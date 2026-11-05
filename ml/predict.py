"""Generate future predictions with the selected models and shape them for storage."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .train_demand import DemandBacktest, XGBoostDemandModel, make_model, relative_band, residuals_for
from .train_price import PriceBacktest, eligible_price_skus, make_price_model, price_residuals


def combine(demand: pd.DataFrame, price: pd.DataFrame | None) -> pd.DataFrame:
    """Join daily demand and (where available) price forecasts; price NaN = unavailable."""
    d = demand.assign(sku=demand["sku"].astype(str), date=pd.to_datetime(demand["date"]))
    if price is None or price.empty:
        return d.assign(price_forecast=np.nan, price_lower=np.nan, price_upper=np.nan)
    p = price.assign(sku=price["sku"].astype(str), date=pd.to_datetime(price["date"]))
    return d.merge(p[["date", "sku", "price_forecast", "price_lower", "price_upper"]], on=["date", "sku"], how="left")


def production_demand(daily: pd.DataFrame, skus: list[str], model_name: str, bt: DemandBacktest, horizon: int,
                      seed: int, n_jobs: int):
    history = daily[daily["sku"].isin(skus)]
    model = make_model(model_name, seed, n_jobs).fit(history)
    if isinstance(model, XGBoostDemandModel):
        model.residuals = residuals_for(bt, model_name)
        model.relative_band = relative_band(bt, model_name)
    return model, model.forecast(history, horizon)


def production_price(prices: pd.DataFrame, model_name: str, bt: PriceBacktest | None, horizon: int, min_days: int,
                     seed: int, n_jobs: int):
    if prices.empty:
        return None, None, []
    skus = eligible_price_skus(prices, prices["date"].max(), min_days)
    if not skus:
        return None, None, []
    history = prices[prices["sku"].isin(skus)]
    model = make_price_model(model_name, seed, n_jobs, horizon).fit(history)
    if bt is not None:
        model.residuals = price_residuals(bt, model_name)
    return model, model.forecast(history, horizon), skus


def backtest_frames(demand_bt: DemandBacktest, price_bt: PriceBacktest | None) -> dict[pd.Timestamp, pd.DataFrame]:
    """Selected models' backtest predictions per cutoff, as 'forecasts made earlier'."""
    sel = demand_bt.predictions[demand_bt.predictions["model"] == demand_bt.selected]
    if sel["lower"].isna().all():
        q = residuals_for(demand_bt, demand_bt.selected)
        sel = sel.drop(columns=["lower", "upper"]).merge(q, on="sku", how="left")
        sel["lower"] = (sel["forecast"] + sel["resid_lo"]).clip(lower=0)
        sel["upper"] = (sel["forecast"] + sel["resid_hi"]).clip(lower=0)
    out = {}
    for cutoff, g in sel.groupby("cutoff"):
        demand = g[["date", "sku", "forecast", "lower", "upper"]].dropna(subset=["forecast"])
        price = None
        if price_bt is not None:
            p = price_bt.predictions[(price_bt.predictions["model"] == price_bt.selected)
                                     & (price_bt.predictions["cutoff"] == cutoff)]
            if len(p):
                q = price_residuals(price_bt, price_bt.selected)
                p = p.merge(q, on="sku", how="left")
                p["price_lower"] = (p["price_forecast"] + p["resid_lo"].fillna(0)).clip(lower=0.01)
                p["price_upper"] = p["price_forecast"] + p["resid_hi"].fillna(0)
                price = p
        out[cutoff] = combine(demand, price)
    return out
