import responses

from fetch_job.url_discovery import discover_from_sitemap

SITEMAP_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/</loc></url>
  <url><loc>https://example.com/about</loc></url>
  <url><loc>https://other-domain.com/ignored</loc></url>
</urlset>
"""


@responses.activate
def test_discover_from_sitemap_filters_same_domain():
    responses.add(responses.GET, "https://example.com/sitemap.xml", body=SITEMAP_XML, status=200)

    urls = discover_from_sitemap("example.com", max_pages=200)

    assert urls == ["https://example.com/", "https://example.com/about"]


@responses.activate
def test_discover_from_sitemap_respects_max_pages():
    responses.add(responses.GET, "https://example.com/sitemap.xml", body=SITEMAP_XML, status=200)

    urls = discover_from_sitemap("example.com", max_pages=1)

    assert urls == ["https://example.com/"]


@responses.activate
def test_discover_from_sitemap_returns_empty_when_missing():
    responses.add(responses.GET, "https://example.com/sitemap.xml", status=404)
    responses.add(responses.GET, "https://example.com/sitemap_index.xml", status=404)

    urls = discover_from_sitemap("example.com", max_pages=200)

    assert urls == []
