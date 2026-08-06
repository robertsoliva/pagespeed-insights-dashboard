"""CLI for provisioning a PageSpeed Insights monitoring job.

Examples:

    # From a CSV of URLs, checked every 6 hours
    python -m setup.cli deploy \\
        --project my-gcp-project --region us-central1 \\
        --csv urls.csv --interval-hours 6 \\
        --dataset psi_monitor --table psi_metrics

    # Whole-site monitoring via sitemap/crawl discovery, checked daily
    python -m setup.cli deploy \\
        --project my-gcp-project --region us-central1 \\
        --domain example.com --interval-hours 24 \\
        --dataset psi_monitor --table psi_metrics

Requires `gcloud auth login` and `gcloud auth application-default login` to
have been run already, and PSI_API_KEY set in the environment (or passed via
--psi-api-key).
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from setup.core import (
    DeploymentPlan,
    ProvisioningError,
    list_bq_datasets,
    list_bq_tables,
    list_gcp_projects,
    parse_csv_urls,
    preview_domain_urls,
    provision,
)

app = typer.Typer(add_completion=False)
REPO_ROOT = str(Path(__file__).resolve().parent.parent)


@app.command()
def list_projects() -> None:
    """List GCP projects visible to the current gcloud account."""
    for project in list_gcp_projects():
        typer.echo(f"{project['projectId']}\t{project.get('name', '')}")


@app.command()
def list_datasets(project: str) -> None:
    """List BigQuery datasets in a project."""
    for dataset in list_bq_datasets(project):
        typer.echo(dataset)


@app.command()
def list_tables(project: str, dataset: str) -> None:
    """List BigQuery tables in a dataset."""
    for table in list_bq_tables(project, dataset):
        typer.echo(table)


@app.command()
def preview_domain(domain: str, max_pages: int = 200) -> None:
    """Preview which URLs would be discovered for a domain (sitemap/crawl), no PSI calls."""
    urls = preview_domain_urls(domain, max_pages)
    typer.echo(f"Discovered {len(urls)} URLs:")
    for url in urls:
        typer.echo(f"  {url}")


@app.command()
def deploy(
    project: str = typer.Option(..., help="GCP project ID"),
    region: str = typer.Option("us-central1", help="GCP region for Cloud Run/Scheduler/Artifact Registry"),
    dataset: str = typer.Option(..., help="BigQuery dataset (created if missing)"),
    table: str = typer.Option(..., help="BigQuery table to append metrics to (created if missing)"),
    interval_hours: int = typer.Option(..., min=1, max=24, help="How often to run, in hours (1-24)"),
    csv: str | None = typer.Option(None, help="Path to a CSV of URLs to monitor"),
    domain: str | None = typer.Option(None, help="Root domain to monitor in full (sitemap/crawl discovery)"),
    max_crawl_pages: int = typer.Option(200, help="Cap on discovered URLs when --domain is used"),
    psi_api_key: str | None = typer.Option(None, envvar="PSI_API_KEY", help="PageSpeed Insights API key"),
    fetch_service_account: str | None = typer.Option(
        None, help="Override: use this SA for the fetch job instead of creating psi-fetch-<job_id>"
    ),
    scheduler_service_account: str | None = typer.Option(
        None, help="Override: use this SA for the Scheduler trigger instead of creating psi-sched-<job_id>"
    ),
) -> None:
    """Provision BigQuery tables, a Cloud Run Job, and a Cloud Scheduler trigger."""
    if bool(csv) == bool(domain):
        raise typer.BadParameter("Pass exactly one of --csv or --domain")
    if not psi_api_key:
        raise typer.BadParameter("PSI API key required: pass --psi-api-key or set PSI_API_KEY")

    if csv:
        csv_text = Path(csv).read_text()
        urls = parse_csv_urls(csv_text)
        if not urls:
            raise typer.BadParameter(f"No URLs found in {csv}")
        typer.echo(f"Parsed {len(urls)} URLs from {csv}")
        plan = DeploymentPlan(
            project=project, region=region, psi_api_key=psi_api_key,
            source_type="csv", interval_hours=interval_hours,
            target_dataset=dataset, target_table=table, urls=urls,
            fetch_service_account_email=fetch_service_account,
            scheduler_service_account_email=scheduler_service_account,
        )
    else:
        preview = preview_domain_urls(domain, max_crawl_pages)
        typer.echo(f"Preview: {len(preview)} URLs discovered for {domain} (capped at {max_crawl_pages})")
        plan = DeploymentPlan(
            project=project, region=region, psi_api_key=psi_api_key,
            source_type="domain", interval_hours=interval_hours,
            target_dataset=dataset, target_table=table,
            domain=domain, max_crawl_pages=max_crawl_pages,
            fetch_service_account_email=fetch_service_account,
            scheduler_service_account_email=scheduler_service_account,
        )

    try:
        result = provision(plan, repo_root=REPO_ROOT, log=typer.echo)
    except ProvisioningError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    typer.secho("\nDone.", fg=typer.colors.GREEN)
    for key, value in result.items():
        typer.echo(f"  {key}: {value}")


if __name__ == "__main__":
    app()
