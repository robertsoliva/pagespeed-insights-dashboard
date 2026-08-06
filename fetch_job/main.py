"""Cloud Run Job entrypoint: one execution = one monitoring run for one job_id.

Required environment variables (set at `gcloud run jobs deploy` / `gcloud run
jobs execute --update-env-vars` time):
    CONFIG_PROJECT   GCP project holding the psi_monitor_config table
    CONFIG_DATASET   dataset holding the psi_monitor_config table
    JOB_ID           which config row to run (one job_id per monitored site)
    PSI_API_KEY      PageSpeed Insights API key (bind via Secret Manager, not a literal env var)
    MAX_WORKERS      optional, default 5 -- concurrent PSI requests
"""

from __future__ import annotations

import logging
import os
import sys
import uuid

from common.bq_client import ensure_dataset, ensure_metrics_table, get_client, insert_metric_rows, read_job_config
from fetch_job.metrics import build_row
from fetch_job.psi_client import fetch_all
from fetch_job.url_discovery import discover_urls

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fetch_job")


def _env(name: str, required: bool = True, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def main() -> int:
    config_project = _env("CONFIG_PROJECT")
    config_dataset = _env("CONFIG_DATASET")
    job_id = _env("JOB_ID")
    psi_api_key = _env("PSI_API_KEY")
    max_workers = int(_env("MAX_WORKERS", required=False, default="5"))

    client = get_client(config_project)
    config = read_job_config(client, config_project, config_dataset, job_id)

    if config.source_type == "csv":
        urls = config.urls
        logger.info("Job %s: using %d explicit URLs from config", job_id, len(urls))
    else:
        urls = discover_urls(config.domain, config.max_crawl_pages)
        logger.info("Job %s: discovered %d URLs for domain %s", job_id, len(urls), config.domain)

    if not urls:
        logger.warning("Job %s: no URLs to check, exiting", job_id)
        return 0

    target_client = client if config.target_project == config_project else get_client(config.target_project)
    ensure_dataset(target_client, config.target_project, config.target_dataset)
    ensure_metrics_table(target_client, config.target_project, config.target_dataset, config.target_table)

    run_id = str(uuid.uuid4())
    results = fetch_all(urls, psi_api_key, max_workers=max_workers)

    rows = []
    failures = 0
    for url, device, psi_json in results:
        if psi_json is None:
            failures += 1
            continue
        rows.append(build_row(run_id, job_id, url, device, psi_json))

    insert_metric_rows(target_client, config.target_project, config.target_dataset, config.target_table, rows)
    logger.info(
        "Job %s run %s: inserted %d rows, %d failures out of %d requests",
        job_id, run_id, len(rows), failures, len(results),
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
