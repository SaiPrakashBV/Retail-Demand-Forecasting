"""Backtesting (rolling origin) and forecast accuracy metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .features import TARGET


def metrics(actual: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    err = pred - actual
    denom = np.abs(actual).sum()
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        # Weighted absolute percentage error: robust to zero-demand days.
        "wape": float(np.abs(err).sum() / denom) if denom else float("nan"),
        # Positive bias = over-forecasting.
        "bias": float(err.sum() / denom) if denom else float("nan"),
    }


def seasonal_naive(history: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Repeat each product's last observed week across the horizon."""
    last_date = history["date"].max()
    last_week = history[history["date"] > last_date - pd.Timedelta(days=7)]
    last_week = last_week.assign(dow=last_week["date"].dt.dayofweek)[["product_id", "dow", TARGET]]
    dates = pd.date_range(last_date + pd.Timedelta(days=1), periods=horizon, freq="D")
    fut = pd.DataFrame({"date": dates, "dow": dates.dayofweek}).merge(last_week, on="dow")
    return fut.rename(columns={TARGET: "naive"})[["date", "product_id", "naive"]]


def backtest_cutoffs(last_date: pd.Timestamp, horizon: int, folds: int) -> list[pd.Timestamp]:
    """Non-overlapping forecast origins, oldest first; the newest fold ends on last_date."""
    return [last_date - pd.Timedelta(days=horizon * k) for k in range(folds, 0, -1)]


def run_backtest(sales: pd.DataFrame, make_model, horizon: int, folds: int):
    """Train on data up to each cutoff, forecast ``horizon`` days, score vs actuals.

    Returns (per-row predictions, per-fold metric dicts).
    """
    last_date = sales["date"].max()
    rows, fold_metrics = [], []
    for k, cutoff in enumerate(backtest_cutoffs(last_date, horizon, folds)):
        train = sales[sales["date"] <= cutoff]
        test = sales[(sales["date"] > cutoff) & (sales["date"] <= cutoff + pd.Timedelta(days=horizon))]
        model = make_model().fit(train)
        fc = model.forecast(train, horizon, future_exog=test[["date", "product_id", "price", "on_promo"]])
        scored = (
            test[["date", "product_id", "category", TARGET]]
            .merge(fc[["date", "product_id", "forecast"]], on=["date", "product_id"])
            .merge(seasonal_naive(train, horizon), on=["date", "product_id"])
        )
        scored["fold"] = k
        scored["horizon_day"] = (scored["date"] - cutoff).dt.days
        rows.append(scored)

        m = {f"model_{k_}": v for k_, v in metrics(scored[TARGET], scored["forecast"]).items()}
        m |= {f"naive_{k_}": v for k_, v in metrics(scored[TARGET], scored["naive"]).items()}
        m["cutoff"] = cutoff.date().isoformat()
        fold_metrics.append(m)
    return pd.concat(rows, ignore_index=True), fold_metrics


def per_product_metrics(bt: pd.DataFrame) -> pd.DataFrame:
    recs = []
    for pid, g in bt.groupby("product_id"):
        mm, nm = metrics(g[TARGET], g["forecast"]), metrics(g[TARGET], g["naive"])
        recs.append({"product_id": pid, "category": g["category"].iloc[0],
                     "avg_daily_units": g[TARGET].mean(), **mm,
                     "naive_wape": nm["wape"]})
    return pd.DataFrame(recs).sort_values("wape").reset_index(drop=True)


def residual_intervals(bt: pd.DataFrame, lower_q: float = 0.1, upper_q: float = 0.9) -> pd.DataFrame:
    """Per-product empirical residual quantiles from the backtest, for prediction intervals."""
    res = bt.assign(resid=bt[TARGET] - bt["forecast"])
    q = res.groupby("product_id")["resid"].quantile([lower_q, upper_q]).unstack()
    q.columns = ["resid_lo", "resid_hi"]
    return q.reset_index()
