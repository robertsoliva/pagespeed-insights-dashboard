"""Single source of truth for every PageSpeed Insights metric this project tracks.

Both the fetch job (extraction + BigQuery schema generation) and the dashboard
(display order, grouping, labels) import METRICS from here. Add a metric once,
it shows up everywhere consistently.

Metrics are grouped into tiers reflecting how important they are to a page-speed
review. The dashboard renders tiers top-to-bottom in this order; earlier tiers
are "principal KPIs", later tiers are progressively more granular detail.

Field paths use classic, stable Lighthouse audit IDs (not the newer "-insight"
suffixed audits, which are a newer, less consistently-available output format).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class Tier(IntEnum):
    CORE_WEB_VITALS = 1
    CATEGORY_SCORES = 2
    FIELD_DATA = 3
    RESOURCES = 4
    OPPORTUNITIES = 5


TIER_LABELS = {
    Tier.CORE_WEB_VITALS: "Core Web Vitals",
    Tier.CATEGORY_SCORES: "Lighthouse Category Scores",
    Tier.FIELD_DATA: "Real-User Field Data (CrUX)",
    Tier.RESOURCES: "Resource Breakdown",
    Tier.OPPORTUNITIES: "Optimization Opportunities",
}


@dataclass(frozen=True)
class Metric:
    name: str            # BigQuery column name
    path: str             # dot path into the PSI v5 JSON response
    bq_type: str          # BigQuery field type: FLOAT, STRING, INTEGER
    tier: Tier
    label: str            # human-readable label for the dashboard
    unit: str             # "score" (0-100), "ms", "bytes", "ratio", "count", "text"
    lower_is_better: bool = True
    scale_to_100: bool = False  # PSI scores are 0-1; multiply by 100 for display


METRICS: list[Metric] = [
    # --- Tier 1: Core Web Vitals -------------------------------------------------
    Metric("performance_score", "lighthouseResult.categories.performance.score",
           "FLOAT", Tier.CORE_WEB_VITALS, "Performance Score", "score", False, True),
    Metric("lcp_ms", "lighthouseResult.audits.largest-contentful-paint.numericValue",
           "FLOAT", Tier.CORE_WEB_VITALS, "Largest Contentful Paint", "ms"),
    Metric("lcp_score", "lighthouseResult.audits.largest-contentful-paint.score",
           "FLOAT", Tier.CORE_WEB_VITALS, "LCP Score", "score", False, True),
    Metric("cls", "lighthouseResult.audits.cumulative-layout-shift.numericValue",
           "FLOAT", Tier.CORE_WEB_VITALS, "Cumulative Layout Shift", "ratio"),
    Metric("cls_score", "lighthouseResult.audits.cumulative-layout-shift.score",
           "FLOAT", Tier.CORE_WEB_VITALS, "CLS Score", "score", False, True),
    Metric("tbt_ms", "lighthouseResult.audits.total-blocking-time.numericValue",
           "FLOAT", Tier.CORE_WEB_VITALS, "Total Blocking Time (INP proxy)", "ms"),
    Metric("tbt_score", "lighthouseResult.audits.total-blocking-time.score",
           "FLOAT", Tier.CORE_WEB_VITALS, "TBT Score", "score", False, True),
    Metric("fcp_ms", "lighthouseResult.audits.first-contentful-paint.numericValue",
           "FLOAT", Tier.CORE_WEB_VITALS, "First Contentful Paint", "ms"),
    Metric("fcp_score", "lighthouseResult.audits.first-contentful-paint.score",
           "FLOAT", Tier.CORE_WEB_VITALS, "FCP Score", "score", False, True),
    Metric("speed_index_ms", "lighthouseResult.audits.speed-index.numericValue",
           "FLOAT", Tier.CORE_WEB_VITALS, "Speed Index", "ms"),
    Metric("speed_index_score", "lighthouseResult.audits.speed-index.score",
           "FLOAT", Tier.CORE_WEB_VITALS, "Speed Index Score", "score", False, True),
    Metric("tti_ms", "lighthouseResult.audits.interactive.numericValue",
           "FLOAT", Tier.CORE_WEB_VITALS, "Time to Interactive", "ms"),

    # --- Tier 2: Other Lighthouse category scores --------------------------------
    Metric("accessibility_score", "lighthouseResult.categories.accessibility.score",
           "FLOAT", Tier.CATEGORY_SCORES, "Accessibility Score", "score", False, True),
    Metric("best_practices_score", "lighthouseResult.categories.best-practices.score",
           "FLOAT", Tier.CATEGORY_SCORES, "Best Practices Score", "score", False, True),
    Metric("seo_score", "lighthouseResult.categories.seo.score",
           "FLOAT", Tier.CATEGORY_SCORES, "SEO Score", "score", False, True),

    # --- Tier 3: CrUX real-user field data (may be null for low-traffic URLs) ----
    Metric("crux_lcp_ms_p75", "loadingExperience.metrics.LARGEST_CONTENTFUL_PAINT_MS.percentile",
           "FLOAT", Tier.FIELD_DATA, "Field LCP (p75)", "ms"),
    Metric("crux_lcp_good_ratio", "loadingExperience.metrics.LARGEST_CONTENTFUL_PAINT_MS.distributions[0].proportion",
           "FLOAT", Tier.FIELD_DATA, "Field LCP Good Ratio", "ratio", False),
    Metric("crux_cls_p75", "loadingExperience.metrics.CUMULATIVE_LAYOUT_SHIFT_SCORE.percentile",
           "FLOAT", Tier.FIELD_DATA, "Field CLS (p75)", "ratio"),
    Metric("crux_cls_good_ratio", "loadingExperience.metrics.CUMULATIVE_LAYOUT_SHIFT_SCORE.distributions[0].proportion",
           "FLOAT", Tier.FIELD_DATA, "Field CLS Good Ratio", "ratio", False),
    Metric("crux_fcp_ms_p75", "loadingExperience.metrics.FIRST_CONTENTFUL_PAINT_MS.percentile",
           "FLOAT", Tier.FIELD_DATA, "Field FCP (p75)", "ms"),
    Metric("crux_fcp_good_ratio", "loadingExperience.metrics.FIRST_CONTENTFUL_PAINT_MS.distributions[0].proportion",
           "FLOAT", Tier.FIELD_DATA, "Field FCP Good Ratio", "ratio", False),
    Metric("crux_inp_ms_p75", "loadingExperience.metrics.INTERACTION_TO_NEXT_PAINT.percentile",
           "FLOAT", Tier.FIELD_DATA, "Field INP (p75)", "ms"),
    Metric("crux_inp_good_ratio", "loadingExperience.metrics.INTERACTION_TO_NEXT_PAINT.distributions[0].proportion",
           "FLOAT", Tier.FIELD_DATA, "Field INP Good Ratio", "ratio", False),
    Metric("crux_ttfb_ms_p75", "loadingExperience.metrics.EXPERIMENTAL_TIME_TO_FIRST_BYTE.percentile",
           "FLOAT", Tier.FIELD_DATA, "Field Time to First Byte (p75)", "ms"),
    Metric("crux_overall_category", "loadingExperience.overall_category",
           "STRING", Tier.FIELD_DATA, "Field Overall Category", "text"),

    # --- Tier 4: Resource / DOM breakdown -----------------------------------------
    Metric("total_requests", "lighthouseResult.audits.resource-summary.details.items[0].requestCount",
           "FLOAT", Tier.RESOURCES, "Total Requests", "count"),
    Metric("total_bytes", "lighthouseResult.audits.resource-summary.details.items[0].transferSize",
           "FLOAT", Tier.RESOURCES, "Total Transfer Size", "bytes"),
    Metric("image_bytes", "lighthouseResult.audits.resource-summary.details.items[1].transferSize",
           "FLOAT", Tier.RESOURCES, "Image Bytes", "bytes"),
    Metric("script_bytes", "lighthouseResult.audits.resource-summary.details.items[2].transferSize",
           "FLOAT", Tier.RESOURCES, "Script Bytes", "bytes"),
    Metric("font_bytes", "lighthouseResult.audits.resource-summary.details.items[3].transferSize",
           "FLOAT", Tier.RESOURCES, "Font Bytes", "bytes"),
    Metric("document_bytes", "lighthouseResult.audits.resource-summary.details.items[4].transferSize",
           "FLOAT", Tier.RESOURCES, "Document Bytes", "bytes"),
    Metric("stylesheet_bytes", "lighthouseResult.audits.resource-summary.details.items[5].transferSize",
           "FLOAT", Tier.RESOURCES, "Stylesheet Bytes", "bytes"),
    Metric("media_bytes", "lighthouseResult.audits.resource-summary.details.items[6].transferSize",
           "FLOAT", Tier.RESOURCES, "Media Bytes", "bytes"),
    Metric("third_party_bytes", "lighthouseResult.audits.resource-summary.details.items[7].transferSize",
           "FLOAT", Tier.RESOURCES, "Third-Party Bytes", "bytes"),
    Metric("dom_elements", "lighthouseResult.audits.dom-size.details.items[0].value",
           "FLOAT", Tier.RESOURCES, "Total DOM Elements", "count"),
    Metric("dom_max_depth", "lighthouseResult.audits.dom-size.details.items[1].value",
           "FLOAT", Tier.RESOURCES, "Max DOM Depth", "count"),

    # --- Tier 5: Optimization opportunities (granular, least important) ----------
    Metric("render_blocking_savings_ms", "lighthouseResult.audits.render-blocking-resources.details.overallSavingsMs",
           "FLOAT", Tier.OPPORTUNITIES, "Render-Blocking Resources Savings", "ms"),
    Metric("unused_js_savings_bytes", "lighthouseResult.audits.unused-javascript.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Unused JavaScript Savings", "bytes"),
    Metric("unused_css_savings_bytes", "lighthouseResult.audits.unused-css-rules.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Unused CSS Savings", "bytes"),
    Metric("modern_image_formats_savings_bytes", "lighthouseResult.audits.modern-image-formats.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Modern Image Format Savings", "bytes"),
    Metric("offscreen_images_savings_bytes", "lighthouseResult.audits.offscreen-images.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Offscreen Image Savings", "bytes"),
    Metric("unminified_js_savings_bytes", "lighthouseResult.audits.unminified-javascript.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Unminified JS Savings", "bytes"),
    Metric("unminified_css_savings_bytes", "lighthouseResult.audits.unminified-css.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Unminified CSS Savings", "bytes"),
    Metric("text_compression_savings_bytes", "lighthouseResult.audits.uses-text-compression.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Text Compression Savings", "bytes"),
    Metric("server_response_time_ms", "lighthouseResult.audits.server-response-time.numericValue",
           "FLOAT", Tier.OPPORTUNITIES, "Server Response Time", "ms"),
    Metric("main_thread_work_ms", "lighthouseResult.audits.mainthread-work-breakdown.numericValue",
           "FLOAT", Tier.OPPORTUNITIES, "Main Thread Work", "ms"),
    Metric("bootup_time_ms", "lighthouseResult.audits.bootup-time.numericValue",
           "FLOAT", Tier.OPPORTUNITIES, "JS Bootup Time", "ms"),
    Metric("legacy_js_savings_bytes", "lighthouseResult.audits.legacy-javascript.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Legacy JavaScript Savings", "bytes"),
    Metric("duplicate_js_savings_bytes", "lighthouseResult.audits.duplicated-javascript.details.overallSavingsBytes",
           "FLOAT", Tier.OPPORTUNITIES, "Duplicate JavaScript Savings", "bytes"),
    Metric("third_party_blocking_ms", "lighthouseResult.audits.third-party-summary.details.summary.wastedMs",
           "FLOAT", Tier.OPPORTUNITIES, "Third-Party Blocking Time", "ms"),
]

# Identity/context columns that precede the metrics in the BigQuery table.
IDENTITY_FIELDS: list[tuple[str, str]] = [
    ("run_id", "STRING"),
    ("job_id", "STRING"),
    ("fetched_at", "TIMESTAMP"),
    ("url", "STRING"),
    ("device", "STRING"),
]

_ARRAY_INDEX_RE = re.compile(r"(\w+)\[(\d+)\]")


def _split_path(path: str) -> list[Any]:
    keys: list[Any] = []
    for raw_key in path.split("."):
        match = _ARRAY_INDEX_RE.match(raw_key)
        if match:
            keys.append(match.group(1))
            keys.append(int(match.group(2)))
        else:
            keys.append(raw_key)
    return keys


def safe_get(data: dict, path: str, as_string: bool = False) -> Any:
    """Walk a dot/bracket path into a nested dict-of-lists PSI response.

    Returns None if any segment is missing, rather than raising - PSI
    responses omit whole sections (e.g. CrUX field data) for low-traffic URLs.
    """
    current: Any = data
    for key in _split_path(path):
        if current is None:
            return None
        try:
            if isinstance(key, int):
                current = current[key] if isinstance(current, list) and len(current) > key else None
            else:
                current = current.get(key) if isinstance(current, dict) else None
        except (TypeError, KeyError, IndexError):
            return None

    if current is None:
        return None
    if as_string:
        return str(current)
    if isinstance(current, bool):
        return None
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


def metrics_by_tier() -> dict[Tier, list[Metric]]:
    grouped: dict[Tier, list[Metric]] = {tier: [] for tier in Tier}
    for metric in METRICS:
        grouped[metric.tier].append(metric)
    return grouped
