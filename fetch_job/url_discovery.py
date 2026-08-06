"""Discover URLs for a domain when the user didn't upload an explicit CSV.

Strategy: try the site's sitemap(s) first (fast, respects the site's own
declared structure, one or two HTTP requests). Only fall back to a same-domain
crawl -- respecting robots.txt -- if no sitemap is found. Both paths are capped
at max_pages, since every discovered URL costs a PageSpeed API call (~10-30s
each) on top of BigQuery/API quota.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "pagespeed-insights-dashboard/0.1 (+https://github.com/)"
REQUEST_TIMEOUT = 15
MAX_SITEMAP_CHILDREN = 50

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.hrefs.append(value)


def _normalize_root(domain: str) -> str:
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    parsed = urlparse(domain)
    return f"{parsed.scheme}://{parsed.netloc}"


def _same_domain(url: str, netloc: str) -> bool:
    return urlparse(url).netloc == netloc


def _fetch_sitemap_locs(url: str, session: requests.Session, depth: int = 0) -> list[str]:
    if depth > 2:
        return []
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200 or not resp.content:
            return []
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as exc:
        logger.info("Sitemap fetch/parse failed for %s: %s", url, exc)
        return []

    tag = root.tag
    if tag == f"{_SITEMAP_NS}sitemapindex":
        child_locs = [
            loc.text.strip()
            for sitemap in root.findall(f"{_SITEMAP_NS}sitemap")[:MAX_SITEMAP_CHILDREN]
            if (loc := sitemap.find(f"{_SITEMAP_NS}loc")) is not None and loc.text
        ]
        urls: list[str] = []
        for child_url in child_locs:
            urls.extend(_fetch_sitemap_locs(child_url, session, depth + 1))
        return urls

    if tag == f"{_SITEMAP_NS}urlset":
        return [
            loc.text.strip()
            for url_el in root.findall(f"{_SITEMAP_NS}url")
            if (loc := url_el.find(f"{_SITEMAP_NS}loc")) is not None and loc.text
        ]

    return []


def discover_from_sitemap(domain: str, max_pages: int, session: requests.Session | None = None) -> list[str]:
    root = _normalize_root(domain)
    netloc = urlparse(root).netloc
    session = session or requests.Session()

    candidates = [f"{root}/sitemap.xml", f"{root}/sitemap_index.xml"]
    for candidate in candidates:
        urls = _fetch_sitemap_locs(candidate, session)
        if urls:
            same_domain_urls = [u for u in dict.fromkeys(urls) if _same_domain(u, netloc)]
            return same_domain_urls[:max_pages]
    return []


def crawl_site(domain: str, max_pages: int, session: requests.Session | None = None) -> list[str]:
    root = _normalize_root(domain)
    netloc = urlparse(root).netloc
    session = session or requests.Session()

    robots = RobotFileParser()
    robots.set_url(f"{root}/robots.txt")
    try:
        robots.read()
    except Exception as exc:  # robots.txt missing/unreachable -> allow all
        logger.info("robots.txt unavailable for %s: %s", root, exc)
        robots = None

    def allowed(url: str) -> bool:
        if robots is None:
            return True
        try:
            return robots.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    seen: set[str] = set()
    queue: list[str] = [root]
    discovered: list[str] = []

    while queue and len(discovered) < max_pages:
        url = queue.pop(0)
        if url in seen or not allowed(url):
            continue
        seen.add(url)

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                continue
        except requests.RequestException as exc:
            logger.info("Crawl fetch failed for %s: %s", url, exc)
            continue

        discovered.append(url)

        parser = _LinkExtractor()
        parser.feed(resp.text)
        for href in parser.hrefs:
            absolute = urljoin(url, href).split("#")[0]
            if _same_domain(absolute, netloc) and absolute not in seen and absolute not in queue:
                queue.append(absolute)

    return discovered[:max_pages]


def discover_urls(domain: str, max_pages: int = 200) -> list[str]:
    """Sitemap first; crawl fallback. Always capped at max_pages."""
    session = requests.Session()

    sitemap_urls = discover_from_sitemap(domain, max_pages, session)
    if sitemap_urls:
        logger.info("Discovered %d URLs from sitemap for %s", len(sitemap_urls), domain)
        return sitemap_urls

    logger.info("No sitemap found for %s, falling back to crawl", domain)
    return crawl_site(domain, max_pages, session)
