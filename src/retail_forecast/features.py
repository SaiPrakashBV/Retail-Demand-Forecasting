"""Feature engineering for the global (all-products) XGBoost demand model."""

from __future__ import annotations

from functools import lru_cache

import holidays
import numpy as np
import pandas as pd

TARGET = "units_sold"
LAGS = [1, 2, 3, 7, 14, 21, 28, 364]
ROLL_WINDOWS = [7, 28]

CALENDAR_FEATURES = [
    "dow", "dom", "month", "weekofyear", "doy", "is_weekend",
    "is_holiday", "days_to_holiday", "days_since_holiday",
]
PRICE_FEATURES = ["price", "price_ratio", "on_promo"]
LAG_FEATURES = (
    [f"lag_{lag}" for lag in LAGS]
    + [f"roll_mean_{w}" for w in ROLL_WINDOWS]
    + ["roll_std_28", "dow_mean_4w", "ewm_14"]
)
CATEGORICAL_FEATURES = ["product_id", "category"]
FEATURES = CATEGORICAL_FEATURES + CALENDAR_FEATURES + PRICE_FEATURES + LAG_FEATURES

# History needed to compute every lag/rolling feature for one new day.
MAX_LOOKBACK = max(LAGS) + 1


@lru_cache(maxsize=8)
def _holiday_dates(start_year: int, end_year: int) -> np.ndarray:
    cal = holidays.UnitedStates(years=range(start_year - 1, end_year + 2))
    return np.array(sorted(pd.Timestamp(d) for d in cal), dtype="datetime64[ns]")


def _holiday_distances(dates: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    hol = _holiday_dates(int(dates.dt.year.min()), int(dates.dt.year.max()))
    d = dates.to_numpy(dtype="datetime64[ns]")
    nxt = np.searchsorted(hol, d, side="left")
    prv = np.searchsorted(hol, d, side="right") - 1
    day = np.timedelta64(1, "D")
    to_next = (hol[np.clip(nxt, 0, len(hol) - 1)] - d) / day
    since_prev = (d - hol[np.clip(prv, 0, len(hol) - 1)]) / day
    is_hol = to_next == 0
    return is_hol.astype(int), np.clip(to_next, 0, 30), np.clip(since_prev, 0, 30)


def build_features(df: pd.DataFrame, categories: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """Add model features to a frame sorted by (product_id, date).

    ``units_sold`` may be NaN for future days: their lag features still resolve
    from earlier (actual or already-predicted) values, which is what the
    recursive forecaster relies on. The original index is preserved.
    """
    out = df.sort_values(["product_id", "date"]).copy()
    date = out["date"]

    out["dow"] = date.dt.dayofweek
    out["dom"] = date.dt.day
    out["month"] = date.dt.month
    out["weekofyear"] = date.dt.isocalendar().week.astype(int).to_numpy()
    out["doy"] = date.dt.dayofyear
    out["is_weekend"] = (out["dow"] >= 5).astype(int)
    out["is_holiday"], out["days_to_holiday"], out["days_since_holiday"] = _holiday_distances(date)

    by_product = out.groupby("product_id", sort=False)
    y = by_product[TARGET]
    for lag in LAGS:
        out[f"lag_{lag}"] = y.shift(lag)

    shifted = y.shift(1)
    grp = shifted.groupby(out["product_id"], sort=False)
    for w in ROLL_WINDOWS:
        out[f"roll_mean_{w}"] = grp.transform(lambda s, w=w: s.rolling(w, min_periods=1).mean())
    out["roll_std_28"] = grp.transform(lambda s: s.rolling(28, min_periods=2).std())
    out["ewm_14"] = grp.transform(lambda s: s.ewm(span=14, adjust=False).mean())
    out["dow_mean_4w"] = out[["lag_7", "lag_14", "lag_21", "lag_28"]].mean(axis=1)

    ref_price = by_product["price"].transform(lambda s: s.rolling(28, min_periods=1).max())
    out["price_ratio"] = out["price"] / ref_price

    cats = categories or {c: sorted(out[c].unique()) for c in CATEGORICAL_FEATURES}
    for c in CATEGORICAL_FEATURES:
        out[c] = pd.Categorical(out[c], categories=cats[c])
    return out


def category_levels(df: pd.DataFrame) -> dict[str, list[str]]:
    return {c: sorted(df[c].astype(str).unique()) for c in CATEGORICAL_FEATURES}
