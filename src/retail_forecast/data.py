"""Loading, validating and (optionally) synthesising daily product-level sales data.

Expected schema (one row per product per day):

    date        YYYY-MM-DD
    product_id  str
    category    str
    price       float   selling price that day
    on_promo    0/1     promotion running that day
    units_sold  int     demand (target)

Missing product-days are filled with zero sales so every series is contiguous.
"""

from __future__ import annotations

from pathlib import Path

import holidays
import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["date", "product_id", "category", "price", "on_promo", "units_sold"]

CATEGORIES = {
    # name: (weekly profile Mon..Sun, yearly peak day-of-year, yearly amplitude, price range)
    "Grocery": ([1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.2], 355, 0.10, (1.5, 8.0)),
    "Beverages": ([0.9, 0.9, 0.95, 1.0, 1.15, 1.35, 1.25], 200, 0.35, (1.0, 5.0)),
    "Snacks": ([0.9, 0.9, 0.9, 1.0, 1.2, 1.4, 1.3], 355, 0.25, (1.5, 6.0)),
    "Household": ([1.1, 1.0, 1.0, 1.0, 0.95, 1.05, 0.9], 90, 0.08, (3.0, 20.0)),
    "Personal Care": ([1.05, 1.0, 1.0, 1.0, 1.0, 1.05, 0.9], 160, 0.12, (2.5, 15.0)),
}


def generate_synthetic_sales(
    n_products: int = 40,
    start: str = "2023-11-01",
    end: str = "2026-10-31",
    seed: int = 42,
) -> pd.DataFrame:
    """Create a realistic-looking retail demand dataset.

    Each product gets its own base level, trend, weekly/yearly seasonality (driven by
    its category), holiday uplift, randomly scheduled promotions with price elasticity,
    and negative-binomial noise. A few low-volume products are intermittent.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="D")
    n = len(dates)
    t = np.arange(n)
    doy = dates.dayofyear.to_numpy()
    dow = dates.dayofweek.to_numpy()
    us_holidays = holidays.UnitedStates(years=range(dates.year.min(), dates.year.max() + 1))
    is_holiday = np.array([d in us_holidays for d in dates.date])
    # Demand spikes in the days *before* a holiday (shopping), dips on the day itself.
    pre_holiday = np.zeros(n, dtype=bool)
    for i in np.flatnonzero(is_holiday):
        pre_holiday[max(0, i - 3) : i] = True

    cat_names = list(CATEGORIES)
    frames = []
    for p in range(n_products):
        cat = cat_names[p % len(cat_names)]
        weekly, peak_doy, amp, (pmin, pmax) = CATEGORIES[cat]
        weekly = np.asarray(weekly)

        intermittent = rng.random() < 0.12
        base = rng.lognormal(mean=0.6 if intermittent else 3.0, sigma=0.6)
        trend = rng.normal(0.0, 0.25) / n  # relative change over the full period
        amp_p = amp * rng.uniform(0.6, 1.4)
        base_price = round(rng.uniform(pmin, pmax), 2)
        elasticity = rng.uniform(1.2, 2.8)

        # Promotions: blocks of 3-7 days, roughly 8% of days.
        on_promo = np.zeros(n, dtype=int)
        i = int(rng.integers(0, 30))
        while i < n:
            if rng.random() < 0.25:
                length = int(rng.integers(3, 8))
                on_promo[i : i + length] = 1
                i += length + int(rng.integers(10, 30))
            else:
                i += int(rng.integers(5, 15))
        discount = np.where(on_promo == 1, rng.choice([0.1, 0.15, 0.2, 0.25, 0.3], size=n), 0.0)

        # Slow price inflation plus promo discount.
        list_price = base_price * (1 + 0.03 * t / 365)
        price = np.round(list_price * (1 - discount), 2)

        level = base * (1 + trend * t)
        seasonal_year = 1 + amp_p * np.cos(2 * np.pi * (doy - peak_doy) / 365.25)
        seasonal_week = weekly[dow]
        holiday_fx = np.where(pre_holiday, 1.35, 1.0) * np.where(is_holiday, 0.7, 1.0)
        promo_fx = (1 - discount) ** (-elasticity)
        lam = np.clip(level * seasonal_year * seasonal_week * holiday_fx * promo_fx, 0.05, None)

        # Negative binomial (gamma-Poisson) noise; dispersion r controls overdispersion.
        r = 3.0 if intermittent else 12.0
        units = rng.poisson(rng.gamma(shape=r, scale=lam / r))

        frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "product_id": f"P{p + 1:03d}",
                    "category": cat,
                    "price": price,
                    "on_promo": on_promo,
                    "units_sold": units.astype(int),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def validate_and_clean(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Sales data is missing required columns: {missing}")

    df = df[REQUIRED_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["product_id"] = df["product_id"].astype(str)
    df["category"] = df["category"].astype(str)
    df["units_sold"] = pd.to_numeric(df["units_sold"], errors="coerce").fillna(0).clip(lower=0)
    df["on_promo"] = pd.to_numeric(df["on_promo"], errors="coerce").fillna(0).astype(int).clip(0, 1)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    # Aggregate accidental duplicates, then make each series contiguous.
    df = (
        df.groupby(["product_id", "date"], as_index=False)
        .agg(category=("category", "last"), price=("price", "mean"),
             on_promo=("on_promo", "max"), units_sold=("units_sold", "sum"))
    )
    full_idx = pd.MultiIndex.from_product(
        [df["product_id"].unique(), pd.date_range(df["date"].min(), df["date"].max(), freq="D")],
        names=["product_id", "date"],
    )
    df = df.set_index(["product_id", "date"]).reindex(full_idx).reset_index()
    df["units_sold"] = df["units_sold"].fillna(0)
    df["on_promo"] = df["on_promo"].fillna(0).astype(int)
    df["category"] = df.groupby("product_id")["category"].transform(lambda s: s.ffill().bfill())
    df["price"] = df.groupby("product_id")["price"].transform(lambda s: s.ffill().bfill())
    return df.sort_values(["product_id", "date"]).reset_index(drop=True)


def load_sales(path: Path, *, synthetic_kwargs: dict | None = None) -> pd.DataFrame:
    """Load sales from CSV, generating a synthetic dataset first if the file is absent."""
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        generate_synthetic_sales(**(synthetic_kwargs or {})).to_csv(path, index=False)
    return validate_and_clean(pd.read_csv(path))
