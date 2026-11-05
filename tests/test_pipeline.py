import json

import numpy as np
import pandas as pd
import pytest

from retail_forecast.analytics import compute_analytics
from retail_forecast.data import generate_synthetic_sales, validate_and_clean
from retail_forecast.evaluate import backtest_cutoffs, metrics, seasonal_naive
from retail_forecast.features import FEATURES, build_features
from retail_forecast.model import DemandForecaster

FAST_PARAMS = {"objective": "reg:tweedie", "n_estimators": 40, "max_depth": 4, "tree_method": "hist"}


@pytest.fixture(scope="module")
def sales():
    return validate_and_clean(generate_synthetic_sales(n_products=6, start="2025-01-01", end="2026-03-31", seed=1))


def test_validate_fills_gaps_and_duplicates():
    raw = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-01", "2026-01-03"],
        "product_id": ["A", "A", "A"], "category": ["X"] * 3,
        "price": [2.0, 2.0, 2.5], "on_promo": [0, 0, 1], "units_sold": [3, 2, 7],
    })
    out = validate_and_clean(raw)
    assert out["date"].tolist() == list(pd.date_range("2026-01-01", "2026-01-03"))
    assert out["units_sold"].tolist() == [5, 0, 7]
    assert out["price"].tolist() == [2.0, 2.0, 2.5]


def test_validate_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        validate_and_clean(pd.DataFrame({"date": ["2026-01-01"], "units_sold": [1]}))


def test_lag_features_do_not_leak_target(sales):
    feats = build_features(sales)
    p = feats[feats["product_id"] == "P001"].reset_index(drop=True)
    assert p.loc[10, "lag_1"] == p.loc[9, "units_sold"]
    assert p.loc[30, "lag_7"] == p.loc[23, "units_sold"]
    assert p.loc[10, "roll_mean_7"] == pytest.approx(p.loc[3:9, "units_sold"].mean())
    assert set(FEATURES) <= set(feats.columns)


def test_forecast_shape_and_values(sales):
    model = DemandForecaster(params=FAST_PARAMS).fit(sales)
    fc = model.forecast(sales, horizon=30)
    assert len(fc) == 30 * sales["product_id"].nunique()
    assert fc["date"].min() == sales["date"].max() + pd.Timedelta(days=1)
    assert fc["forecast"].notna().all() and (fc["forecast"] >= 0).all()
    assert (fc["on_promo"] == 0).all()


def test_forecast_uses_promo_plan(sales):
    model = DemandForecaster(params=FAST_PARAMS).fit(sales)
    start = sales["date"].max() + pd.Timedelta(days=1)
    plan = pd.DataFrame({"date": [start], "product_id": ["P001"], "price": [0.5], "on_promo": [1]})
    fc = model.forecast(sales, horizon=7, future_exog=plan)
    row = fc[(fc["product_id"] == "P001") & (fc["date"] == start)].iloc[0]
    assert row["on_promo"] == 1 and row["price"] == 0.5


def test_metrics_and_naive(sales):
    m = metrics(np.array([10, 0, 5]), np.array([8, 1, 5]))
    assert m["mae"] == pytest.approx(1.0)
    assert m["wape"] == pytest.approx(3 / 15)
    naive = seasonal_naive(sales, 14)
    assert len(naive) == 14 * sales["product_id"].nunique()
    cutoffs = backtest_cutoffs(pd.Timestamp("2026-03-31"), 30, 3)
    assert cutoffs == sorted(cutoffs) and cutoffs[-1] == pd.Timestamp("2026-03-01")


def test_analytics(sales):
    a = compute_analytics(sales)
    assert a["summary"]["n_products"] == 6
    assert set(a["products"]["abc_class"]) <= {"A", "B", "C"}
    assert a["categories"]["revenue_share"].sum() == pytest.approx(1.0)
    json.dumps(a["summary"])  # must be serialisable


def test_api_serves_outputs(tmp_path, monkeypatch, sales):
    from retail_forecast.analytics import save_analytics

    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_PATH", str(tmp_path / "sales.csv"))
    sales.to_csv(tmp_path / "sales.csv", index=False)
    save_analytics(compute_analytics(sales), tmp_path / "analytics")
    fc = DemandForecaster(params=FAST_PARAMS).fit(sales).forecast(sales, 30)
    fc = fc.assign(lower=fc["forecast"] * 0.8, upper=fc["forecast"] * 1.2, run_id="test")
    fc.to_csv(tmp_path / "forecast.csv", index=False)
    (tmp_path / "model_info.json").write_text(json.dumps({"run_id": "test"}))

    import importlib

    import retail_forecast.api as api
    importlib.reload(api)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    assert client.get("/health").json()["forecast_ready"] is True
    r = client.get("/forecast/P001")
    assert r.status_code == 200 and len(r.json()["points"]) == 30
    assert client.get("/forecast/NOPE").status_code == 404
    assert len(client.get("/forecast").json()) == 6
    assert client.get("/analytics/summary").json()["n_products"] == 6
    assert client.get("/model").json()["run_id"] == "test"
    hist = client.get("/history/P001?days=14").json()
    assert len(hist) == 14 and {"date", "units_sold"} <= set(hist[0])
    assert client.get("/history/NOPE").status_code == 404
