"""PageSpeed Insights v5 API client with retry/backoff and bounded concurrency."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CATEGORIES = ["performance", "accessibility", "best-practices", "seo"]
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2
REQUEST_TIMEOUT = 90
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def fetch_psi(url: str, strategy: str, api_key: str, session: requests.Session | None = None) -> dict | None:
    session = session or requests.Session()
    params = [("url", url), ("key", api_key), ("strategy", strategy)] + [("category", c) for c in CATEGORIES]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(PSI_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("PSI request error for %s (%s) attempt %d/%d: %s", url, strategy, attempt, MAX_RETRIES, exc)
        else:
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code not in RETRYABLE_STATUS:
                logger.error("PSI HTTP %d for %s (%s): %s", resp.status_code, url, strategy, resp.text[:300])
                return None
            logger.warning("PSI HTTP %d for %s (%s) attempt %d/%d", resp.status_code, url, strategy, attempt, MAX_RETRIES)

        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE_SECONDS**attempt)

    logger.error("PSI failed for %s (%s) after %d attempts", url, strategy, MAX_RETRIES)
    return None


def fetch_all(urls: list[str], api_key: str, max_workers: int = 5) -> list[tuple[str, str, dict | None]]:
    """Fetches mobile + desktop PSI results for every URL, bounded by max_workers."""
    tasks = [(url, device) for url in urls for device in ("mobile", "desktop")]
    session = requests.Session()
    results: list[tuple[str, str, dict | None]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(fetch_psi, url, device, api_key, session): (url, device) for url, device in tasks
        }
        for future in as_completed(future_map):
            url, device = future_map[future]
            try:
                data = future.result()
            except Exception:
                logger.exception("Unhandled error fetching %s (%s)", url, device)
                data = None
            results.append((url, device, data))

    return results
