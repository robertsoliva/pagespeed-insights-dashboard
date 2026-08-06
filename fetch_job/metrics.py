"""Flattens a raw PSI v5 JSON response into a BigQuery row, using the canonical
metric definitions in common/metrics_spec.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from common.metrics_spec import METRICS, safe_get


def build_row(run_id: str, job_id: str, url: str, device: str, psi_json: dict) -> dict:
    row: dict = {
        "run_id": run_id,
        "job_id": job_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "device": device,
    }

    for metric in METRICS:
        value = safe_get(psi_json, metric.path, as_string=(metric.bq_type == "STRING"))
        if value is not None and metric.scale_to_100:
            value = value * 100
        row[metric.name] = value

    return row
