"""Streamlit setup wizard: upload a CSV or point at a domain, pick a schedule,
connect to a GCP project, and deploy the Cloud Run Job + Cloud Scheduler
trigger that will keep it running.

Run with: streamlit run setup/streamlit_app.py

Requires `gcloud auth login` and `gcloud auth application-default login` to
have been run on this machine already.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

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

REPO_ROOT = str(Path(__file__).resolve().parent.parent)

st.set_page_config(page_title="PSI Monitor Setup", page_icon="⚙️", layout="centered")
st.title("PageSpeed Insights Monitor — Setup")
st.caption("Provisions BigQuery tables, a Cloud Run Job, and a Cloud Scheduler trigger for scheduled PageSpeed monitoring.")

# --- 1. What to monitor ------------------------------------------------------
st.header("1. What to monitor")
source_mode = st.radio("Source", ["Upload a CSV of URLs", "Monitor a whole domain"], horizontal=True)

urls: list[str] = []
domain: str | None = None
max_crawl_pages = 200

if source_mode == "Upload a CSV of URLs":
    uploaded = st.file_uploader("CSV file (a column named url/urls/website/link, or a single unlabeled column)", type=["csv"])
    if uploaded is not None:
        urls = parse_csv_urls(uploaded.getvalue().decode("utf-8"))
        if urls:
            st.success(f"Parsed {len(urls)} URLs")
            with st.expander("Preview URLs"):
                st.write(urls[:50])
        else:
            st.error("No URLs found in that file.")
else:
    domain = st.text_input("Root domain (e.g. example.com)")
    max_crawl_pages = st.slider("Max pages to discover", 10, 1000, 200, step=10)
    if domain and st.button("Preview discovered URLs"):
        with st.spinner("Checking sitemap.xml, falling back to a crawl if needed..."):
            preview = preview_domain_urls(domain, max_crawl_pages)
        st.success(f"Discovered {len(preview)} URLs (this preview costs no PSI API calls)")
        with st.expander("Preview URLs"):
            st.write(preview[:50])

# --- 2. How often -------------------------------------------------------------
st.header("2. How often")
interval_hours = st.select_slider("Run every N hours", options=[1, 2, 3, 4, 6, 8, 12, 24], value=6)

# --- 3. Connect to GCP ---------------------------------------------------------
st.header("3. Connect to GCP")
psi_api_key = st.text_input("PageSpeed Insights API key", type="password", help="Stored in Secret Manager, never in plain env vars.")

if st.button("Load my GCP projects"):
    with st.spinner("Listing projects via gcloud..."):
        try:
            st.session_state["projects"] = list_gcp_projects()
        except Exception as exc:
            st.error(f"Couldn't list projects (is `gcloud auth login` done?): {exc}")

projects = st.session_state.get("projects", [])
project_ids = [p["projectId"] for p in projects]
project = st.selectbox("GCP project", project_ids) if project_ids else st.text_input("GCP project ID")
region = st.selectbox("Region", ["us-central1", "europe-west1", "asia-southeast1", "us-east1"], index=0)

# --- 4. BigQuery destination ---------------------------------------------------
st.header("4. Choose a BigQuery destination")

dataset_mode = st.radio("Dataset", ["Select existing", "Create new"], horizontal=True)
if dataset_mode == "Select existing" and project:
    try:
        datasets = list_bq_datasets(project)
    except Exception:
        datasets = []
    dataset = st.selectbox("Dataset", datasets) if datasets else st.text_input("Dataset ID (none found — will be created)", value="psi_monitor")
else:
    dataset = st.text_input("New dataset ID", value="psi_monitor")

table_mode = st.radio("Table", ["Select existing", "Create new"], horizontal=True)
if table_mode == "Select existing" and project and dataset:
    try:
        tables = list_bq_tables(project, dataset)
    except Exception:
        tables = []
    table = st.selectbox("Table", tables) if tables else st.text_input("Table ID (none found — will be created)", value="psi_metrics")
else:
    table = st.text_input("New table ID", value="psi_metrics")

# --- Advanced: service accounts ------------------------------------------------
with st.expander("Advanced: service accounts"):
    st.caption(
        "By default, two dedicated service accounts are created per deployment: "
        "one for the fetch job's runtime (dataset-scoped BigQuery write + its own secret), "
        "one for Cloud Scheduler's OAuth invoker (run.invoker on this job only). "
        "Override only if you already have accounts you want to reuse."
    )
    fetch_service_account = st.text_input("Fetch job service account (optional)") or None
    scheduler_service_account = st.text_input("Scheduler invoker service account (optional)") or None

# --- 5. Deploy -------------------------------------------------------------
st.header("5. Deploy")
ready = bool(project and dataset and table and psi_api_key and (urls or domain))
if not ready:
    st.info("Fill in the steps above to enable deployment.")

if st.button("Deploy Cloud Run Job + Scheduler", disabled=not ready, type="primary"):
    log_box = st.empty()
    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(message)
        log_box.code("\n".join(lines))

    plan = DeploymentPlan(
        project=project,
        region=region,
        psi_api_key=psi_api_key,
        source_type="csv" if urls else "domain",
        interval_hours=interval_hours,
        target_dataset=dataset,
        target_table=table,
        urls=urls,
        domain=domain,
        max_crawl_pages=max_crawl_pages,
        fetch_service_account_email=fetch_service_account,
        scheduler_service_account_email=scheduler_service_account,
    )

    try:
        with st.spinner("Provisioning (this can take a few minutes, mostly the container build)..."):
            result = provision(plan, repo_root=REPO_ROOT, log=log)
    except ProvisioningError as exc:
        st.error(str(exc))
    else:
        st.success("Deployed.")
        st.json(result)
        st.caption("Run the dashboard with: streamlit run dashboard/app.py")
