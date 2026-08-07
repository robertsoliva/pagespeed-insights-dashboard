from unittest.mock import MagicMock, patch

import pytest

from setup.core import create_psi_api_key, interval_to_cron, parse_csv_urls, slugify


def test_parse_csv_urls_with_header():
    csv_text = "url,notes\nhttps://example.com,home\nexample.org/about,about\n"
    assert parse_csv_urls(csv_text) == ["https://example.com", "https://example.org/about"]


def test_parse_csv_urls_without_header():
    csv_text = "https://a.com\nhttps://b.com\n"
    assert parse_csv_urls(csv_text) == ["https://a.com", "https://b.com"]


def test_parse_csv_urls_dedupes():
    csv_text = "url\nhttps://a.com\nhttps://a.com\n"
    assert parse_csv_urls(csv_text) == ["https://a.com"]


def test_interval_to_cron():
    assert interval_to_cron(6) == "0 */6 * * *"
    assert interval_to_cron(24) == "0 0 * * *"
    with pytest.raises(ValueError):
        interval_to_cron(0)
    with pytest.raises(ValueError):
        interval_to_cron(25)


def test_slugify():
    assert slugify("Example.com") == "example-com"
    assert slugify("") == "site"


def test_create_psi_api_key_enables_apis_and_returns_key_string():
    with patch("setup.core.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # services enable
            MagicMock(returncode=0, stdout="AIzaSyFAKEKEYSTRINGvalue\n", stderr=""),  # api-keys create
        ]

        key = create_psi_api_key("my-project", log=lambda _: None)

        assert key == "AIzaSyFAKEKEYSTRINGvalue"
        enable_call, create_call = mock_run.call_args_list
        assert "pagespeedonline.googleapis.com" in enable_call.args[0]
        assert "apikeys.googleapis.com" in enable_call.args[0]
        create_args = create_call.args[0]
        assert "--api-target=service=pagespeedonline.googleapis.com" in create_args
        assert "--project=my-project" in create_args
