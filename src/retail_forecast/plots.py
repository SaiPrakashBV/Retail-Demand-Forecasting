"""Static charts logged as MLflow artifacts and written to the outputs folder."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SERIES_1 = "#2a78d6"  # actuals / single series
SERIES_2 = "#eb6834"  # forecast


def _style(ax, title: str, ylabel: str = "") -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=TEXT, fontsize=12, fontweight="semibold")
    ax.set_ylabel(ylabel, color=TEXT_2)
    ax.tick_params(colors=TEXT_2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


def _fig(w=10, h=4):
    fig, ax = plt.subplots(figsize=(w, h), dpi=120)
    fig.patch.set_facecolor(SURFACE)
    return fig, ax


def forecast_plot(history: pd.DataFrame, forecast: pd.DataFrame, product_id: str, path: Path, days: int = 120) -> Path:
    h = history[history["product_id"] == product_id].tail(days)
    f = forecast[forecast["product_id"] == product_id]
    fig, ax = _fig()
    ax.plot(h["date"], h["units_sold"], color=SERIES_1, linewidth=1.6, label="Actual")
    if {"lower", "upper"} <= set(f.columns):
        ax.fill_between(f["date"], f["lower"], f["upper"], color=SERIES_2, alpha=0.18, linewidth=0, label="80% interval")
    ax.plot(f["date"], f["forecast"], color=SERIES_2, linewidth=2, label="Forecast")
    ax.set_ylim(bottom=0)
    _style(ax, f"{product_id} · daily units, last {days} days + {len(f)}-day forecast", "Units")
    ax.legend(frameon=False, labelcolor=TEXT_2, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def backtest_plot(bt: pd.DataFrame, path: Path) -> Path:
    daily = bt.groupby("date")[["units_sold", "forecast", "naive"]].sum().reset_index()
    fig, ax = _fig()
    ax.plot(daily["date"], daily["units_sold"], color=SERIES_1, linewidth=1.8, label="Actual")
    ax.plot(daily["date"], daily["forecast"], color=SERIES_2, linewidth=1.8, label="XGBoost")
    ax.plot(daily["date"], daily["naive"], color=TEXT_2, linewidth=1.2, linestyle="--", label="Seasonal naive")
    for cutoff in bt.groupby("fold")["date"].min():
        ax.axvline(cutoff, color=GRID, linewidth=1)
    _style(ax, "Backtest · total daily units across all products", "Units")
    ax.legend(frameon=False, labelcolor=TEXT_2, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def feature_importance_plot(importance: pd.Series, path: Path, top: int = 15) -> Path:
    imp = importance.head(top)[::-1]
    fig, ax = _fig(8, 5)
    ax.barh(imp.index, imp.values, color=SERIES_1, height=0.6)
    _style(ax, f"Top {top} features by gain")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path


def revenue_trend_plot(monthly: pd.DataFrame, path: Path) -> Path:
    total = monthly.groupby("month")["revenue"].sum()
    fig, ax = _fig()
    ax.plot(total.index, total.values, color=SERIES_1, linewidth=2, marker="o", markersize=4)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"${v / 1000:,.0f}k"))
    _style(ax, "Monthly revenue, all products")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return path
