"""Forecast accuracy metrics and time-based backtesting helpers.

Backtests use rolling origins (train on data up to a cutoff, forecast the next
``horizon`` days, score against what happened) - never random splits.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def metrics(actual, pred) -> dict[str, float]:
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    err = p - a
    denom = np.abs(a).sum()
    nz = a != 0
    return {
        "mae": float(np.mean(np.abs(err))) if len(a) else float("nan"),
        "rmse": float(np.sqrt(np.mean(err ** 2))) if len(a) else float("nan"),
        "wape": float(np.abs(err).sum() / denom) if denom else float("nan"),
        "bias": float(err.sum() / denom) if denom else float("nan"),   # > 0 = over-forecasting
        "mape": float(np.mean(np.abs(err[nz] / a[nz]))) if nz.any() else float("nan"),
        "n_obs": int(len(a)),
    }


def backtest_cutoffs(last_date: pd.Timestamp, horizon: int, folds: int) -> list[pd.Timestamp]:
    """Non-overlapping origins, oldest first; the newest window ends on ``last_date``."""
    return [last_date - pd.Timedelta(days=horizon * k) for k in range(folds, 0, -1)]


def per_product(df: pd.DataFrame, actual: str, pred: str) -> pd.DataFrame:
    rows = []
    for sku, g in df.groupby("sku", observed=True):
        rows.append({"sku": sku, **metrics(g[actual], g[pred])})
    return pd.DataFrame(rows)


def residual_quantiles(df: pd.DataFrame, actual: str, pred: str, lo: float = 0.1, hi: float = 0.9) -> pd.DataFrame:
    """Per-product empirical error quantiles from a backtest -> prediction intervals."""
    r = (df[actual] - df[pred]).groupby(df["sku"].astype(str))
    q = pd.DataFrame({"resid_lo": r.quantile(lo), "resid_hi": r.quantile(hi)})
    return q.reset_index().rename(columns={"index": "sku"})


def seasonal_naive(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Baseline: repeat each product's last observed week."""
    last = history["date"].max()
    wk = history[history["date"] > last - pd.Timedelta(days=7)]
    wk = wk.assign(dow=wk["date"].dt.dayofweek)[["sku", "dow", "units_sold"]]
    dates = pd.date_range(last + pd.Timedelta(days=1), periods=horizon, freq="D")
    fut = pd.DataFrame({"date": dates, "dow": dates.dayofweek}).merge(wk, on="dow")
    return fut.rename(columns={"units_sold": "forecast"})[["date", "sku", "forecast"]]
