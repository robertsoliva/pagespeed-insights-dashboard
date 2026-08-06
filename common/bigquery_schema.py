"""BigQuery table schemas, generated from the canonical metric list in metrics_spec.py."""

from __future__ import annotations

from google.cloud import bigquery

from common.metrics_spec import IDENTITY_FIELDS, METRICS

# Name of the config table that lives alongside every metrics table. One row
# per monitoring job (one CSV upload or one domain, deployed as one Cloud Run
# Job + Cloud Scheduler trigger).
CONFIG_TABLE_NAME = "psi_monitor_config"


def metrics_table_schema() -> list[bigquery.SchemaField]:
    fields = [
        bigquery.SchemaField(name, field_type, mode="REQUIRED" if name in ("run_id", "job_id", "fetched_at", "url", "device") else "NULLABLE")
        for name, field_type in IDENTITY_FIELDS
    ]
    fields += [
        bigquery.SchemaField(metric.name, metric.bq_type, mode="NULLABLE")
        for metric in METRICS
    ]
    return fields


def config_table_schema() -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField("job_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("enabled", "BOOL", mode="REQUIRED"),
        bigquery.SchemaField("source_type", "STRING", mode="REQUIRED"),  # "csv" | "domain"
        bigquery.SchemaField("urls", "STRING", mode="REPEATED"),         # explicit list, source_type == "csv"
        bigquery.SchemaField("domain", "STRING", mode="NULLABLE"),       # source_type == "domain"
        bigquery.SchemaField("max_crawl_pages", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("interval_hours", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("target_project", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("target_dataset", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("target_table", "STRING", mode="REQUIRED"),
    ]
