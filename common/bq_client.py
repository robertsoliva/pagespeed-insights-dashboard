"""BigQuery helpers shared by the setup tool, fetch job, and dashboard.

Authentication is always via Application Default Credentials -- run
`gcloud auth application-default login` once on the machine that runs the
setup tool. The Cloud Run Job picks up ADC automatically from its attached
service account; no key files are read or written by this project.
"""

from __future__ import annotations

import logging

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from common.bigquery_schema import CONFIG_TABLE_NAME, config_table_schema, metrics_table_schema
from common.models import JobConfig

logger = logging.getLogger(__name__)


def get_client(project: str) -> bigquery.Client:
    return bigquery.Client(project=project)


def ensure_dataset(client: bigquery.Client, project: str, dataset: str, location: str = "US") -> None:
    dataset_ref = bigquery.DatasetReference(project, dataset)
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        logger.info("Creating BigQuery dataset %s.%s", project, dataset)
        client.create_dataset(bigquery.Dataset(dataset_ref, location=location))


def ensure_metrics_table(client: bigquery.Client, project: str, dataset: str, table: str) -> None:
    table_ref = bigquery.TableReference(bigquery.DatasetReference(project, dataset), table)
    try:
        client.get_table(table_ref)
    except NotFound:
        logger.info("Creating BigQuery table %s.%s.%s", project, dataset, table)
        bq_table = bigquery.Table(table_ref, schema=metrics_table_schema())
        bq_table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field="fetched_at"
        )
        client.create_table(bq_table)


def ensure_config_table(client: bigquery.Client, project: str, dataset: str) -> None:
    table_ref = bigquery.TableReference(bigquery.DatasetReference(project, dataset), CONFIG_TABLE_NAME)
    try:
        client.get_table(table_ref)
    except NotFound:
        logger.info("Creating BigQuery config table %s.%s.%s", project, dataset, CONFIG_TABLE_NAME)
        client.create_table(bigquery.Table(table_ref, schema=config_table_schema()))


def write_job_config(client: bigquery.Client, project: str, dataset: str, config: JobConfig) -> None:
    ensure_config_table(client, project, dataset)
    table_ref = f"{project}.{dataset}.{CONFIG_TABLE_NAME}"
    errors = client.insert_rows_json(table_ref, [config.to_bq_row()])
    if errors:
        raise RuntimeError(f"Failed to write job config: {errors}")


def read_job_config(client: bigquery.Client, project: str, dataset: str, job_id: str) -> JobConfig:
    query = f"""
        SELECT * FROM `{project}.{dataset}.{CONFIG_TABLE_NAME}`
        WHERE job_id = @job_id AND enabled = TRUE
        ORDER BY created_at DESC
        LIMIT 1
    """
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("job_id", "STRING", job_id)]
        ),
    )
    rows = list(job.result())
    if not rows:
        raise LookupError(f"No enabled config found for job_id={job_id!r} in {project}.{dataset}.{CONFIG_TABLE_NAME}")
    return JobConfig.from_bq_row(dict(rows[0].items()))


def grant_dataset_writer(client: bigquery.Client, project: str, dataset: str, member_email: str) -> None:
    """Grants a service account WRITER access on a dataset (read/write/create
    tables within it) without touching project-level IAM -- the minimal
    dataset-scoped grant the fetch job's runtime identity needs."""
    dataset_ref = bigquery.DatasetReference(project, dataset)
    bq_dataset = client.get_dataset(dataset_ref)
    entry = bigquery.AccessEntry(role="WRITER", entity_type="userByEmail", entity_id=member_email)
    if entry in bq_dataset.access_entries:
        return
    bq_dataset.access_entries = list(bq_dataset.access_entries) + [entry]
    client.update_dataset(bq_dataset, ["access_entries"])


def insert_metric_rows(client: bigquery.Client, project: str, dataset: str, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    table_ref = f"{project}.{dataset}.{table}"
    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"Failed to insert {len(rows)} metric rows into {table_ref}: {errors}")
    logger.info("Inserted %d rows into %s", len(rows), table_ref)
