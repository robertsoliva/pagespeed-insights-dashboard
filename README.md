# PageSpeed Insights Dashboard

Open-source, self-hosted PageSpeed Insights monitoring: point it at a CSV of
URLs (or a whole domain), pick how often to check, and it deploys a scheduled
Cloud Run Job that writes results into BigQuery, plus a Streamlit dashboard
to visualize the trend.

## How it works

1. **Setup** (CLI or Streamlit wizard) — upload a CSV of URLs, or give it a
   root domain to monitor in full (discovered via `sitemap.xml`, falling
   back to a robots.txt-respecting crawl, capped at a max page count).
2. Pick a run interval (every 1–24 hours).
3. Connect to your GCP project (via `gcloud`/Application Default
   Credentials — no key files).
4. Pick or create a BigQuery dataset + table to append results to.
5. The tool provisions: a BigQuery config table + metrics table, an
   Artifact Registry repo, a container image (built via Cloud Build), a
   **Cloud Run Job**, a **Cloud Scheduler** trigger, a Secret Manager
   secret for your PageSpeed API key, and two dedicated, minimally-scoped
   service accounts (see below).
6. The **Streamlit dashboard** reads from BigQuery: toggle Desktop/Mobile,
   pick a URL (or average across all of them), and see trends over a
   configurable lookback window — ordered from Core Web Vitals down to the
   long tail of optimization opportunities.

## Project layout

```
common/         Shared code: canonical metric definitions, BigQuery schema,
                config models, BigQuery client helpers.
fetch_job/      The Cloud Run Job: PSI API client, URL discovery
                (sitemap/crawl), metric extraction, BigQuery writer.
setup/          Provisioning: shared core logic, a Typer CLI, and a
                Streamlit setup wizard -- both call the same core.
dashboard/      The Streamlit visualization app.
tests/          Unit tests (pytest).
```

## Prerequisites

- Python 3.11+
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install), authenticated:
  ```
  gcloud auth login
  gcloud auth application-default login
  ```
- A GCP project with billing enabled, and your account having sufficient
  permissions to run setup (Editor/Owner, or the granular equivalent: Cloud
  Build, Artifact Registry, Cloud Run, Cloud Scheduler, Secret Manager,
  Service Account Admin, Project IAM Admin, and BigQuery admin roles). This
  is a one-time cost to the person running setup — see below for what the
  deployed resources themselves actually run as.
- A [PageSpeed Insights API key](https://developers.google.com/speed/docs/insights/v5/get-started).

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Provision a monitoring job

CLI:

```bash
# From a CSV of URLs, checked every 6 hours
python -m setup.cli deploy \
    --project my-gcp-project --region us-central1 \
    --csv urls.csv --interval-hours 6 \
    --dataset psi_monitor --table psi_metrics \
    --psi-api-key "$PSI_API_KEY"

# Whole-site monitoring via sitemap/crawl discovery, checked daily
python -m setup.cli deploy \
    --project my-gcp-project --region us-central1 \
    --domain example.com --interval-hours 24 \
    --dataset psi_monitor --table psi_metrics \
    --psi-api-key "$PSI_API_KEY"
```

Or the Streamlit wizard:

```bash
streamlit run setup/streamlit_app.py
```

## View the dashboard

```bash
streamlit run dashboard/app.py
```

Enter the same project/dataset/table in the sidebar and connect.

## IAM model

Since this is meant for anyone to deploy, each deployment gets two dedicated
service accounts instead of reusing the project's default compute identity:

| Service account | Used by | Permissions |
|---|---|---|
| `psi-fetch-<job_id>` | The Cloud Run Job at runtime | `WRITER` on just the target BigQuery **dataset** (dataset-level ACL, not project-wide); `secretmanager.secretAccessor` on just its own PSI API key secret; `roles/bigquery.jobUser` at the project level (unavoidable — BigQuery requires job-creation permission to be granted at project scope even when data access is dataset-scoped) |
| `psi-sched-<job_id>` | Cloud Scheduler's OAuth trigger | `roles/run.invoker` on just the one Cloud Run Job it triggers — no BigQuery or Secret Manager access at all |

Both accounts are created automatically per deployment (`ensure_service_account`
in `setup/core.py`); IAM bindings that reference a just-created account retry
for up to ~30s to ride out identity-propagation delay. Pass
`--fetch-service-account` / `--scheduler-service-account` (CLI) or use the
"Advanced: service accounts" section (Streamlit wizard) to reuse existing
accounts instead.

## Notes

- The PSI API key is stored in Secret Manager, never as a literal
  environment variable.
- The metrics table is one row per `(run, url, device)`, partitioned by day
  on `fetched_at`. The full metric list — and the tiered importance order
  the dashboard renders in — lives in `common/metrics_spec.py`; add a
  metric there and it shows up in both the fetch job and the dashboard
  automatically.
- Domain-mode discovery is capped (`--max-crawl-pages`, default 200) since
  every discovered URL costs a PageSpeed API call per device.
