"""Streamlit dashboard for the 30-day demand forecasts and sales analytics.

All data comes from the FastAPI service (API_URL); the dashboard holds no model code.
Run locally with:  API_URL=http://localhost:8000 streamlit run dashboard/app.py
"""

from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
MLFLOW_UI_URL = os.environ.get("MLFLOW_UI_URL", "http://localhost:5000").rstrip("/")

# Validated categorical palette (fixed order; colour follows the entity, never its rank).
SURFACE, TEXT, TEXT_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
ACTUAL, FORECAST = "#2a78d6", "#eb6834"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]

st.set_page_config(page_title="Demand Forecasts", page_icon="📈", layout="wide")


# --------------------------------------------------------------------------- data
class ApiError(RuntimeError):
    pass


@st.cache_data(ttl=60, show_spinner=False)
def api(path: str, **params) -> dict | list:
    try:
        r = requests.get(f"{API_URL}{path}", params={k: v for k, v in params.items() if v is not None}, timeout=15)
    except requests.RequestException as exc:
        raise ApiError(f"Can't reach the forecast API at {API_URL} ({exc.__class__.__name__}).") from exc
    if r.status_code == 503:
        raise ApiError("The API is up but has no forecast yet. Run the trainer job (`make retrain`).")
    if not r.ok:
        raise ApiError(f"{path} returned HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def frame(path: str, date_cols: tuple[str, ...] = ("date",), **params) -> pd.DataFrame:
    df = pd.DataFrame(api(path, **params))
    for c in date_cols:
        if c in df:
            df[c] = pd.to_datetime(df[c])
    return df


def category_colors(categories: list[str]) -> dict[str, str]:
    """Stable colour per category: slot order is alphabetical over *all* categories."""
    return {c: SERIES[i % len(SERIES)] for i, c in enumerate(sorted(categories))}


# --------------------------------------------------------------------------- charts
def style(fig: go.Figure, height: int = 380, hovermode: str = "x unified") -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=36, b=8),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, hovermode=hovermode,
        font=dict(color=TEXT_2, size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None, font=dict(color=TEXT_2)),
        hoverlabel=dict(bgcolor="white", font_color=TEXT),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=TEXT_2))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=GRID, tickfont=dict(color=TEXT_2), rangemode="tozero")
    return fig


def forecast_chart(hist: pd.DataFrame, fc: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=pd.concat([fc["date"], fc["date"][::-1]]), y=pd.concat([fc["upper"], fc["lower"][::-1]]),
        fill="toself", fillcolor="rgba(235,104,52,0.16)", line=dict(width=0),
        name="80% interval", hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(x=fc["date"], y=fc["upper"], mode="lines", line=dict(width=0),
                             showlegend=False, name="Upper", hovertemplate="%{y:.1f}"))
    fig.add_trace(go.Scatter(x=fc["date"], y=fc["lower"], mode="lines", line=dict(width=0),
                             showlegend=False, name="Lower", hovertemplate="%{y:.1f}"))
    fig.add_trace(go.Scatter(x=hist["date"], y=hist["units_sold"], mode="lines", name="Actual",
                             line=dict(color=ACTUAL, width=2), hovertemplate="%{y:.0f}"))
    promo = hist[hist["on_promo"] == 1]
    if len(promo):
        fig.add_trace(go.Scatter(x=promo["date"], y=promo["units_sold"], mode="markers", name="Promo day",
                                 marker=dict(color=ACTUAL, size=8, symbol="diamond", line=dict(color=SURFACE, width=2)),
                                 hovertemplate="%{y:.0f} (promo)"))
    fig.add_trace(go.Scatter(x=fc["date"], y=fc["forecast"], mode="lines", name="Forecast",
                             line=dict(color=FORECAST, width=2), hovertemplate="%{y:.1f}"))
    fig.add_vline(x=fc["date"].min(), line=dict(color=GRID, width=1, dash="dot"))
    fig.update_yaxes(title="Units per day")
    return style(fig, height=420)


