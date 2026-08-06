"""Core provisioning logic shared by the CLI (setup/cli.py) and the Streamlit
setup wizard (setup/streamlit_app.py).

BigQuery operations (dataset/table/config creation) go through the
google-cloud-bigquery client, authenticated via Application Default
Credentials (`gcloud auth application-default login`).

Cloud Build, Artifact Registry, Cloud Run Jobs, Cloud Scheduler, IAM, and
Secret Manager operations shell out to the `gcloud` CLI -- kept as plain,
auditable subprocess calls rather than a second set of GCP client libraries.
Requires `gcloud` installed and authenticated, and the caller's account
having sufficient permissions on the target project (Editor/Owner, or the
granular equivalent: Cloud Build Editor, Artifact Registry Admin, Cloud Run
Admin, Cloud Scheduler Admin, Secret Manager Admin, Service Account Admin,
Project IAM Admin, BigQuery Admin).

Each deployment gets two dedicated, minimally-scoped service accounts rather
than reusing the project's default compute service account -- since this
tool is meant for anyone to deploy, the fetch job's runtime identity and the
scheduler's invoker identity shouldn't share one broad principal:

  - psi-fetch-<job_id>: the Cloud Run Job's runtime identity. Gets WRITER on
    just the target BigQuery dataset, secretmanager.secretAccessor on just
    its own PSI API key secret, and bigquery.jobUser at the project level
    (BigQuery's model requires job-creation permission to be granted at the
    project scope, even for an identity that only ever touches one dataset).
  - psi-sched-<job_id>: Cloud Scheduler's OAuth identity. Gets only
    run.invoker on the one Cloud Run Job it triggers -- no BigQuery or
    Secret Manager access at all.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from common.bq_client import ensure_dataset, ensure_metrics_table, get_client, grant_dataset_writer, write_job_config
from common.models import JobConfig
from fetch_job.url_discovery import discover_urls

logger = logging.getLogger(__name__)

LogFn = Callable[[str], None]


class ProvisioningError(RuntimeError):
    pass


def _default_log(message: str) -> None:
    logger.info(message)


def run_gcloud(args: list[str], log: LogFn = _default_log, input_text: str | None = None) -> str:
    cmd = ["gcloud", *args]
    log(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, input=input_text)
    if result.returncode != 0:
        raise ProvisioningError(f"gcloud command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def _gcloud_resource_exists(args: list[str]) -> bool:
    result = subprocess.run(["gcloud", *args], capture_output=True, text=True)
    return result.returncode == 0


def _with_retry(fn: Callable[[], None], description: str, log: LogFn = _default_log, attempts: int = 5, delay_seconds: float = 6.0) -> None:
    """IAM bindings that reference a just-created service account can fail
    for a few seconds while the identity propagates. Retry rather than fail
    the whole deployment on that race."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            fn()
            return
        except Exception as exc:  # gcloud IAM errors and BigQuery API errors both land here
            last_exc = exc
            if attempt < attempts:
                log(f"{description} not ready yet (attempt {attempt}/{attempts}), retrying in {delay_seconds:.0f}s")
                time.sleep(delay_seconds)
    raise last_exc  # type: ignore[misc]


# --------------------------------------------------------------------------
# CSV parsing
# --------------------------------------------------------------------------

_URL_COLUMN_CANDIDATES = {"url", "urls", "website", "link", "page"}


