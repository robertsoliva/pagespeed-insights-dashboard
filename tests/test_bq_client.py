"""Constructs the real google-cloud-bigquery objects (no mocking of the
library's own classes) so a constructor-signature mismatch -- e.g. passing a
kwarg the installed library version doesn't accept -- fails here instead of
mid-deploy against a real project."""

from unittest.mock import MagicMock

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from common.bq_client import ensure_config_table, ensure_dataset, ensure_metrics_table


def test_ensure_dataset_creates_when_missing():
    client = MagicMock()
    client.get_dataset.side_effect = NotFound("nope")

    ensure_dataset(client, "proj", "ds", location="US")

    assert client.create_dataset.called
    created = client.create_dataset.call_args[0][0]
    assert isinstance(created, bigquery.Dataset)
    assert created.location == "US"


def test_ensure_dataset_noop_when_exists():
    client = MagicMock()
    client.get_dataset.return_value = bigquery.Dataset("proj.ds")

    ensure_dataset(client, "proj", "ds")

    client.create_dataset.assert_not_called()


def test_ensure_metrics_table_creates_when_missing():
    client = MagicMock()
    client.get_table.side_effect = NotFound("nope")

    ensure_metrics_table(client, "proj", "ds", "tbl")

    assert client.create_table.called
    created = client.create_table.call_args[0][0]
    assert isinstance(created, bigquery.Table)
    assert created.time_partitioning.field == "fetched_at"


def test_ensure_config_table_creates_when_missing():
    client = MagicMock()
    client.get_table.side_effect = NotFound("nope")

    ensure_config_table(client, "proj", "ds")

    assert client.create_table.called
    created = client.create_table.call_args[0][0]
    assert isinstance(created, bigquery.Table)
