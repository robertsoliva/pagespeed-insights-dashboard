"""BigQuery read queries backing the dashboard."""

from __future__ import annotations

import pandas as pd
from google.cloud import bigquery

from common.bq_client import get_client


def list_urls(project: str, dataset: str, table: str) -> list[str]:
    client = get_client(project)
    query = f"SELECT DISTINCT url FROM `{project}.{dataset}.{table}` ORDER BY url"
    return [row.url for row in client.query(query).result()]


def get_trend_data(
    project: str,
    dataset: str,
    table: str,
    device: str,
    lookback_days: int,
    url: str | None = None,
    urls: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch trend rows. `url` filters to one exact page; `urls` filters to a
    group (e.g. a website section); passing neither returns every page."""
    client = get_client(project)
    where = ["device = @device", "fetched_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)"]
    params = [
        bigquery.ScalarQueryParameter("device", "STRING", device),
        bigquery.ScalarQueryParameter("days", "INT64", lookback_days),
    ]
    if url:
        where.append("url = @url")
        params.append(bigquery.ScalarQueryParameter("url", "STRING", url))
    elif urls:
        where.append("url IN UNNEST(@urls)")
        params.append(bigquery.ArrayQueryParameter("urls", "STRING", urls))

    query = f"SELECT * FROM `{project}.{dataset}.{table}` WHERE {' AND '.join(where)} ORDER BY fetched_at"
    return client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).to_dataframe()