def parse_csv_urls(csv_text: str) -> list[str]:
    """Extract URLs from an uploaded CSV.

    Looks for a url-like column header (url/urls/website/link/page); if the
    file has no such header (e.g. a single unlabeled column), every non-empty
    cell in the first column is treated as a URL.
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    url_col_idx = next((i for i, h in enumerate(header) if h in _URL_COLUMN_CANDIDATES), None)

    data_rows = rows[1:] if url_col_idx is not None else rows
    col_idx = url_col_idx if url_col_idx is not None else 0

    urls = []
    for row in data_rows:
        if col_idx >= len(row):
            continue
        value = row[col_idx].strip()
        if not value:
            continue
        if not value.startswith(("http://", "https://")):
            value = f"https://{value}"
        urls.append(value)

    return list(dict.fromkeys(urls))  # de-dupe, preserve order


def preview_domain_urls(domain: str, max_pages: int = 200) -> list[str]:
    """Free preview of what the fetch job would discover for a domain
    (sitemap first, crawl fallback) -- no PSI API calls involved."""
    return discover_urls(domain, max_pages)


# --------------------------------------------------------------------------
# GCP project / BigQuery browsing
# --------------------------------------------------------------------------

def list_gcp_projects(log: LogFn = _default_log) -> list[dict]:
    output = run_gcloud(["projects", "list", "--format=json"], log=log)
    return json.loads(output) if output else []


def list_bq_datasets(project: str) -> list[str]:
    client = get_client(project)
    return [d.dataset_id for d in client.list_datasets()]


def list_bq_tables(project: str, dataset: str) -> list[str]:
    client = get_client(project)
    return [t.table_id for t in client.list_tables(dataset)]


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------

def interval_to_cron(hours: int) -> str:
    if not (1 <= hours <= 24):
        raise ValueError("interval_hours must be between 1 and 24")
    return "0 0 * * *" if hours == 24 else f"0 */{hours} * * *"


# --------------------------------------------------------------------------
# Deployment plan
# --------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug or "site"


@dataclass
class DeploymentPlan:
    project: str
    region: str
    psi_api_key: str
    source_type: str  # "csv" | "domain"
    interval_hours: int
    target_dataset: str
    target_table: str
    urls: list[str] = field(default_factory=list)
    domain: str | None = None
    max_crawl_pages: int = 200
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    artifact_repo: str = "psi-monitor"
    cloud_run_job_name: str = ""
    scheduler_job_name: str = ""
    fetch_sa_id: str = ""
    scheduler_sa_id: str = ""
    fetch_service_account_email: str | None = None  # override; unset creates a dedicated SA
    scheduler_service_account_email: str | None = None  # override; unset creates a dedicated SA

    def __post_init__(self) -> None:
        base_name = slugify(self.domain or self.target_table)
        if not self.cloud_run_job_name:
            self.cloud_run_job_name = f"psi-fetch-{base_name}-{self.job_id}"
        if not self.scheduler_job_name:
            self.scheduler_job_name = f"psi-schedule-{base_name}-{self.job_id}"
        if not self.fetch_sa_id:
            self.fetch_sa_id = f"psi-fetch-{self.job_id}"
        if not self.scheduler_sa_id:
            self.scheduler_sa_id = f"psi-sched-{self.job_id}"


# --------------------------------------------------------------------------
# Provisioning steps
# --------------------------------------------------------------------------

def ensure_apis_enabled(plan: DeploymentPlan, log: LogFn = _default_log) -> None:
    apis = [
        "run.googleapis.com",
        "cloudscheduler.googleapis.com",
        "cloudbuild.googleapis.com",
        "compute.googleapis.com",  # Cloud Build's managed workers need this enabled on the project
        "artifactregistry.googleapis.com",
        "bigquery.googleapis.com",
        "secretmanager.googleapis.com",
        "iam.googleapis.com",
    ]
    run_gcloud(["services", "enable", *apis, f"--project={plan.project}"], log=log)


def ensure_cloud_build_permissions(plan: DeploymentPlan, log: LogFn = _default_log) -> None:
    """Since mid-2024, GCP no longer auto-grants Editor to a new project's
    default Compute Engine service account -- which `gcloud builds submit`
    uses as its default build identity unless told otherwise. Without this,
    the build fails trying to read its own uploaded source tarball back out
    of the Cloud Build staging bucket. Every fresh project needs this grant
    once; the binding is idempotent to re-apply."""
    project_number = run_gcloud(
        ["projects", "describe", plan.project, "--format=value(projectNumber)"], log=log
    )
    compute_sa = f"{project_number}-compute@developer.gserviceaccount.com"
    _with_retry(
        lambda: run_gcloud([
            "projects", "add-iam-policy-binding", plan.project,
            f"--member=serviceAccount:{compute_sa}",
            "--role=roles/cloudbuild.builds.builder",
            "--condition=None",
        ], log=log),
        description=f"Grant cloudbuild.builds.builder to {compute_sa}",
        log=log,
    )


def ensure_artifact_repo(plan: DeploymentPlan, log: LogFn = _default_log) -> None:
    if _gcloud_resource_exists([
        "artifacts", "repositories", "describe", plan.artifact_repo,
        f"--project={plan.project}", f"--location={plan.region}",
    ]):
        return
    run_gcloud([
        "artifacts", "repositories", "create", plan.artifact_repo,
        "--repository-format=docker", f"--location={plan.region}",
        f"--project={plan.project}",
    ], log=log)


def build_and_push_image(plan: DeploymentPlan, repo_root: str, log: LogFn = _default_log) -> str:
    image_uri = f"{plan.region}-docker.pkg.dev/{plan.project}/{plan.artifact_repo}/psi-fetch-job:latest"
    run_gcloud([
        "builds", "submit", repo_root,
        f"--config={repo_root}/fetch_job/cloudbuild.yaml",
        f"--substitutions=_IMAGE_URI={image_uri}",
        f"--project={plan.project}",
    ], log=log)
    return image_uri


def ensure_service_account(project: str, account_id: str, display_name: str, log: LogFn = _default_log) -> str:
    email = f"{account_id}@{project}.iam.gserviceaccount.com"
    if _gcloud_resource_exists([
        "iam", "service-accounts", "describe", email, f"--project={project}",
    ]):
        return email

    run_gcloud([
        "iam", "service-accounts", "create", account_id,
        f"--project={project}",
        f"--display-name={display_name}",
    ], log=log)
    log(f"Created service account {email}, waiting for it to propagate...")
    time.sleep(10)  # freshly created SAs aren't immediately usable in IAM bindings
    return email


def resolve_fetch_service_account(plan: DeploymentPlan, log: LogFn = _default_log) -> str:
    if plan.fetch_service_account_email:
        return plan.fetch_service_account_email
    return ensure_service_account(
        plan.project, plan.fetch_sa_id, f"PSI fetch job runtime ({plan.job_id})", log=log
    )


def resolve_scheduler_service_account(plan: DeploymentPlan, log: LogFn = _default_log) -> str:
    if plan.scheduler_service_account_email:
        return plan.scheduler_service_account_email
    return ensure_service_account(
        plan.project, plan.scheduler_sa_id, f"PSI scheduler invoker ({plan.job_id})", log=log
    )


def grant_project_role(project: str, member_email: str, role: str, log: LogFn = _default_log) -> None:
    """The only project-scoped grant this tool makes: bigquery.jobUser, which
    BigQuery requires at project level to run queries/streaming inserts even
    when data access itself is scoped to a single dataset."""
    _with_retry(
        lambda: run_gcloud([
            "projects", "add-iam-policy-binding", project,
            f"--member=serviceAccount:{member_email}",
            f"--role={role}",
            "--condition=None",
        ], log=log),
        description=f"Grant {role} to {member_email}",
        log=log,
    )


def ensure_secret(plan: DeploymentPlan, log: LogFn = _default_log) -> str:
    secret_name = f"psi-api-key-{plan.job_id}"
    if not _gcloud_resource_exists([
        "secrets", "describe", secret_name, f"--project={plan.project}",
    ]):
        run_gcloud([
            "secrets", "create", secret_name,
            f"--project={plan.project}", "--replication-policy=automatic",
        ], log=log)

    run_gcloud([
        "secrets", "versions", "add", secret_name,
        f"--project={plan.project}", "--data-file=-",
    ], log=log, input_text=plan.psi_api_key)
    log(f"Stored PSI API key in Secret Manager as '{secret_name}'")
    return secret_name


def grant_secret_access(secret_name: str, service_account: str, plan: DeploymentPlan, log: LogFn = _default_log) -> None:
    _with_retry(
        lambda: run_gcloud([
            "secrets", "add-iam-policy-binding", secret_name,
            f"--project={plan.project}",
            f"--member=serviceAccount:{service_account}",
            "--role=roles/secretmanager.secretAccessor",
        ], log=log),
        description=f"Grant secret access to {service_account}",
        log=log,
    )


def deploy_cloud_run_job(
    plan: DeploymentPlan, image_uri: str, secret_name: str, service_account: str, log: LogFn = _default_log
) -> None:
    env_vars = {
        "CONFIG_PROJECT": plan.project,
        "CONFIG_DATASET": plan.target_dataset,
        "JOB_ID": plan.job_id,
        "MAX_WORKERS": "5",
    }
    env_vars_str = ",".join(f"{k}={v}" for k, v in env_vars.items())

    _with_retry(
        lambda: run_gcloud([
            "run", "jobs", "deploy", plan.cloud_run_job_name,
            f"--image={image_uri}",
            f"--region={plan.region}",
            f"--project={plan.project}",
            f"--set-env-vars={env_vars_str}",
            f"--set-secrets=PSI_API_KEY={secret_name}:latest",
            f"--service-account={service_account}",
            "--tasks=1",
            "--max-retries=1",
            "--task-timeout=30m",
        ], log=log),
        description=f"Deploy Cloud Run Job with runtime SA {service_account}",
        log=log,
    )


def grant_run_invoker(plan: DeploymentPlan, service_account: str, log: LogFn = _default_log) -> None:
    _with_retry(
        lambda: run_gcloud([
            "run", "jobs", "add-iam-policy-binding", plan.cloud_run_job_name,
            f"--project={plan.project}", f"--region={plan.region}",
            f"--member=serviceAccount:{service_account}",
            "--role=roles/run.invoker",
        ], log=log),
        description=f"Grant run.invoker to {service_account}",
        log=log,
    )


def create_scheduler_job(plan: DeploymentPlan, service_account: str, log: LogFn = _default_log) -> None:
    uri = (
        f"https://{plan.region}-run.googleapis.com/apis/run.googleapis.com/v1/"
        f"namespaces/{plan.project}/jobs/{plan.cloud_run_job_name}:run"
    )
    cron = interval_to_cron(plan.interval_hours)
    action = "update" if _gcloud_resource_exists([
        "scheduler", "jobs", "describe", plan.scheduler_job_name,
        f"--project={plan.project}", f"--location={plan.region}",
    ]) else "create"

    _with_retry(
        lambda: run_gcloud([
            "scheduler", "jobs", action, "http", plan.scheduler_job_name,
            f"--project={plan.project}",
            f"--location={plan.region}",
            f"--schedule={cron}",
            f"--uri={uri}",
            "--http-method=POST",
            f"--oauth-service-account-email={service_account}",
        ], log=log),
        description=f"Create/update Scheduler job with OAuth SA {service_account}",
        log=log,
    )


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------

def provision(plan: DeploymentPlan, repo_root: str, log: LogFn = _default_log) -> dict:
    log(f"Starting provisioning for job_id={plan.job_id}")

    bq_client = get_client(plan.project)
    ensure_dataset(bq_client, plan.project, plan.target_dataset)
    ensure_metrics_table(bq_client, plan.project, plan.target_dataset, plan.target_table)
    log(f"BigQuery ready: {plan.project}.{plan.target_dataset}.{plan.target_table}")

    config = JobConfig(
        job_id=plan.job_id,
        source_type=plan.source_type,
        interval_hours=plan.interval_hours,
        target_project=plan.project,
        target_dataset=plan.target_dataset,
        target_table=plan.target_table,
        urls=plan.urls,
        domain=plan.domain,
        max_crawl_pages=plan.max_crawl_pages,
    )
    write_job_config(bq_client, plan.project, plan.target_dataset, config)
    log(f"Wrote job config (job_id={plan.job_id}) to psi_monitor_config")

    ensure_apis_enabled(plan, log=log)
    ensure_artifact_repo(plan, log=log)
    ensure_cloud_build_permissions(plan, log=log)
    image_uri = build_and_push_image(plan, repo_root, log=log)
    log(f"Built and pushed image: {image_uri}")

    fetch_sa = resolve_fetch_service_account(plan, log=log)
    scheduler_sa = resolve_scheduler_service_account(plan, log=log)
    log(f"Fetch job runtime service account: {fetch_sa}")
    log(f"Scheduler invoker service account: {scheduler_sa}")

    _with_retry(
        lambda: grant_dataset_writer(bq_client, plan.project, plan.target_dataset, fetch_sa),
        description=f"Grant dataset WRITER to {fetch_sa}",
        log=log,
    )
    grant_project_role(plan.project, fetch_sa, "roles/bigquery.jobUser", log=log)

    secret_name = ensure_secret(plan, log=log)
    grant_secret_access(secret_name, fetch_sa, plan, log=log)

    deploy_cloud_run_job(plan, image_uri, secret_name, fetch_sa, log=log)
    grant_run_invoker(plan, scheduler_sa, log=log)
    create_scheduler_job(plan, scheduler_sa, log=log)

    log("Provisioning complete.")
    return {
        "job_id": plan.job_id,
        "cloud_run_job": plan.cloud_run_job_name,
        "scheduler_job": plan.scheduler_job_name,
        "fetch_service_account": fetch_sa,
        "scheduler_service_account": scheduler_sa,
        "target_table": f"{plan.project}.{plan.target_dataset}.{plan.target_table}",
        "cron": interval_to_cron(plan.interval_hours),
    }
