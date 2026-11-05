"""Demand forecasting models, rolling-origin backtest and per-run model selection.

Candidates (same interface: ``fit(history)`` then ``forecast(history, horizon, future_exog)``):

* ``xgboost``  one global gradient-boosted model over all products (Tweedie objective),
               lag/rolling/calendar/price/stock features, recursive 30-day forecast;
* ``prophet``  one Prophet model per product on log1p(units), weekly + yearly seasonality,
               US holidays + Black Friday, promo and price regressors; native 80% intervals.

Both are backtested on the same cutoffs; the lower volume-weighted error (WAPE) wins the run.
Stock-out days are excluded from scoring because sales on those days understate demand.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from xgboost import XGBRegressor

from .data import history_days
from .evaluate import backtest_cutoffs, metrics, residual_quantiles, seasonal_naive
from .features import DEMAND_FEATURES, MAX_LOOKBACK, TARGET, build_demand_features, category_levels

log = logging.getLogger(__name__)

XGB_PARAMS: dict = {
    "objective": "reg:tweedie", "tweedie_variance_power": 1.3, "n_estimators": 600, "learning_rate": 0.05,
    "max_depth": 7, "min_child_weight": 5, "subsample": 0.8, "colsample_bytree": 0.8, "reg_lambda": 1.0,
    "tree_method": "hist", "max_cat_to_onehot": 1,
}
PROPHET_PARAMS: dict = {
    "weekly_seasonality": True, "yearly_seasonality": "auto", "daily_seasonality": False,
    "changepoint_prior_scale": 0.05, "seasonality_prior_scale": 5.0, "interval_width": 0.8,
    "uncertainty_samples": 200,
}


def future_frame(history: pd.DataFrame, horizon: int, future_exog: pd.DataFrame | None) -> pd.DataFrame:
    """Future rows per product: planned price/promo when given, else last regular price and no promo."""
    last = history["date"].max()
    dates = pd.date_range(last + pd.Timedelta(days=1), periods=horizon, freq="D")
    latest = history.sort_values("date").groupby("sku", observed=True).tail(1)
    fut = latest[["sku", "product_id", "category", "regular_price"]].merge(pd.DataFrame({"date": dates}), how="cross")
    fut["price"] = fut["regular_price"]
    fut["on_promo"] = 0
    if future_exog is not None and len(future_exog):
        plan = future_exog[["date", "sku", "price", "on_promo"]].rename(columns={"price": "_p", "on_promo": "_promo"})
        fut = fut.merge(plan, on=["date", "sku"], how="left")
        fut["price"] = fut["_p"].fillna(fut["price"])
        fut["on_promo"] = fut["_promo"].fillna(fut["on_promo"]).astype(int)
        fut = fut.drop(columns=["_p", "_promo"])
    fut["in_stock"] = 1  # forecast unconstrained demand
    fut[TARGET] = np.nan
    return fut


# ------------------------------------------------------------------ XGBoost (global, recursive)
@dataclass
class XGBoostDemandModel:
    name: str = "xgboost"
    params: dict = field(default_factory=lambda: dict(XGB_PARAMS))
    seed: int = 42
    n_jobs: int = -1
    model: XGBRegressor | None = None
    categories: dict | None = None
    residuals: pd.DataFrame | None = None  # per-product error quantiles -> intervals
    relative_band: tuple[float, float] | None = None  # fallback for products missing from the backtest

    def fit(self, history: pd.DataFrame) -> "XGBoostDemandModel":
        self.categories = category_levels(history)
        feats = build_demand_features(history, self.categories)
        train = feats.dropna(subset=["lag_28", TARGET])
        self.model = XGBRegressor(**self.params, enable_categorical=True, random_state=self.seed, n_jobs=self.n_jobs)
        self.model.fit(train[DEMAND_FEATURES], train[TARGET])
        return self

    def forecast(self, history: pd.DataFrame, horizon: int, future_exog: pd.DataFrame | None = None) -> pd.DataFrame:
        last = history["date"].max()
        hist = history[history["date"] > last - pd.Timedelta(days=MAX_LOOKBACK + 28)]
        combined = pd.concat([hist, future_frame(hist, horizon, future_exog)], ignore_index=True)
        combined = combined.sort_values(["sku", "date"]).reset_index(drop=True)
        for day in sorted(combined.loc[combined["date"] > last, "date"].unique()):
            feats = build_demand_features(combined, self.categories)
            idx = feats.index[feats["date"] == day]
            combined.loc[idx, TARGET] = np.clip(self.model.predict(feats.loc[idx, DEMAND_FEATURES]), 0, None)
        fc = combined[combined["date"] > last][["date", "sku", TARGET]].rename(columns={TARGET: "forecast"})
        return self._intervals(fc.reset_index(drop=True))

    def _intervals(self, fc: pd.DataFrame) -> pd.DataFrame:
        if self.residuals is None and self.relative_band is None:
            return fc.assign(lower=np.nan, upper=np.nan)
        if self.residuals is not None:
            fc = fc.merge(self.residuals, on="sku", how="left")
        else:
            fc = fc.assign(resid_lo=np.nan, resid_hi=np.nan)
        if self.relative_band is not None:
            lo, hi = self.relative_band
            fc["resid_lo"] = fc["resid_lo"].fillna(fc["forecast"] * lo)
            fc["resid_hi"] = fc["resid_hi"].fillna(fc["forecast"] * hi)
        fc["lower"] = (fc["forecast"] + fc["resid_lo"]).clip(lower=0)
        fc["upper"] = (fc["forecast"] + fc["resid_hi"]).clip(lower=0)
        return fc.drop(columns=["resid_lo", "resid_hi"])

    def feature_importance(self) -> pd.Series:
        gain = self.model.get_booster().get_score(importance_type="gain")
        return pd.Series(gain, name="gain").reindex(DEMAND_FEATURES).fillna(0).sort_values(ascending=False)

    def describe(self) -> dict:
        return {f"xgb_{k}": v for k, v in self.params.items()}


# ------------------------------------------------------------------ Prophet (per product)
def _black_friday_holidays(years: range) -> pd.DataFrame:
    from .features import holiday_dates

    _, bf = holiday_dates(years.start, years.stop - 1)
    return pd.DataFrame({"holiday": "black_friday", "ds": pd.to_datetime(bf), "lower_window": -2, "upper_window": 3})


def _fit_one_prophet(sku: str, hist: pd.DataFrame, fut: pd.DataFrame, params: dict, seed: int):
    import logging as _logging

    for name in ("cmdstanpy", "prophet"):
        _logging.getLogger(name).setLevel(_logging.ERROR)
    from prophet import Prophet

    np.random.seed(seed)
    df = pd.DataFrame({"ds": hist["date"], "y": np.log1p(hist[TARGET].astype(float)),
                       "on_promo": hist["on_promo"], "price_ratio": hist["price_ratio"]})
    df.loc[hist["in_stock"].to_numpy() == 0, "y"] = np.nan  # censored demand: let Prophet ignore it
    years = range(df["ds"].dt.year.min() - 1, int(fut["date"].dt.year.max()) + 2)
    m = Prophet(**params, holidays=_black_friday_holidays(years))
    m.add_country_holidays("US")
    m.add_regressor("on_promo", mode="additive")
    m.add_regressor("price_ratio", mode="additive")
    m.fit(df)
    # Duan smearing: exp(mean of log) is the median; scale back to the mean using in-sample residuals.
    samples, m.uncertainty_samples = m.uncertainty_samples, 0
    fitted = m.predict(df.drop(columns="y"))["yhat"].to_numpy()
    m.uncertainty_samples = samples
    resid = df["y"].to_numpy() - fitted
    smear = float(np.nanmean(np.exp(resid))) if np.isfinite(resid).any() else 1.0
    pred = m.predict(pd.DataFrame({"ds": fut["date"], "on_promo": fut["on_promo"], "price_ratio": fut["price_ratio"]}))
    back = lambda v: np.clip(np.exp(v.to_numpy()) * smear - 1, 0, None)  # noqa: E731
    out = pd.DataFrame({"date": fut["date"].to_numpy(), "sku": sku, "forecast": back(pred["yhat"]),
                        "lower": back(pred["yhat_lower"]), "upper": back(pred["yhat_upper"])})
    m.smearing_factor = smear
    return sku, m, out


@dataclass
class ProphetDemandModel:
    name: str = "prophet"
    params: dict = field(default_factory=lambda: dict(PROPHET_PARAMS))
    seed: int = 42
    n_jobs: int = 4
    models: dict = field(default_factory=dict)

    def fit(self, history: pd.DataFrame) -> "ProphetDemandModel":
        return self  # Prophet is fitted per product inside forecast(), in parallel

    @staticmethod
    def _with_ratio(df: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
        ref = history.groupby("sku", observed=True)["price"].apply(lambda s: s.tail(28).max())
        out = df.copy()
        out["price_ratio"] = out["price"] / out["sku"].map(ref).astype(float)
        return out

    def forecast(self, history: pd.DataFrame, horizon: int, future_exog: pd.DataFrame | None = None) -> pd.DataFrame:
        hist = history.sort_values(["sku", "date"]).copy()
        ref = hist.groupby("sku", observed=True)["price"].transform(lambda s: s.rolling(28, min_periods=1).max())
        hist["price_ratio"] = hist["price"] / ref
        fut = self._with_ratio(future_frame(hist, horizon, future_exog), hist)
        jobs = [(sku, g, fut[fut["sku"] == sku]) for sku, g in hist.groupby("sku", observed=True)]
        results = Parallel(n_jobs=self.n_jobs, prefer="processes")(
            delayed(_fit_one_prophet)(str(sku), g, f, self.params, self.seed) for sku, g, f in jobs)
        self.models = {sku: m for sku, m, _ in results}
        return pd.concat([r[2] for r in results], ignore_index=True)

    def forecast_from_fitted(self, history: pd.DataFrame, horizon: int) -> pd.DataFrame:
        """Predict with the models fitted by the last ``forecast()`` call (no refitting)."""
        hist = history.sort_values(["sku", "date"]).copy()
        fut = self._with_ratio(future_frame(hist, horizon, None), hist)
        out = []
        for sku, m in self.models.items():
            f = fut[fut["sku"].astype(str) == sku]
            pred = m.predict(pd.DataFrame({"ds": f["date"], "on_promo": f["on_promo"], "price_ratio": f["price_ratio"]}))
            smear = getattr(m, "smearing_factor", 1.0)
            back = lambda v: np.clip(np.exp(v.to_numpy()) * smear - 1, 0, None)  # noqa: E731
            out.append(pd.DataFrame({"date": f["date"].to_numpy(), "sku": sku, "forecast": back(pred["yhat"]),
                                     "lower": back(pred["yhat_lower"]), "upper": back(pred["yhat_upper"])}))
        return pd.concat(out, ignore_index=True)

    def describe(self) -> dict:
        return {f"prophet_{k}": v for k, v in self.params.items()} | {"prophet_transform": "log1p",
                                                                     "prophet_regressors": "on_promo,price_ratio"}


FACTORIES: dict[str, Callable[..., object]] = {"xgboost": XGBoostDemandModel, "prophet": ProphetDemandModel}


def make_model(name: str, seed: int, n_jobs: int):
    if name not in FACTORIES:
        raise ValueError(f"Unknown demand model {name!r}; choose from {sorted(FACTORIES)}")
    return FACTORIES[name](seed=seed, n_jobs=n_jobs)


# ------------------------------------------------------------------ backtest + selection
def eligible_skus(daily: pd.DataFrame, at: pd.Timestamp, min_days: int) -> list[str]:
    h = history_days(daily, at)
    return sorted(h[h >= min_days].index.astype(str))


@dataclass
class DemandBacktest:
    predictions: pd.DataFrame          # fold, cutoff, date, sku, category, actual, in_stock, model, forecast, lower, upper
    fold_metrics: pd.DataFrame         # fold, cutoff, model, mae, rmse, wape, bias, ...
    overall: dict[str, dict]           # model -> metrics over all folds (in-stock days)
    selected: str = ""


def run_backtest(daily: pd.DataFrame, candidates: list[str], horizon: int, folds: int, min_history: int,
                 seed: int = 42, n_jobs: int = 4, progress: Callable[[str], None] | None = None) -> DemandBacktest:
    last = daily["date"].max()
    preds, fold_rows = [], []
    for k, cutoff in enumerate(backtest_cutoffs(last, horizon, folds)):
        train = daily[daily["date"] <= cutoff]
        skus = eligible_skus(train, cutoff, min_history)
        train = train[train["sku"].isin(skus)]
        test = daily[(daily["date"] > cutoff) & (daily["date"] <= cutoff + pd.Timedelta(days=horizon))
                     & daily["sku"].isin(skus)]
        exog = test[["date", "sku", "price", "on_promo"]]
        base = test[["date", "sku", "category", TARGET, "in_stock"]].rename(columns={TARGET: "actual"})
        outputs = {"seasonal_naive": seasonal_naive(train, horizon).assign(lower=np.nan, upper=np.nan)}
        for name in candidates:
            if progress:
                progress(f"Backtest fold {k + 1}/{folds}: {name} on {len(skus)} products")
            model = make_model(name, seed, n_jobs).fit(train)
            outputs[name] = model.forecast(train, horizon, exog)
        for name, fc in outputs.items():
            fc = fc.assign(sku=fc["sku"].astype(str))
            scored = base.assign(sku=base["sku"].astype(str)).merge(fc, on=["date", "sku"], how="left")
            scored = scored.assign(fold=k, cutoff=cutoff, model=name)
            preds.append(scored)
            ok = scored[scored["in_stock"] == 1]
            fold_rows.append({"fold": k, "cutoff": cutoff.date().isoformat(), "model": name,
                              **metrics(ok["actual"], ok["forecast"].fillna(0))})
    predictions = pd.concat(preds, ignore_index=True)
    overall = {}
    for name, g in predictions[predictions["in_stock"] == 1].groupby("model"):
        overall[name] = metrics(g["actual"], g["forecast"].fillna(0))
    bt = DemandBacktest(predictions, pd.DataFrame(fold_rows), overall)
    bt.selected = min(candidates, key=lambda n: overall[n]["wape"])
    return bt


def relative_band(bt: DemandBacktest, model: str, lo: float = 0.1, hi: float = 0.9) -> tuple[float, float]:
    """Error quantiles relative to the forecast, pooled over all products."""
    p = bt.predictions[(bt.predictions["model"] == model) & (bt.predictions["in_stock"] == 1)]
    p = p[p["forecast"] > 0.5]
    rel = (p["actual"] - p["forecast"]) / p["forecast"]
    return (float(rel.quantile(lo)), float(rel.quantile(hi))) if len(rel) else (-0.5, 0.5)


def residuals_for(bt: DemandBacktest, model: str) -> pd.DataFrame:
    p = bt.predictions[(bt.predictions["model"] == model) & (bt.predictions["in_stock"] == 1)]
    return residual_quantiles(p, "actual", "forecast")
