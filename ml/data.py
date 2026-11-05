"""Load model-ready daily series from PostgreSQL."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


def load_daily(engine: Engine) -> pd.DataFrame:
    """One row per product per day from its first sale/launch to the latest loaded date.

    Columns: date, sku, product_id, category, units_sold, price, regular_price, on_promo, in_stock.
    ``in_stock`` = 0 on days the product ended with no stock (demand was censored).
    """
    with engine.connect() as conn:
        products = pd.read_sql(text("""SELECT product_id, sku, category, current_price, launch_date
                                        FROM products WHERE is_active"""), conn)
        sales = pd.read_sql(text("SELECT product_id, sale_date AS date, units, avg_price, on_promo "
                                 "FROM daily_product_sales"), conn)
        prices = pd.read_sql(text("SELECT product_id, price_date AS date, actual_price, price_type "
                                  "FROM price_history"), conn)
        snaps = pd.read_sql(text("SELECT product_id, snapshot_date AS date, quantity FROM inventory_snapshots"), conn)
    if sales.empty:
        return pd.DataFrame(columns=["date", "sku", "product_id", "category", "units_sold", "price", "regular_price",
                                     "on_promo", "in_stock"])
    for df in (sales, prices, snaps):
        df["date"] = pd.to_datetime(df["date"])
    end = sales["date"].max()
    first_sale = sales.groupby("product_id")["date"].min()
    launch = pd.to_datetime(products["launch_date"])
    products["start"] = pd.concat([launch, products["product_id"].map(first_sale)], axis=1).min(axis=1)
    products = products.dropna(subset=["start"])

    grid = pd.concat([
        pd.DataFrame({"product_id": r.product_id, "date": pd.date_range(r.start, end, freq="D")})
        for r in products.itertuples()
    ], ignore_index=True)
    df = (grid.merge(products[["product_id", "sku", "category", "current_price"]], on="product_id")
              .merge(sales, on=["product_id", "date"], how="left")
              .merge(prices, on=["product_id", "date"], how="left")
              .merge(snaps, on=["product_id", "date"], how="left"))
    df["units_sold"] = df["units"].fillna(0).astype(float)
    price = df["actual_price"].astype(float).fillna(df["avg_price"].astype(float))
    df["price"] = price.groupby(df["product_id"]).ffill().fillna(df["current_price"].astype(float))
    df["on_promo"] = ((df["price_type"] == "promo") | (df["on_promo"].astype("boolean").fillna(False))).astype(int)
    regular = df["actual_price"].where(df["price_type"] == "regular").astype(float)
    df["regular_price"] = regular.groupby(df["product_id"]).ffill().fillna(df["price"])
    # Sold out at the end of the day, and nothing more could be sold.
    df["in_stock"] = np.where(df["quantity"].notna() & (df["quantity"] <= 0), 0, 1)
    out = df[["date", "sku", "product_id", "category", "units_sold", "price", "regular_price", "on_promo", "in_stock"]]
    return out.sort_values(["sku", "date"]).reset_index(drop=True)


def load_prices(engine: Engine) -> pd.DataFrame:
    """Recorded selling prices only (no imputation) - the price model's training data."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT p.sku, p.product_id, p.category, ph.price_date AS date, ph.actual_price::float AS price,
                   (ph.price_type = 'promo')::int AS on_promo
            FROM price_history ph JOIN products p USING (product_id) WHERE p.is_active
            ORDER BY p.sku, ph.price_date"""), conn)
    df["date"] = pd.to_datetime(df["date"])
    return df


def history_days(df: pd.DataFrame, at: pd.Timestamp) -> pd.Series:
    """Days between each product's first record and ``at``."""
    first = df[df["date"] <= at].groupby("sku")["date"].min()
    return (at - first).dt.days + 1
