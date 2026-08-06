"""PageSpeed Insights dashboard.

Desktop and mobile are separate views (device filter in the sidebar). KPIs
render top-to-bottom in importance order -- Core Web Vitals first, then other
Lighthouse category scores, then real-user field data, resource breakdown,
and finally the long tail of optimization opportunities -- driven by the
single metric-tier definition in common/metrics_spec.py.

Run with: streamlit run dashboard/app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from common.metrics_spec import TIER_LABELS, Tier, metrics_by_tier
from dashboard.kpi_config import STATUS_COLORS, classify, format_value
from dashboard.queries import get_trend_data, list_urls

st.set_page_config(page_title="PageSpeed Insights Dashboard", page_icon="📈", layout="wide")

CHART_LINE_COLOR = "#2a78d6"  # categorical slot 1 -- single series per chart, no legend needed
ALL_URLS_LABEL = "All URLs (average)"

st.title("PageSpeed Insights Dashboard")

with st.sidebar:
    st.header("Connection")
    project = st.text_input("GCP project", value=st.session_state.get("project", ""))
    dataset = st.text_input("Dataset", value=st.session_state.get("dataset", "psi_monitor"))
    table = st.text_input("Table", value=st.session_state.get("table", "psi_metrics"))
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
    st.warning("No data yet — the Cloud Run Job hasn't run, or hasn't succeeded yet.")
    st.stop()

with st.sidebar:
    st.header("Filters")
    device = st.radio("Device", ["mobile", "desktop"], format_func=str.title, horizontal=True)
    url_choice = st.selectbox("URL", [ALL_URLS_LABEL, *urls])
    lookback_days = st.slider("Lookback window (days)", 1, 90, 14)

selected_url = None if url_choice == ALL_URLS_LABEL else url_choice
df = get_trend_data(project, dataset, table, device, lookback_days, selected_url)

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

st.caption(f"{len(df)} runs · {device.title()} · {url_choice} · last {lookback_days} days")

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
