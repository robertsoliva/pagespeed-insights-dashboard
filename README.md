# PageSpeed Insights Dashboard

Open-source, self-hosted PageSpeed Insights monitoring: point it at a CSV of
URLs (or a whole domain), pick how often to check, and it deploys a scheduled
Cloud Run Job that writes results into BigQuery, plus a Streamlit dashboard
to visualize the trend.

## Quick start

Setup and the dashboard are two tabs of **one running app** -- this is the
only command you need for the whole journey, both the first time and every
time after:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
streamlit run app.py
```

That opens a browser tab with **Setup** and **Dashboard** in the sidebar:

1. **Setup** -- a one-time step per site: upload a CSV of URLs or give it a
   domain, pick a run interval, connect to your GCP project, and deploy.
   (See Prerequisites below for what needs to be in place first.)
2. **Dashboard** -- once deployed, switch to this tab to see the trends.
   Come back here later with the same `streamlit run app.py` command --
   nothing needs redeploying, the Cloud Run Job and Scheduler keep running
   in GCP on their own. Right after deploying it'll be empty or a single
   flat point; see "View the dashboard" below for why, and how to skip the
   wait.

Don't have `gcloud` set up yet, or want the CLI instead for scripting? Keep
reading -- everything below covers both paths in more detail.

## How it works

1. **Setup** (CLI or Streamlit wizard) — upload a CSV of URLs, or give it a
   root domain to monitor in full (discovered via `sitemap.xml`, falling
   back to a robots.txt-respecting crawl, capped at a max page count).
2. Pick a run interval (every 1–24 hours; 2–6h recommended, see below).
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
- A [PageSpeed Insights API key](https://developers.google.com/speed/docs/insights/v5/get-started) --
  or skip getting one yourself: both the wizard and the CLI (`create-key`)
  can generate one restricted to your chosen project in one step.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Provision a monitoring job

**The Streamlit wizard is the primary path** -- see Quick start above:
`streamlit run app.py`, then the Setup tab. It walks through source (CSV or
domain), interval, GCP project, a PageSpeed API key (paste your own, or
generate one for the selected project with one click), and the BigQuery
destination, then deploys. Each page also runs standalone if you only want
one of the two:

```bash
streamlit run setup/streamlit_app.py
streamlit run dashboard/app.py
```

### Alternative: CLI

For scripting or CI, `setup/cli.py` does the same thing non-interactively:

```bash
# No PSI API key yet? Generate one restricted to this project:
python -m setup.cli create-key --project my-gcp-project

# From a CSV of URLs, checked every 4 hours (2-6h recommended, see below)
python -m setup.cli deploy \
    --project my-gcp-project --region us-central1 \
    --csv urls.csv --interval-hours 4 \
    --dataset psi_monitor --table psi_metrics \
    --psi-api-key "$PSI_API_KEY"

# Whole-site monitoring via sitemap/crawl discovery, checked every 6 hours
python -m setup.cli deploy \
    --project my-gcp-project --region us-central1 \
    --domain example.com --interval-hours 6 \
    --dataset psi_monitor --table psi_metrics \
    --psi-api-key "$PSI_API_KEY"
```

### Picking an interval

PageSpeed scores vary run to run even with nothing changed on the site --
network jitter, host load, and Lighthouse's own simulated throttling all add
noise. A single check a day can't tell a real regression from a one-off
fluke, so **2-6 hours is the recommended range**: enough samples per day to
see a genuine pattern, without over-polling. Both the wizard and the CLI
default to 4 hours.

## View the dashboard

In the sidebar, click "Load my GCP projects" and pick your way down through
project → dataset → table (the same picker the Setup page uses), or type
them directly if you'd rather skip the `gcloud` round-trip. Setup hands
these over automatically if you just deployed in the same session -- this
picker is for opening the dashboard fresh, or pointing it at a different
site.

**Give it a few runs before judging the trends:** right after deploying,
the dashboard will be empty (or show a single flat data point) until Cloud
Scheduler has actually fired -- which, depending on the interval you chose
in Setup, could be up to that many hours away. The whole point of this tool
is trends over time, so a single run isn't very informative yet. To see
movement sooner without waiting, trigger the Cloud Run Job manually a few
times:

```bash
gcloud run jobs execute <cloud-run-job-name> --region <region>
```

(the job and region names are in the JSON Setup prints when it finishes
deploying). The dashboard itself will also tell you when it's working with
too few runs to be meaningful yet.

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
