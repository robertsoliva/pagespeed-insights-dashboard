import pytest

from setup.core import interval_to_cron, parse_csv_urls, slugify


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
