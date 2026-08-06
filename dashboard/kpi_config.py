"""Display formatting and good/needs-improvement/poor thresholds for the dashboard.

Colors are the fixed status palette (never themed, never reused for series
identity): good/warning/critical. Thresholds below are Google's published
Core Web Vitals and Lighthouse score bands.
"""

from __future__ import annotations

STATUS_COLORS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "critical": "#d03b3b",
}

# metric_name -> (good_threshold, poor_threshold)
THRESHOLDS: dict[str, tuple[float, float]] = {
    "performance_score": (90, 50),
    "accessibility_score": (90, 50),
    "best_practices_score": (90, 50),
    "seo_score": (90, 50),
    "lcp_ms": (2500, 4000),
    "cls": (0.1, 0.25),
    "tbt_ms": (200, 600),
    "fcp_ms": (1800, 3000),
    "speed_index_ms": (3400, 5800),
    "tti_ms": (3800, 7300),
    "crux_lcp_ms_p75": (2500, 4000),
    "crux_cls_p75": (0.1, 0.25),
    "crux_fcp_ms_p75": (1800, 3000),
    "crux_inp_ms_p75": (200, 500),
    "crux_ttfb_ms_p75": (800, 1800),
}


def classify(metric_name: str, value: float | None, lower_is_better: bool) -> str | None:
    if value is None or metric_name not in THRESHOLDS:
        return None
    good, poor = THRESHOLDS[metric_name]
    if lower_is_better:
        if value <= good:
            return "good"
        if value > poor:
            return "critical"
        return "warning"
    if value >= good:
        return "good"
    if value < poor:
        return "critical"
    return "warning"


def format_value(value: float | str | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "ms":
        return f"{value:,.0f} ms"
    if unit == "score":
        return f"{value:.0f}"
    if unit == "bytes":
        if value >= 1_000_000:
            return f"{value / 1_000_000:.2f} MB"
        return f"{value / 1000:.1f} KB"
    if unit == "ratio":
        return f"{value:.3f}"
    if unit == "count":
        return f"{value:,.0f}"
    return str(value)
