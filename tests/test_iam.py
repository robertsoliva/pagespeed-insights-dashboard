from unittest.mock import MagicMock

import pytest
from google.cloud import bigquery

from common.bq_client import grant_dataset_writer
from setup.core import DeploymentPlan, _with_retry


def test_deployment_plan_derives_dedicated_service_account_ids():
    plan = DeploymentPlan(
        project="proj", region="us-central1", psi_api_key="key",
        source_type="domain", interval_hours=6,
        target_dataset="ds", target_table="tbl", domain="example.com",
    )
    assert plan.fetch_sa_id == f"psi-fetch-{plan.job_id}"
    assert plan.scheduler_sa_id == f"psi-sched-{plan.job_id}"
    assert plan.fetch_service_account_email is None
    assert plan.scheduler_service_account_email is None


def test_deployment_plan_respects_service_account_override():
    plan = DeploymentPlan(
        project="proj", region="us-central1", psi_api_key="key",
        source_type="domain", interval_hours=6,
        target_dataset="ds", target_table="tbl", domain="example.com",
        fetch_service_account_email="custom-fetch@proj.iam.gserviceaccount.com",
        scheduler_service_account_email="custom-sched@proj.iam.gserviceaccount.com",
    )
    assert plan.fetch_service_account_email == "custom-fetch@proj.iam.gserviceaccount.com"
    assert plan.scheduler_service_account_email == "custom-sched@proj.iam.gserviceaccount.com"


def test_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("not ready yet")

    _with_retry(flaky, description="test", log=lambda _: None, attempts=5, delay_seconds=0)
    assert calls["n"] == 3


def test_with_retry_raises_after_exhausting_attempts():
    def always_fails():
        raise RuntimeError("still not ready")

    with pytest.raises(RuntimeError, match="still not ready"):
        _with_retry(always_fails, description="test", log=lambda _: None, attempts=3, delay_seconds=0)


def test_grant_dataset_writer_adds_access_entry_once():
    client = MagicMock()
    dataset = bigquery.Dataset("proj.ds")
    dataset.access_entries = []
    client.get_dataset.return_value = dataset

    grant_dataset_writer(client, "proj", "ds", "fetch-sa@proj.iam.gserviceaccount.com")

    assert client.update_dataset.called
    updated_dataset = client.update_dataset.call_args[0][0]
    assert any(
        e.role == "WRITER" and e.entity_id == "fetch-sa@proj.iam.gserviceaccount.com"
        for e in updated_dataset.access_entries
    )


def test_grant_dataset_writer_is_idempotent():
    client = MagicMock()
    dataset = bigquery.Dataset("proj.ds")
    dataset.access_entries = [
        bigquery.AccessEntry(role="WRITER", entity_type="userByEmail", entity_id="fetch-sa@proj.iam.gserviceaccount.com")
    ]
    client.get_dataset.return_value = dataset

    grant_dataset_writer(client, "proj", "ds", "fetch-sa@proj.iam.gserviceaccount.com")

    client.update_dataset.assert_not_called()