def bar_chart(df: pd.DataFrame, x: str, y: str, color: str | list[str], fmt: str,
              tickformat: str | None = None) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=df[x], y=df[y], orientation="h", marker=dict(color=color, cornerradius=4),
        hovertemplate=f"%{{y}}: %{{x:{fmt}}}<extra></extra>", texttemplate=f"%{{x:{fmt}}}",
        textposition="outside", textfont=dict(color=TEXT_2), cliponaxis=False,
    ))
    fig.update_layout(bargap=0.35)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    # Pad the value axis so outside labels never clip.
    lo, hi = min(0.0, float(df[x].min())), max(0.0, float(df[x].max()))
    pad = (hi - lo) * 0.18 or 1
    fig.update_xaxes(showgrid=True, gridcolor=GRID, range=[lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0)],
                     tickformat=tickformat or fmt.lstrip("+"))
    return style(fig, height=max(240, 46 * len(df) + 80), hovermode="closest")


def show(fig: go.Figure, title: str) -> None:
    """Chart with its title as a Streamlit heading, so it never collides with the legend."""
    st.markdown(f"##### {title}")
    st.plotly_chart(fig, use_container_width=True)


def pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{x:+.{digits}%}"


# --------------------------------------------------------------------------- page
try:
    model = api("/model")
    summary = api("/analytics/summary")
    products = frame("/products", date_cols=())
    fc_summary = frame("/forecast", date_cols=("start", "end"))
except ApiError as err:
    st.title("Demand Forecasts")
    st.error(str(err))
    st.stop()

colors = category_colors(products["category"].unique().tolist())
catalog = products.merge(fc_summary.drop(columns="category"), on="product_id", how="left")
m = model["metrics"]

st.title("Demand Forecasts")
st.caption(
    f"{model['horizon']}-day forecast for {model['forecast_start']} to {model['forecast_end']} · "
    f"trained on sales up to {model['data_end']} · model `{model['registered_model']}` v{model['model_version']}"
    + (" (champion)" if model.get("promoted_to_champion") else "")
)

# Sidebar filters ---------------------------------------------------------------
with st.sidebar:
    st.header("Filters")
    all_cats = sorted(products["category"].unique())
    cats = st.multiselect("Category", all_cats, default=all_cats)
    classes = st.multiselect("ABC class", ["A", "B", "C"], default=["A", "B", "C"],
                             help="A = products making the first 80% of revenue, B = next 15%, C = the rest.")
    history_days = st.slider("History shown (days)", 30, 365, 120, step=15)
    st.divider()
    st.caption(f"API: {API_URL}")
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

view = catalog[catalog["category"].isin(cats) & catalog["abc_class"].isin(classes)]
if view.empty:
    st.warning("No products match the filters.")
    st.stop()

# KPI row -------------------------------------------------------------------------
recent_total = view["recent_actual"].sum() if "recent_actual" in view else float("nan")
fc_total = view["total_forecast"].sum()
k1, k2, k3, k4 = st.columns(4)
k1.metric(f"Forecast units, next {model['horizon']} days", f"{fc_total:,.0f}",
          pct(fc_total / recent_total - 1 if recent_total else None) + " vs last period",
          delta_color="off", help="Sum over the products in the current filter.")
k2.metric(f"Actual units, last {model['horizon']} days", f"{recent_total:,.0f}")
k3.metric("Revenue, last 30 days (all products)", f"${summary['last_30d_revenue']:,.0f}",
          pct(summary.get("revenue_growth_vs_prior_30d")) + " vs prior 30 days")
k4.metric("Backtest error (WAPE)", f"{m['backtest_wape']:.1%}",
          f"{m['backtest_wape'] - m['naive_wape']:+.1%} vs naive baseline", delta_color="inverse",
          help="Weighted absolute % error over the rolling backtest. Lower is better.")

tab_product, tab_all, tab_sales, tab_model = st.tabs(["Product forecast", "All products", "Sales analytics", "Model"])

