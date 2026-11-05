"""Model unit tests on simulated data (no database)."""

import numpy as np
import pandas as pd
import pytest

from mock_odata.generator import simulate
from ml.evaluate import backtest_cutoffs, metrics
from ml.predict import combine
from ml.train_demand import ProphetDemandModel, XGBoostDemandModel, eligible_skus, run_backtest
from ml.train_price import (NaivePriceModel, XGBoostPriceModel, eligible_price_skus, run_price_backtest)

FAST_XGB = {"objective": "reg:tweedie", "n_estimators": 40, "max_depth": 4, "tree_method": "hist",
            "max_cat_to_onehot": 1}
END = pd.Timestamp("2026-10-31")


@pytest.fixture(scope="module")
def sim():
    return simulate(n_products=6, seed=3)


@pytest.fixture(scope="module")
def daily(sim):
    d = sim.daily[(sim.daily["date"] <= END) & sim.daily["launched"]]
    meta = sim.products.set_index("Sku")
    return pd.DataFrame({
        "date": d["date"], "sku": d["Sku"], "product_id": d["Sku"].str[4:].astype(int),
        "category": d["Sku"].map(meta["Category"]), "units_sold": d["sales"].astype(float), "price": d["price"],
        "regular_price": d["regular_price"], "on_promo": d["on_promo"].astype(int),
        "in_stock": (d["on_hand"] > 0).astype(int),
    }).reset_index(drop=True)


@pytest.fixture(scope="module")
def prices(sim):
    d = sim.daily[(sim.daily["date"] <= END) & sim.daily["launched"]]
    publish = set(sim.products.loc[~sim.products["CatalogOnly"], "Sku"])
    d = d[d["Sku"].isin(publish)]
    meta = sim.products.set_index("Sku")
    return pd.DataFrame({"sku": d["Sku"], "category": d["Sku"].map(meta["Category"]), "date": d["date"],
                         "price": d["price"], "on_promo": d["on_promo"].astype(int)}).reset_index(drop=True)


def test_metrics_definitions():
    m = metrics([10, 0, 5], [8, 1, 5])
    assert m["mae"] == pytest.approx(1.0) and m["wape"] == pytest.approx(3 / 15)
    assert m["bias"] == pytest.approx(-1 / 15) and m["n_obs"] == 3
    cut = backtest_cutoffs(END, 30, 3)
    assert cut == sorted(cut) and cut[-1] == END - pd.Timedelta(days=30)


def test_xgboost_forecast_shape_and_intervals(daily):
    model = XGBoostDemandModel(params=FAST_XGB).fit(daily)
    model.relative_band = (-0.4, 0.5)
    fc = model.forecast(daily, 30)
    n = daily["sku"].nunique()
    assert len(fc) == 30 * n and fc["date"].min() == END + pd.Timedelta(days=1)
    assert (fc["forecast"] >= 0).all()
    assert (fc["lower"] <= fc["forecast"]).all() and (fc["upper"] >= fc["forecast"]).all()


def test_prophet_forecast_with_native_intervals(daily):
    two = daily[daily["sku"].isin(sorted(daily["sku"].unique())[:2])]
    model = ProphetDemandModel(n_jobs=1)
    fc = model.forecast(two, 14)
    assert len(fc) == 28 and set(model.models) == set(two["sku"].unique())
    assert (fc["lower"] <= fc["forecast"] + 1e-9).all() and (fc["forecast"] <= fc["upper"] + 1e-9).all()
    again = model.forecast_from_fitted(two, 14)
    assert np.allclose(again["forecast"], fc["forecast"])


def test_backtest_selects_lowest_wape_and_skips_stockouts(daily, monkeypatch):
    import ml.train_demand as td

    monkeypatch.setitem(td.XGB_PARAMS, "n_estimators", 40)
    bt = run_backtest(daily, ["xgboost"], 14, 1, 90, n_jobs=2)
    assert bt.selected == "xgboost"
    assert {"xgboost", "seasonal_naive"} <= set(bt.overall)
    in_stock = bt.predictions[(bt.predictions["model"] == "xgboost") & (bt.predictions["in_stock"] == 1)]
    assert bt.overall["xgboost"]["n_obs"] == len(in_stock)


def test_new_products_are_not_eligible(daily):
    late = daily[daily["date"] >= END - pd.Timedelta(days=30)].assign(sku="SKU-NEW")
    skus = eligible_skus(pd.concat([daily, late]), END, 90)
    first = daily.groupby("sku")["date"].min()
    expected = sorted(first[(END - first).dt.days + 1 >= 90].index)
    assert "SKU-NEW" not in skus and skus == expected


def test_price_models_and_eligibility(prices):
    skus = eligible_price_skus(prices, END, 180)
    assert skus and set(skus) <= set(prices["sku"])
    naive = NaivePriceModel().forecast(prices, 30)
    assert len(naive) == 30 * prices["sku"].nunique() and (naive["price_forecast"] > 0).all()
    model = XGBoostPriceModel(n_jobs=2, horizon=30)
    model.params["n_estimators"] = 40
    fc = model.fit(prices).forecast(prices, 30)
    assert len(fc) == len(naive) and (fc["price_forecast"] > 0).all()
    bt = run_price_backtest(prices, 30, 1, 180, n_jobs=2)
    assert bt.selected in {"naive_last_regular", "xgboost_price"}


def test_combine_marks_missing_prices_unavailable():
    demand = pd.DataFrame({"date": ["2026-11-01"] * 2, "sku": ["A", "B"], "forecast": [1.0, 2.0],
                           "lower": [0.5, 1.0], "upper": [2.0, 3.0]})
    price = pd.DataFrame({"date": ["2026-11-01"], "sku": ["A"], "price_forecast": [9.99], "price_lower": [9.0],
                          "price_upper": [10.5]})
    out = combine(demand, price).set_index("sku")
    assert out.loc["A", "price_forecast"] == 9.99 and pd.isna(out.loc["B", "price_forecast"])
