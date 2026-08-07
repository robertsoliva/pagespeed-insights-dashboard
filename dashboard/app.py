"""PageSpeed Insights dashboard.

Desktop and mobile are separate views (device filter in the sidebar). KPIs
render top-to-bottom in importance order -- Core Web Vitals first, then other
Lighthouse category scores, then real-user field data, resource breakdown,
and finally the long tail of optimization opportunities -- driven by the
single metric-tier definition in common/metrics_spec.py.

Run with: streamlit run dashboard/app.py
"""

from __future__ import annotations

from urllib.parse import urlparse

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.bigquery_schema import CONFIG_TABLE_NAME
from common.metrics_spec import TIER_LABELS, Tier, metrics_by_tier
from dashboard.kpi_config import STATUS_COLORS, classify, format_value
from dashboard.queries import get_trend_data, list_urls
from setup.core import list_bq_datasets, list_bq_tables, list_gcp_projects

st.set_page_config(page_title="PageSpeed Insights Dashboard", page_icon="📈", layout="wide")

CHART_LINE_COLOR = "#2a78d6"  # categorical slot 1 -- single series per chart, no legend needed
ALL_URLS_LABEL = "All URLs (average)"
ALL_SECTIONS_LABEL = "All Website"
HOME_SECTION = "Home"
OTHER_SECTION = "Other pages"

st.title("PageSpeed Insights Dashboard")

def _pick(label: str, options: list[str], current: str, fallback_default: str = "") -> str:
    """Selectbox when GCP gave us real options, text input otherwise -- and
    keep whatever was already connected (e.g. handed off from Setup) selected."""
    if options:
        index = options.index(current) if current in options else 0
        return st.selectbox(label, options, index=index)
    return st.text_input(label, value=current or fallback_default)


def _normalize(url: str) -> str:
    return url.strip().rstrip("/")


def _group_by_section(urls: list[str]) -> dict[str, list[str]]:
    """Group tracked URLs by first path segment, e.g. root/A/* -> section "A".
    A first segment only counts as a section if something is nested under it
    (root/A/ alone doesn't); otherwise the page is a one-off in "Other pages".
    The root page itself is always "Home"."""
    path_segments = {url: [s for s in urlparse(url).path.strip("/").split("/") if s] for url in urls}
    section_names = {segments[0] for segments in path_segments.values() if len(segments) >= 2}

    sections: dict[str, list[str]] = {}
    for url, segments in path_segments.items():
        if not segments:
            section = HOME_SECTION
        elif segments[0] in section_names:
            section = segments[0]
        else:
            section = OTHER_SECTION
        sections.setdefault(section, []).append(url)
    return sections


with st.sidebar:
    st.header("Connection")

    if st.button("Load my GCP projects"):
        with st.spinner("Listing projects via gcloud..."):
            try:
                st.session_state["projects"] = list_gcp_projects()
            except Exception as exc:
                st.error(f"Couldn't list projects (is `gcloud auth login` done?): {exc}")

    project_ids = [p["projectId"] for p in st.session_state.get("projects", [])]
    project = _pick("GCP project", project_ids, st.session_state.get("project", ""))

    try:
        datasets = list_bq_datasets(project) if project else []
    except Exception:
        datasets = []
    dataset = _pick("Dataset", datasets, st.session_state.get("dataset", ""), fallback_default="psi_monitor")

    try:
        tables = [t for t in list_bq_tables(project, dataset) if t != CONFIG_TABLE_NAME] if project and dataset else []
    except Exception:
        tables = []
    table = _pick("Table", tables, st.session_state.get("table", ""), fallback_default="psi_metrics")

    if st.button("Connect") or st.session_state.get("connected"):
        st.session_state.update(connected=True, project=project, dataset=dataset, table=table)

if not st.session_state.get("connected"):
    st.info("Enter your BigQuery project / dataset / table in the sidebar and click Connect.")
    st.stop()

try:
    urls = list_urls(project, dataset, table)
except Exception as exc:
    st.error(f"Couldn't read from `{project}.{dataset}.{table}`: {exc}")
    st.stop()

if not urls:
    st.warning(
        "No data yet. The Cloud Run Job only runs on Cloud Scheduler's cadence "
        "(whatever interval you picked in Setup), so if you just deployed, the "
        "first row can take up to that long to show up. To check sooner, trigger "
        "it manually:\n\n"
        "```\ngcloud run jobs execute <cloud-run-job-name> --region <region>\n```"
    )
    st.stop()

sections = _group_by_section(urls)
section_names = sorted(s for s in sections if s not in (HOME_SECTION, OTHER_SECTION))
section_options = [ALL_SECTIONS_LABEL]
section_options += [s for s in (HOME_SECTION,) if s in sections]
section_options += section_names
section_options += [s for s in (OTHER_SECTION,) if s in sections]

