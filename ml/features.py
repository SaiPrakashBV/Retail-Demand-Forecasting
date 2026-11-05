"""Time-series and calendar features for the global XGBoost models."""

from __future__ import annotations

from functools import lru_cache

import holidays
import numpy as np
import pandas as pd

TARGET = "units_sold"
LAGS = [1, 2, 3, 7, 14, 21, 28, 364]
ROLL_WINDOWS = [7, 28]
CATEGORICAL = ["sku", "category"]

CALENDAR_FEATURES = ["dow", "dom", "month", "weekofyear", "doy", "is_weekend", "is_holiday", "days_to_holiday",
                     "days_since_holiday", "days_to_black_friday"]
PRICE_FEATURES = ["price", "price_ratio", "on_promo", "in_stock"]
LAG_FEATURES = ([f"lag_{lag}" for lag in LAGS] + [f"roll_mean_{w}" for w in ROLL_WINDOWS]
                + ["roll_std_28", "dow_mean_4w", "ewm_14", "stockout_days_28"])
DEMAND_FEATURES = CATEGORICAL + CALENDAR_FEATURES + PRICE_FEATURES + LAG_FEATURES
MAX_LOOKBACK = max(LAGS) + 1


@lru_cache(maxsize=8)
def holiday_dates(start_year: int, end_year: int) -> tuple[np.ndarray, np.ndarray]:
    cal = holidays.UnitedStates(years=range(start_year - 1, end_year + 2))
    days = np.array(sorted(pd.Timestamp(d) for d in cal), dtype="datetime64[ns]")
    bf = np.array(sorted(pd.Timestamp(d) + pd.Timedelta(days=1) for d, n in cal.items() if "Thanksgiving" in n),
                  dtype="datetime64[ns]")
    return days, bf


def _distance(dates: pd.Series, events: np.ndarray, cap: int = 30) -> tuple[np.ndarray, np.ndarray]:
    d = dates.to_numpy(dtype="datetime64[ns]")
    nxt = np.searchsorted(events, d, side="left")
    prv = np.searchsorted(events, d, side="right") - 1
    day = np.timedelta64(1, "D")
    to_next = (events[np.clip(nxt, 0, len(events) - 1)] - d) / day
    since = (d - events[np.clip(prv, 0, len(events) - 1)]) / day
    return np.clip(to_next, -1, cap), np.clip(since, 0, cap)


def calendar_features(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    date = df[date_col]
    hol, bf = holiday_dates(int(date.dt.year.min()), int(date.dt.year.max()))
    out = pd.DataFrame(index=df.index)
    out["dow"] = date.dt.dayofweek
    out["dom"] = date.dt.day
    out["month"] = date.dt.month
    out["weekofyear"] = date.dt.isocalendar().week.astype(int).to_numpy()
    out["doy"] = date.dt.dayofyear
    out["is_weekend"] = (out["dow"] >= 5).astype(int)
    to_h, since_h = _distance(date, hol)
    out["is_holiday"] = (to_h == 0).astype(int)
    out["days_to_holiday"], out["days_since_holiday"] = to_h, since_h
    to_bf, since_bf = _distance(date, bf, cap=60)
    # Signed distance to Black Friday: negative in the run-up, small positive during cyber week.
    out["days_to_black_friday"] = np.where(since_bf <= 7, -since_bf, to_bf)
    return out


def build_demand_features(df: pd.DataFrame, categories: dict[str, list[str]]) -> pd.DataFrame:
    """Features for frames sorted by (sku, date); future rows may have NaN units_sold."""
    out = df.sort_values(["sku", "date"]).copy()
    out[CALENDAR_FEATURES] = calendar_features(out)

    by = out.groupby("sku", sort=False)
    y = by[TARGET]
    for lag in LAGS:
        out[f"lag_{lag}"] = y.shift(lag)
    grp = y.shift(1).groupby(out["sku"], sort=False)
    for w in ROLL_WINDOWS:
        out[f"roll_mean_{w}"] = grp.transform(lambda s, w=w: s.rolling(w, min_periods=1).mean())
    out["roll_std_28"] = grp.transform(lambda s: s.rolling(28, min_periods=2).std())
    out["ewm_14"] = grp.transform(lambda s: s.ewm(span=14, adjust=False).mean())
    out["dow_mean_4w"] = out[["lag_7", "lag_14", "lag_21", "lag_28"]].mean(axis=1)
    stockout = (1 - out["in_stock"]).groupby(out["sku"], sort=False).shift(1)
    out["stockout_days_28"] = stockout.groupby(out["sku"], sort=False).transform(
        lambda s: s.rolling(28, min_periods=1).sum())
    ref = by["price"].transform(lambda s: s.rolling(28, min_periods=1).max())
    out["price_ratio"] = out["price"] / ref
    for c in CATEGORICAL:
        out[c] = pd.Categorical(out[c].astype(str), categories=categories[c])
    return out


def category_levels(df: pd.DataFrame) -> dict[str, list[str]]:
    return {c: sorted(df[c].astype(str).unique()) for c in CATEGORICAL}
