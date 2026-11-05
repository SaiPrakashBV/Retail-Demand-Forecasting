"""Full flow against a real PostgreSQL: migrate -> ETL from mock OData -> train -> API.

Needs TEST_DATABASE_URL (an empty database it may wipe), e.g.
    TEST_DATABASE_URL=postgresql+psycopg2://retail:retail@localhost:5433/retail_test pytest tests/integration
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL not set")]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    eng = create_engine(URL)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    env = {**os.environ, "DATABASE_URL": URL}
    subprocess.run([sys.executable, str(ROOT / "database" / "migrate.py")], check=True, env=env)
    check = subprocess.run([sys.executable, str(ROOT / "database" / "migrate.py"), "--check"], env=env)
    assert check.returncode == 0

    os.environ.update(DATABASE_URL=URL, RETAIL_DATABASE_URL=URL, TRAIN_API_KEY="test-key",
                      MLFLOW_TRACKING_URI=f"sqlite:///{tmp_path_factory.mktemp('mlflow')}/mlflow.db",
                      DEMAND_MODELS="xgboost", BACKTEST_FOLDS="1", ODATA_BASE_URL="http://testserver/odata")
    from mock_odata.app import app as odata_app
    from tasks.common import EtlSettings
    from tasks.pipeline import run_all

    settings = EtlSettings(work_dir=tmp_path_factory.mktemp("etl"), incoming_dir=tmp_path_factory.mktemp("in"))
    summary = run_all("it_run_1", settings=settings, http=TestClient(odata_app))
    assert summary["processed"] > 100_000 and summary["quarantined"] > 0

    from app.config import get_settings
    from app.database import get_engine
    get_settings.cache_clear()
    get_engine.cache_clear()
    from app.main import app
    client = TestClient(app)
    yield client, eng


def test_dashboard_and_search_before_training(stack):
    client, _ = stack
    d = client.get("/api/analytics/dashboard").json()
    assert d["has_data"] and d["kpis"]["revenue"]["value"] > 0
    r = client.get("/api/products/SKU-1002/forecast")
    assert r.status_code == 503 and r.json()["error"]["code"] == "forecast_unavailable"
    hits = client.get("/api/products", params={"q": "coffee"}).json()
    assert hits["total"] >= 1 and any("Coffee" in i["name"] for i in hits["items"])


def test_training_job_flow(stack):
    client, _ = stack
    assert client.post("/api/forecasts/train", json={}).status_code == 401
    job = client.post("/api/forecasts/train", json={"requested_by": "test"}, headers={"X-API-Key": "test-key"})
    assert job.status_code == 202
    dup = client.post("/api/forecasts/train", json={}, headers={"X-API-Key": "test-key"})
    assert dup.status_code == 409 and dup.json()["error"]["details"]["job_id"] == job.json()["job_id"]

    from ml.worker import main as worker_main
    sys.argv = ["ml.worker", "--once"]
    worker_main()
    done = client.get(f"/api/forecasts/jobs/{job.json()['job_id']}").json()
    assert done["status"] == "succeeded", done["error"]


def test_forecasts_inventory_reports_after_training(stack):
    client, _ = stack
    fc = client.get("/api/products/SKU-1001/forecast").json()
    assert len(fc["points"]) == 30 and fc["summary"]["total_demand"] > 0
    no_price = client.get("/api/products/SKU-1002/forecast").json()
    assert no_price["price_forecast"]["available"] is False and "no price history" in no_price["price_forecast"]["reason"]
    comp = client.get("/api/products/SKU-1001/forecast-comparison").json()
    assert comp["runs"][0]["run_type"] == "backtest" and comp["points"][0]["actual"] is not None
    acc = client.get("/api/analytics/accuracy").json()
    assert acc["backtest"]["demand"] and acc["backtest"]["price"]
    reorders = client.get("/api/inventory/reorders").json()
    assert reorders["total"] >= 1 and reorders["items"][0]["explanation"]
    status = client.get("/api/pipelines/status").json()
    assert status["ingestion_runs"][0]["status"] == "succeeded" and status["latest_forecast_run"]
    xlsx = client.get("/api/reports/reorder-recommendations", params={"format": "xlsx"})
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_models_match_database_schema(stack):
    _, eng = stack
    from sqlalchemy import inspect

    from app.models.tables import metadata
    insp = inspect(eng)
    for table in metadata.tables.values():
        db_cols = {c["name"] for c in insp.get_columns(table.name)}
        assert {c.name for c in table.columns} <= db_cols, table.name