# Product forecast ------------------------------------------------------------------
with tab_product:
    options = view.sort_values("revenue", ascending=False)
    labels = {r.product_id: f"{r.product_id} · {r.category} · class {r.abc_class}" for r in options.itertuples()}
    pid = st.selectbox("Product", list(labels), format_func=labels.get)

    detail = api(f"/forecast/{pid}")
    fc = pd.DataFrame(detail["points"])
    fc["date"] = pd.to_datetime(fc["date"])
    hist = frame(f"/history/{pid}", days=history_days)

    row = view.set_index("product_id").loc[pid]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Forecast, next {len(fc)} days", f"{detail['total_forecast']:,.0f} units")
    c2.metric("80% range", f"{fc['lower'].sum():,.0f} – {fc['upper'].sum():,.0f}")
    c3.metric("Average per day", f"{fc['forecast'].mean():,.1f}")
    c4.metric(f"Actual, last {len(fc)} days", f"{row.get('recent_actual', float('nan')):,.0f}",
              pct(row.get("change_vs_recent")) + " forecast change", delta_color="off")

    st.plotly_chart(forecast_chart(hist, fc), use_container_width=True)
    st.caption("The band is an empirical 80% interval from this product's backtest errors. "
               "Future days assume the latest regular price and no promotions unless a promo plan was supplied.")

    with st.expander("Daily forecast table"):
        table = fc.assign(date=fc["date"].dt.date)
        st.dataframe(table, hide_index=True, use_container_width=True, column_config={
            "forecast": st.column_config.NumberColumn("Forecast", format="%.1f"),
            "lower": st.column_config.NumberColumn("Lower (P10)", format="%.1f"),
            "upper": st.column_config.NumberColumn("Upper (P90)", format="%.1f"),
            "price": st.column_config.NumberColumn("Price", format="$%.2f"),
            "on_promo": st.column_config.CheckboxColumn("Promo"),
        })
        st.download_button("Download CSV", table.to_csv(index=False), f"forecast_{pid}.csv", "text/csv")

# All products ----------------------------------------------------------------------
with tab_all:
    left, right = st.columns([2, 3])
    by_cat = (view.groupby("category", as_index=False)[["total_forecast", "recent_actual"]].sum()
                  .sort_values("total_forecast", ascending=False))
    with left:
        show(bar_chart(by_cat, "total_forecast", "category", [colors[c] for c in by_cat["category"]], ",.0f"),
             f"Forecast units by category, next {model['horizon']} days")
    with right:
        movers = view.dropna(subset=["change_vs_recent"]).sort_values("change_vs_recent")
        movers = pd.concat([movers.tail(5)[::-1], movers.head(5)]).drop_duplicates("product_id")
        show(bar_chart(movers, "change_vs_recent", "product_id", ACTUAL, "+.0%", tickformat="+.0%"),
             "Biggest forecast changes vs the last period")

    table = view[["product_id", "category", "abc_class", "total_forecast", "total_lower", "total_upper",
                  "recent_actual", "change_vs_recent", "avg_daily"]].sort_values("total_forecast", ascending=False)
    st.dataframe(table, hide_index=True, use_container_width=True, column_config={
        "product_id": "Product", "category": "Category", "abc_class": "ABC",
        "total_forecast": st.column_config.ProgressColumn(
            f"Forecast ({model['horizon']}d)", format="%.0f", min_value=0, max_value=float(table["total_forecast"].max())),
        "total_lower": st.column_config.NumberColumn("Lower", format="%.0f"),
        "total_upper": st.column_config.NumberColumn("Upper", format="%.0f"),
        "recent_actual": st.column_config.NumberColumn("Last period actual", format="%.0f"),
        "change_vs_recent": st.column_config.NumberColumn("Change", format="percent"),
        "avg_daily": st.column_config.NumberColumn("Avg / day", format="%.1f"),
    })
    st.download_button("Download all forecasts (summary CSV)", table.to_csv(index=False), "forecast_summary.csv", "text/csv")

