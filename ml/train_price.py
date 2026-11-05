"""Price forecasting: a separate prediction problem from demand, with its own accuracy.

Predicts the expected *selling* price per day for the next 30 days, only for products with
enough recorded price history (``PRICE_MIN_HISTORY_DAYS``). Candidates:

* ``naive_last_regular``  the last regular (non-promotional) price carried forward;
* ``xgboost_price``       a global direct multi-horizon model of price / last regular price,
                          using promotion frequency/depth, time since the last promotion and
                          list-price change, and target-date calendar effects (e.g. Black Friday).

The lower backtest MAPE wins the run. Forecast prices are estimates for planning; they never
change catalog prices.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from .evaluate import backtest_cutoffs, metrics, residual_quantiles
from .features import calendar_features

ORIGIN_FEATURES = ["log_regular", "price_ratio_now", "promo_rate_90", "promo_rate_365", "avg_discount_365",
                   "days_since_promo", "days_since_reg_change", "reg_change_90", "price_cv_90"]
TARGET_FEATURES = ["h", "dow", "month", "doy", "is_holiday", "days_to_holiday", "days_to_black_friday"]
PRICE_FEATURES = ["sku", "category", *ORIGIN_FEATURES, *TARGET_FEATURES]


def eligible_price_skus(prices: pd.DataFrame, at: pd.Timestamp, min_days: int) -> list[str]:
    """Enough recorded prices up to ``at``, and recent ones (no stale feeds)."""
    p = prices[prices["date"] <= at]
    g = p.groupby("sku")["date"].agg(["count", "max"])
    ok = (g["count"] >= min_days) & (g["max"] >= at - pd.Timedelta(days=7))
    return sorted(g.index[ok].astype(str))


def daily_price_grid(prices: pd.DataFrame) -> pd.DataFrame:
    """Contiguous daily series per product (gaps forward-filled) with origin features."""
    frames = []
    for sku, g in prices.groupby("sku"):
        g = g.set_index("date").sort_index()
        idx = pd.date_range(g.index.min(), g.index.max(), freq="D")
        s = g.reindex(idx)
        s["observed"] = s["price"].notna()
        s[["price", "on_promo"]] = s[["price", "on_promo"]].ffill()
        s["sku"], s["category"] = sku, g["category"].iloc[0]
        regular = s["price"].where(s["on_promo"] == 0).ffill().fillna(s["price"])
        s["regular"] = regular
        s["log_regular"] = np.log(regular)
        s["price_ratio_now"] = s["price"] / regular
        s["promo_rate_90"] = s["on_promo"].rolling(90, min_periods=1).mean()
        s["promo_rate_365"] = s["on_promo"].rolling(365, min_periods=1).mean()
        disc = (1 - s["price"] / regular).where(s["on_promo"] == 1, 0.0)
        promo_days = s["on_promo"].rolling(365, min_periods=1).sum()
        s["avg_discount_365"] = (disc.rolling(365, min_periods=1).sum() / promo_days.replace(0, np.nan)).fillna(0)
        last_promo = pd.Series(np.where(s["on_promo"] == 1, np.arange(len(s)), np.nan), index=s.index).ffill()
        s["days_since_promo"] = np.clip(np.arange(len(s)) - last_promo.fillna(-999), 0, 999)
        changed = regular.ne(regular.shift()).to_numpy().copy()
        changed[0] = True
        last_change = pd.Series(np.where(changed, np.arange(len(s)), np.nan), index=s.index).ffill()
        s["days_since_reg_change"] = np.clip(np.arange(len(s)) - last_change, 0, 999)
        s["reg_change_90"] = regular / regular.shift(90).bfill() - 1
        s["price_cv_90"] = s["price"].rolling(90, min_periods=2).std().fillna(0) / s["price"].rolling(90, min_periods=1).mean()
        frames.append(s.rename_axis("date").reset_index())
    return pd.concat(frames, ignore_index=True)


def _target_rows(origins: pd.DataFrame, horizon: int) -> pd.DataFrame:
    rows = origins.loc[origins.index.repeat(horizon)].copy()
    rows["h"] = np.tile(np.arange(1, horizon + 1), len(origins))
    rows["target_date"] = rows["date"] + pd.to_timedelta(rows["h"], unit="D")
    cal = calendar_features(rows, "target_date")
    rows[[c for c in TARGET_FEATURES if c != "h"]] = cal[[c for c in TARGET_FEATURES if c != "h"]]
    return rows


@dataclass
class NaivePriceModel:
    name: str = "naive_last_regular"
    residuals: pd.DataFrame | None = None

    def fit(self, prices: pd.DataFrame) -> "NaivePriceModel":
        return self

    def forecast(self, prices: pd.DataFrame, horizon: int) -> pd.DataFrame:
        grid = daily_price_grid(prices)
        last = grid.sort_values("date").groupby("sku").tail(1)
        start = prices["date"].max()
        dates = pd.date_range(start + pd.Timedelta(days=1), periods=horizon, freq="D")
        fc = last[["sku", "regular"]].merge(pd.DataFrame({"date": dates}), how="cross")
        return _with_intervals(fc.rename(columns={"regular": "price_forecast"})[["date", "sku", "price_forecast"]],
                               self.residuals)

    def describe(self) -> dict:
        return {"price_naive": "last regular price carried forward"}


@dataclass
class XGBoostPriceModel:
    name: str = "xgboost_price"
    seed: int = 42
    n_jobs: int = -1
    horizon: int = 30
    origin_every_days: int = 7
    params: dict = field(default_factory=lambda: {
        "n_estimators": 400, "learning_rate": 0.05, "max_depth": 6, "min_child_weight": 10, "subsample": 0.8,
        "colsample_bytree": 0.9, "tree_method": "hist", "objective": "reg:absoluteerror", "max_cat_to_onehot": 1})
    model: XGBRegressor | None = None
    categories: dict | None = None
    residuals: pd.DataFrame | None = None

    def _cats(self, df: pd.DataFrame) -> pd.DataFrame:
        for c in ("sku", "category"):
            df[c] = pd.Categorical(df[c].astype(str), categories=self.categories[c])
        return df

    def fit(self, prices: pd.DataFrame) -> "XGBoostPriceModel":
        grid = daily_price_grid(prices)
        self.categories = {c: sorted(grid[c].astype(str).unique()) for c in ("sku", "category")}
        end = grid["date"].max()
        first = grid.groupby("sku")["date"].transform("min")
        origins = grid[((grid["date"] - first).dt.days >= 60)
                       & ((end - grid["date"]).dt.days % self.origin_every_days == 0)]
        rows = _target_rows(origins, self.horizon)
        actual = grid.loc[grid["observed"], ["sku", "date", "price"]].rename(
            columns={"date": "target_date", "price": "target_price"})
        rows = rows.merge(actual, on=["sku", "target_date"], how="inner")
        rows["y"] = rows["target_price"] / rows["regular"]
        rows = self._cats(rows)
        self.model = XGBRegressor(**self.params, enable_categorical=True, random_state=self.seed, n_jobs=self.n_jobs)
        self.model.fit(rows[PRICE_FEATURES], rows["y"])
        return self

    def forecast(self, prices: pd.DataFrame, horizon: int) -> pd.DataFrame:
        grid = daily_price_grid(prices)
        origin = grid.sort_values("date").groupby("sku").tail(1)
        origin = origin.assign(date=prices["date"].max())  # forecast from the common data end
        rows = self._cats(_target_rows(origin.reset_index(drop=True), horizon))
        ratio = self.model.predict(rows[PRICE_FEATURES])
        fc = pd.DataFrame({"date": rows["target_date"].to_numpy(), "sku": rows["sku"].astype(str).to_numpy(),
                           "price_forecast": np.round(np.clip(ratio, 0.3, 1.5) * rows["regular"].to_numpy(), 2)})
        return _with_intervals(fc, self.residuals)

    def describe(self) -> dict:
        return {f"price_xgb_{k}": v for k, v in self.params.items()} | {"price_origin_every_days": self.origin_every_days}


def _with_intervals(fc: pd.DataFrame, residuals: pd.DataFrame | None) -> pd.DataFrame:
    if residuals is None:
        return fc.assign(price_lower=np.nan, price_upper=np.nan)
    fc = fc.merge(residuals, on="sku", how="left")
    fc["price_lower"] = (fc["price_forecast"] + fc["resid_lo"].fillna(0)).clip(lower=0.01).round(2)
    fc["price_upper"] = (fc["price_forecast"] + fc["resid_hi"].fillna(0)).round(2)
    return fc.drop(columns=["resid_lo", "resid_hi"])


PRICE_FACTORIES = {"naive_last_regular": NaivePriceModel, "xgboost_price": XGBoostPriceModel}


def make_price_model(name: str, seed: int, n_jobs: int, horizon: int):
    if name == "xgboost_price":
        return XGBoostPriceModel(seed=seed, n_jobs=n_jobs, horizon=horizon)
    return NaivePriceModel()


@dataclass
class PriceBacktest:
    predictions: pd.DataFrame
    fold_metrics: pd.DataFrame
    overall: dict[str, dict]
    selected: str = ""


def run_price_backtest(prices: pd.DataFrame, horizon: int, folds: int, min_days: int, seed: int = 42,
                       n_jobs: int = -1, progress=None) -> PriceBacktest | None:
    if prices.empty:
        return None
    last = prices["date"].max()
    preds, rows = [], []
    for k, cutoff in enumerate(backtest_cutoffs(last, horizon, folds)):
        train = prices[prices["date"] <= cutoff]
        skus = eligible_price_skus(train, cutoff, min_days)
        if not skus:
            continue
        train = train[train["sku"].isin(skus)]
        test = prices[(prices["date"] > cutoff) & (prices["date"] <= cutoff + pd.Timedelta(days=horizon))
                      & prices["sku"].isin(skus)][["date", "sku", "category", "price"]]
        for name in PRICE_FACTORIES:
            if progress:
                progress(f"Price backtest fold {k + 1}/{folds}: {name} on {len(skus)} products")
            fc = make_price_model(name, seed, n_jobs, horizon).fit(train).forecast(train, horizon)
            scored = test.merge(fc, on=["date", "sku"], how="left").assign(fold=k, cutoff=cutoff, model=name)
            preds.append(scored)
            rows.append({"fold": k, "cutoff": cutoff.date().isoformat(), "model": name,
                         **metrics(scored["price"], scored["price_forecast"])})
    if not preds:
        return None
    p = pd.concat(preds, ignore_index=True)
    overall = {n: metrics(g["price"], g["price_forecast"]) for n, g in p.groupby("model")}
    bt = PriceBacktest(p, pd.DataFrame(rows), overall)
    bt.selected = min(overall, key=lambda n: overall[n]["mape"])
    return bt


def price_residuals(bt: PriceBacktest, model: str) -> pd.DataFrame:
    return residual_quantiles(bt.predictions[bt.predictions["model"] == model], "price", "price_forecast")
