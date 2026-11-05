"""Global XGBoost demand model with recursive multi-step forecasting."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from .features import FEATURES, MAX_LOOKBACK, TARGET, build_features, category_levels

DEFAULT_PARAMS: dict = {
    "objective": "reg:tweedie",  # count-like, right-skewed demand with zeros
    "tweedie_variance_power": 1.3,
    "n_estimators": 700,
    "learning_rate": 0.04,
    "max_depth": 7,
    "min_child_weight": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "tree_method": "hist",
    "max_cat_to_onehot": 1,
}


@dataclass
class DemandForecaster:
    params: dict = field(default_factory=lambda: dict(DEFAULT_PARAMS))
    seed: int = 42
    model: XGBRegressor | None = None
    categories: dict[str, list[str]] | None = None

    def fit(self, sales: pd.DataFrame) -> "DemandForecaster":
        self.categories = category_levels(sales)
        feats = build_features(sales, self.categories)
        train = feats.dropna(subset=["lag_28", TARGET])
        self.model = XGBRegressor(**self.params, enable_categorical=True, random_state=self.seed, n_jobs=-1)
        self.model.fit(train[FEATURES], train[TARGET])
        return self

    def predict_frame(self, feature_frame: pd.DataFrame) -> np.ndarray:
        assert self.model is not None, "call fit() first"
        return np.clip(self.model.predict(feature_frame[FEATURES]), 0, None)

    def forecast(self, history: pd.DataFrame, horizon: int, future_exog: pd.DataFrame | None = None) -> pd.DataFrame:
        """Forecast ``horizon`` days past the end of ``history`` for every product.

        Each day is predicted from features built on actuals plus the predictions for
        earlier forecast days (recursive strategy). Future price/promo come from
        ``future_exog`` (columns date, product_id, price, on_promo) when given;
        otherwise the latest non-promo price is carried forward with no promotions.
        """
        last_date = history["date"].max()
        hist = history[history["date"] > last_date - pd.Timedelta(days=MAX_LOOKBACK + 28)]
        future = _future_frame(hist, horizon, future_exog)

        combined = pd.concat([hist, future], ignore_index=True)
        combined = combined.sort_values(["product_id", "date"]).reset_index(drop=True)
        for day in sorted(future["date"].unique()):
            feats = build_features(combined, self.categories)
            idx = feats.index[feats["date"] == day]
            combined.loc[idx, TARGET] = self.predict_frame(feats.loc[idx])

        fc = combined[combined["date"] > last_date][["date", "product_id", "category", "price", "on_promo", TARGET]]
        return fc.rename(columns={TARGET: "forecast"}).reset_index(drop=True)

    def feature_importance(self) -> pd.Series:
        assert self.model is not None
        booster = self.model.get_booster()
        gain = booster.get_score(importance_type="gain")
        return pd.Series(gain, name="gain").reindex(FEATURES).fillna(0).sort_values(ascending=False)


def _future_frame(hist: pd.DataFrame, horizon: int, future_exog: pd.DataFrame | None) -> pd.DataFrame:
    last_date = hist["date"].max()
    dates = pd.date_range(last_date + pd.Timedelta(days=1), periods=horizon, freq="D")
    latest = hist.sort_values("date").groupby("product_id").tail(1)[["product_id", "category"]]
    non_promo = hist[hist["on_promo"] == 0].sort_values("date").groupby("product_id")["price"].last()
    last_any = hist.sort_values("date").groupby("product_id")["price"].last()
    regular_price = non_promo.reindex(last_any.index).fillna(last_any)

    fut = latest.merge(pd.DataFrame({"date": dates}), how="cross")
    fut["price"] = fut["product_id"].map(regular_price)
    fut["on_promo"] = 0
    if future_exog is not None and len(future_exog):
        exog = future_exog[["date", "product_id", "price", "on_promo"]].copy()
        exog["date"] = pd.to_datetime(exog["date"])
        fut = fut.merge(exog, on=["date", "product_id"], how="left", suffixes=("", "_plan"))
        fut["price"] = fut["price_plan"].fillna(fut["price"])
        fut["on_promo"] = fut["on_promo_plan"].fillna(fut["on_promo"]).astype(int)
        fut = fut.drop(columns=["price_plan", "on_promo_plan"])
    fut[TARGET] = np.nan
    return fut