# Sales analytics ---------------------------------------------------------------------
with tab_sales:
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total revenue", f"${summary['total_revenue'] / 1e6:,.2f}M", help=f"{summary['date_from']} to {summary['date_to']}")
    s2.metric("Units sold", f"{summary['total_units']:,}")
    s3.metric("Avg daily revenue", f"${summary['avg_daily_revenue']:,.0f}")
    s4.metric("Last 30 days vs same period last year", pct(summary.get("revenue_growth_yoy_30d")))

    monthly = frame("/analytics/monthly", date_cols=("month",))
    monthly = monthly[monthly["category"].isin(cats)]
    fig = go.Figure()
    for cat in sorted(monthly["category"].unique()):
        g = monthly[monthly["category"] == cat]
        fig.add_trace(go.Scatter(x=g["month"], y=g["revenue"], mode="lines+markers", name=cat,
                                 line=dict(color=colors[cat], width=2),
                                 marker=dict(size=8, line=dict(color=SURFACE, width=2)),
                                 hovertemplate="$%{y:,.0f}"))
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    fig.update_xaxes(hoverformat="%b %Y")
    show(style(fig, height=400), "Monthly revenue by category")

    a, b = st.columns(2)
    with a:
        cat_df = frame("/analytics/categories", date_cols=())
        cat_df = cat_df[cat_df["category"].isin(cats)].sort_values("revenue_share", ascending=False)
        show(bar_chart(cat_df, "revenue_share", "category", [colors[c] for c in cat_df["category"]], ".1%"),
             "Share of total revenue")
    with b:
        promo = frame("/analytics/promo-lift", date_cols=())
        promo = promo[promo["category"].isin(cats)].sort_values("promo_lift", ascending=False)
        show(bar_chart(promo, "promo_lift", "category", [colors[c] for c in promo["category"]], "+.0%"),
             "Average unit lift on promotion days")

    st.subheader("Category detail")
    st.dataframe(cat_df, hide_index=True, use_container_width=True, column_config={
        "category": "Category", "revenue": st.column_config.NumberColumn("Revenue", format="dollar"),
        "units": st.column_config.NumberColumn("Units", format="localized"), "products": "Products",
        "revenue_share": st.column_config.NumberColumn("Share", format="percent"),
        "growth_vs_prior_30d": st.column_config.NumberColumn("Last 30d vs prior", format="percent"),
    })
    st.subheader("Top products by revenue")
    top = frame("/analytics/top-products", date_cols=(), n=500)
    top = top[top["category"].isin(cats) & top["abc_class"].isin(classes)].head(15)
    st.dataframe(top[["product_id", "category", "abc_class", "revenue", "units", "avg_daily_units", "zero_sales_days"]],
                 hide_index=True, use_container_width=True, column_config={
                     "product_id": "Product", "category": "Category", "abc_class": "ABC",
                     "revenue": st.column_config.NumberColumn("Revenue", format="dollar"),
                     "units": st.column_config.NumberColumn("Units", format="localized"),
                     "avg_daily_units": st.column_config.NumberColumn("Avg / day", format="%.1f"),
                     "zero_sales_days": "Zero-sale days",
                 })

# Model ---------------------------------------------------------------------------------
with tab_model:
    run_url = f"{MLFLOW_UI_URL}/#/experiments/{model.get('experiment_id', '')}/runs/{model['run_id']}"
    st.markdown(f"**MLflow run:** [{model['run_name']}]({run_url}) · "
                f"[model registry]({MLFLOW_UI_URL}/#/models/{model['registered_model']})")
    mm = st.columns(4)
    mm[0].metric("WAPE", f"{m['backtest_wape']:.1%}")
    mm[1].metric("Seasonal-naive WAPE", f"{m['naive_wape']:.1%}")
    mm[2].metric("Error reduction vs naive", f"{m['wape_skill_vs_naive']:.0%}")
    mm[3].metric("Bias", f"{m['backtest_bias']:+.1%}", help="Positive = over-forecasting.")
    mm2 = st.columns(4)
    mm2[0].metric("MAE (units/day)", f"{m['backtest_mae']:.2f}")
    mm2[1].metric("RMSE (units/day)", f"{m['backtest_rmse']:.2f}")
    mm2[2].metric("Model version", f"v{model['model_version']}")
    champ = model.get("champion_version")
    mm2[3].metric("Champion version", f"v{champ}" if champ else "n/a",
                  "this run" if model.get("promoted_to_champion") else "this run not promoted", delta_color="off",
                  help="The champion alias moves only when a new version beats the current backtest WAPE. "
                       "Forecasts shown are always from the latest training run.")
    st.caption(f"Trained {pd.to_datetime(model['trained_at']):%Y-%m-%d %H:%M} UTC. "
               "Per-product metrics, backtest charts and feature importance are in the MLflow run's artifacts.")