with st.sidebar:
    st.header("Filters")
    device = st.radio("Device", ["mobile", "desktop"], format_func=str.title, horizontal=True)
    section_choice = st.selectbox("Website section", section_options)
    section_urls = urls if section_choice == ALL_SECTIONS_LABEL else sections[section_choice]
    url_choice = st.selectbox("URL", [ALL_URLS_LABEL, *section_urls])
    custom_url = st.text_input(
        "Or jump to a specific URL",
        placeholder="https://example.com/some/page",
        help="Overrides the section/URL filters above. Must match a tracked URL.",
    )
    lookback_days = st.slider("Lookback window (days)", 1, 90, 14)

selected_url: str | None = None
selected_urls: list[str] | None = None
filter_label = ALL_SECTIONS_LABEL

custom_url = custom_url.strip()
if custom_url:
    url_lookup = {_normalize(u): u for u in urls}
    match = url_lookup.get(_normalize(custom_url))
    if match:
        selected_url = match
        filter_label = match
    else:
        st.sidebar.error(f"'{custom_url}' isn't a tracked URL -- falling back to the filters above.")

if selected_url is None:
    if url_choice != ALL_URLS_LABEL:
        selected_url = url_choice
        filter_label = url_choice
    elif section_choice != ALL_SECTIONS_LABEL:
        selected_urls = section_urls
        filter_label = f"{section_choice} ({len(section_urls)} pages, average)"
    else:
        filter_label = ALL_URLS_LABEL

df = get_trend_data(project, dataset, table, device, lookback_days, url=selected_url, urls=selected_urls)

if df.empty:
    st.warning("No data in this window yet. Try a longer lookback window.")
    st.stop()

if selected_url is None:
    numeric_cols = [c for c in df.columns if df[c].dtype.kind in "fc"]
    df = (
        df.groupby("run_id", as_index=False)
        .agg({"fetched_at": "min", **{c: "mean" for c in numeric_cols}})
        .sort_values("fetched_at")
    )
else:
    df = df.sort_values("fetched_at")

st.caption(f"{len(df)} runs · {device.title()} · {filter_label} · last {lookback_days} days")

if len(df) < 3:
    st.info(
        f"Only {len(df)} run{'s' if len(df) != 1 else ''} so far, so trend lines below "
        "are mostly flat or a single point. They'll fill in as Cloud Scheduler keeps "
        "firing on its interval -- or trigger a few more runs manually "
        "(`gcloud run jobs execute ...`) to see movement sooner."
    )

tiers = metrics_by_tier()


def render_tier(tier: Tier, expanded: bool) -> None:
    metrics = [m for m in tiers[tier] if m.name in df.columns]
    if not metrics:
        return

    if expanded:
        st.subheader(TIER_LABELS[tier])
        body = st.container()
    else:
        body = st.expander(TIER_LABELS[tier], expanded=False)

    with body:
        latest = df.iloc[-1]
        previous = df.iloc[-2] if len(df) > 1 else None

        cols = st.columns(min(len(metrics), 4))
        for i, metric in enumerate(metrics):
            value = latest.get(metric.name)
            status = classify(metric.name, value, metric.lower_is_better)
            delta = None
            if previous is not None and pd.notna(previous.get(metric.name)) and pd.notna(value):
                delta = value - previous[metric.name]
            with cols[i % len(cols)]:
                st.metric(
                    metric.label,
                    format_value(value, metric.unit),
                    delta=f"{delta:+,.1f}" if delta is not None else None,
                    delta_color="inverse" if metric.lower_is_better else "normal",
                )
                if status:
                    st.markdown(
                        f"<span style='color:{STATUS_COLORS[status]}; font-size:0.8em;'>● {status}</span>",
                        unsafe_allow_html=True,
                    )

        for metric in metrics:
            series = df[metric.name].dropna()
            if series.empty:
                continue
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=df["fetched_at"],
                    y=df[metric.name],
                    mode="lines+markers",
                    line=dict(color=CHART_LINE_COLOR, width=2),
                    marker=dict(size=6),
                    name=metric.label,
                    hovertemplate=f"%{{x}}<br>{metric.label}: %{{y}}<extra></extra>",
                )
            )
            fig.update_layout(
                title=metric.label,
                height=260,
                margin=dict(l=10, r=10, t=40, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=False,
                xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor="rgba(128,128,128,0.15)"),
            )
            st.plotly_chart(fig, width="stretch")


render_tier(Tier.CORE_WEB_VITALS, expanded=True)
render_tier(Tier.CATEGORY_SCORES, expanded=True)
render_tier(Tier.FIELD_DATA, expanded=False)
render_tier(Tier.RESOURCES, expanded=False)
render_tier(Tier.OPPORTUNITIES, expanded=False)
