"""Descriptive retail sales analytics: KPIs, category mix, ABC classes, promo lift."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def _growth(cur: float, prev: float) -> float | None:
    return round((cur - prev) / prev, 4) if prev else None


def compute_analytics(sales: pd.DataFrame) -> dict[str, pd.DataFrame | dict]:
    df = sales.assign(revenue=sales["units_sold"] * sales["price"])
    last = df["date"].max()

    def window(days: int, offset: int = 0) -> pd.DataFrame:
        end = last - pd.Timedelta(days=offset)
        return df[(df["date"] > end - pd.Timedelta(days=days)) & (df["date"] <= end)]

    l30, p30, ly30 = window(30), window(30, 30), window(30, 364)
    summary = {
        "date_from": df["date"].min().date().isoformat(),
        "date_to": last.date().isoformat(),
        "n_products": int(df["product_id"].nunique()),
        "n_categories": int(df["category"].nunique()),
        "total_revenue": round(float(df["revenue"].sum()), 2),
        "total_units": int(df["units_sold"].sum()),
        "avg_daily_revenue": round(float(df.groupby("date")["revenue"].sum().mean()), 2),
        "last_30d_revenue": round(float(l30["revenue"].sum()), 2),
        "last_30d_units": int(l30["units_sold"].sum()),
        "revenue_growth_vs_prior_30d": _growth(l30["revenue"].sum(), p30["revenue"].sum()),
        "revenue_growth_yoy_30d": _growth(l30["revenue"].sum(), ly30["revenue"].sum()),
    }

    monthly = (
        df.set_index("date").groupby([pd.Grouper(freq="MS"), "category"])[["revenue", "units_sold"]]
        .sum().reset_index().rename(columns={"date": "month"})
    )

    cat = df.groupby("category").agg(revenue=("revenue", "sum"), units=("units_sold", "sum"),
                                      products=("product_id", "nunique")).reset_index()
    cat["revenue_share"] = cat["revenue"] / cat["revenue"].sum()
    cat_l30 = l30.groupby("category")["revenue"].sum()
    cat_p30 = p30.groupby("category")["revenue"].sum()
    cat["growth_vs_prior_30d"] = cat["category"].map((cat_l30 - cat_p30) / cat_p30)
    cat = cat.sort_values("revenue", ascending=False).reset_index(drop=True)

    # ABC: A = products making the first 80% of revenue, B = next 15%, C = the rest.
    prod = df.groupby(["product_id", "category"]).agg(
        revenue=("revenue", "sum"), units=("units_sold", "sum"),
        avg_daily_units=("units_sold", "mean"), zero_sales_days=("units_sold", lambda s: int((s == 0).sum())),
    ).reset_index().sort_values("revenue", ascending=False)
    prod["cum_share"] = prod["revenue"].cumsum() / prod["revenue"].sum()
    prev_share = prod["cum_share"].shift(fill_value=0)
    prod["abc_class"] = pd.cut(prev_share, [-1, 0.8, 0.95, 1.01], labels=["A", "B", "C"]).astype(str)
    prod = prod.reset_index(drop=True)

    promo = (
        df.groupby(["category", "on_promo"])["units_sold"].mean().unstack()
        .rename(columns={0: "avg_units_regular", 1: "avg_units_promo"}).reset_index()
    )
    promo["promo_lift"] = promo["avg_units_promo"] / promo["avg_units_regular"] - 1

    dow =(df.assign(weekday=df["date"].dt.dayofweek, day=df["date"].dt.day_name())
             .groupby(["weekday", "day"])["revenue"].sum().reset_index())
    dow["index_vs_avg"] = dow["revenue"] / dow["revenue"].mean()

    return {"summary": summary, "monthly_by_category": monthly, "categories": cat,
            "products": prod, "promo_lift": promo, "day_of_week": dow.drop(columns="weekday")}


def save_analytics(results: dict, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, obj in results.items():
        if isinstance(obj, dict):
            p = out_dir / f"{name}.json"
            p.write_text(json.dumps(obj, indent=2))
        else:
            p = out_dir / f"{name}.csv"
            obj.to_csv(p, index=False)
        paths.append(p)
    return paths
