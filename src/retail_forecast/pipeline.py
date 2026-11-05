"""End-to-end training job: analytics -> backtest -> final fit -> 30-day forecast -> MLflow.

Run with ``python -m retail_forecast.pipeline``.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import xgboost
from mlflow.exceptions import MlflowException
from mlflow.models import infer_signature
from mlflow.tracking import MlflowClient

from . import plots
from .analytics import compute_analytics, save_analytics
from .config import Settings, get_settings
from .data import load_sales
from .evaluate import per_product_metrics, residual_intervals, run_backtest
from .features import FEATURES, LAGS, build_features
from .model import DEFAULT_PARAMS, DemandForecaster
from .serving import DemandModel

log = logging.getLogger("retail_forecast")
CHAMPION = "champion"


def _wait_for_tracking_server(uri: str, timeout: int = 120) -> None:
    if not uri.startswith("http"):
        return
    import urllib.request

    deadline = time.time() + timeout
    while True:
        try:
            with urllib.request.urlopen(f"{uri.rstrip('/')}/health", timeout=5) as r:
                if r.status == 200:
                    return
        except OSError:
            pass
        if time.time() > deadline:
            raise RuntimeError(f"MLflow tracking server at {uri} not reachable after {timeout}s")
        time.sleep(3)


def _promote_if_better(client: MlflowClient, name: str, version: str, wape: float) -> bool:
    """Point the 'champion' alias at this version if its backtest WAPE beats the current one."""
    try:
        current = client.get_model_version_by_alias(name, CHAMPION)
    except MlflowException:
        current = None
    if current is not None:
        cur_wape = client.get_run(current.run_id).data.metrics.get("backtest_wape")
        if cur_wape is not None and cur_wape <= wape:
            log.info("Keeping champion v%s (WAPE %.4f <= %.4f)", current.version, cur_wape, wape)
            return False
    client.set_registered_model_alias(name, CHAMPION, version)
    log.info("Promoted v%s to @%s (WAPE %.4f)", version, CHAMPION, wape)
    return True


def run(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    s.output_dir.mkdir(parents=True, exist_ok=True)

    sales = load_sales(s.data_path, synthetic_kwargs={
        "n_products": s.synthetic_products, "start": s.synthetic_start,
        "end": s.synthetic_end, "seed": s.seed,
    })
    last_date = sales["date"].max()
    log.info("Loaded %d rows, %d products, %s -> %s", len(sales), sales["product_id"].nunique(),
             sales["date"].min().date(), last_date.date())

    analytics = compute_analytics(sales)
    analytics_files = save_analytics(analytics, s.analytics_dir)

    _wait_for_tracking_server(s.tracking_uri)
    mlflow.set_tracking_uri(s.tracking_uri)
    mlflow.set_experiment(s.experiment)
    client = MlflowClient()

    run_name = f"xgb-global-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    with mlflow.start_run(run_name=run_name) as active, tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        run_id = active.info.run_id
        mlflow.set_tags({"model_family": "xgboost", "strategy": "global-recursive",
                         "data_source": str(s.data_path)})
        mlflow.log_params({
            **{f"xgb_{k}": v for k, v in DEFAULT_PARAMS.items()},
            "horizon": s.horizon, "backtest_folds": s.backtest_folds, "seed": s.seed,
            "n_products": sales["product_id"].nunique(), "n_rows": len(sales),
            "data_start": sales["date"].min().date().isoformat(), "data_end": last_date.date().isoformat(),
            "lags": ",".join(map(str, LAGS)), "n_features": len(FEATURES),
        })

        # 1) Rolling-origin backtest -------------------------------------------------
        log.info("Backtesting %d folds x %d days", s.backtest_folds, s.horizon)
        bt, fold_metrics = run_backtest(sales, lambda: DemandForecaster(seed=s.seed), s.horizon, s.backtest_folds)
        for k, m in enumerate(fold_metrics):
            mlflow.log_metrics({f"fold_{key}": v for key, v in m.items() if key != "cutoff"}, step=k)
        overall = {
            "backtest_mae": float(np.mean(np.abs(bt["forecast"] - bt["units_sold"]))),
            "backtest_rmse": float(np.sqrt(np.mean((bt["forecast"] - bt["units_sold"]) ** 2))),
            "backtest_wape": float(np.abs(bt["forecast"] - bt["units_sold"]).sum() / bt["units_sold"].sum()),
            "backtest_bias": float((bt["forecast"] - bt["units_sold"]).sum() / bt["units_sold"].sum()),
            "naive_wape": float(np.abs(bt["naive"] - bt["units_sold"]).sum() / bt["units_sold"].sum()),
        }
        overall["wape_skill_vs_naive"] = 1 - overall["backtest_wape"] / overall["naive_wape"]
        mlflow.log_metrics(overall)
        log.info("Backtest: %s", {k: round(v, 4) for k, v in overall.items()})

        ppm = per_product_metrics(bt)
        ppm.to_csv(tmp / "per_product_metrics.csv", index=False)
        bt.to_csv(tmp / "backtest_predictions.csv", index=False)
        pd.DataFrame(fold_metrics).to_csv(tmp / "fold_metrics.csv", index=False)
        plots.backtest_plot(bt, tmp / "backtest.png")

        # 2) Final model on all data + forecast --------------------------------------
        log.info("Fitting final model on full history")
        model = DemandForecaster(seed=s.seed).fit(sales)
        plan_path = s.data_path.parent / "promo_plan.csv"
        future_exog = pd.read_csv(plan_path) if plan_path.exists() else None
        fc = model.forecast(sales, s.horizon, future_exog=future_exog)
        fc = fc.merge(residual_intervals(bt), on="product_id", how="left")
        fc["lower"] = (fc["forecast"] + fc["resid_lo"].fillna(0)).clip(lower=0)
        fc["upper"] = (fc["forecast"] + fc["resid_hi"].fillna(0)).clip(lower=0)
        fc = fc.drop(columns=["resid_lo", "resid_hi"])
        for c in ("forecast", "lower", "upper"):
            fc[c] = fc[c].round(2)
        fc["run_id"] = run_id
        fc.to_csv(s.forecast_path, index=False)

        importance = model.feature_importance()
        importance.to_csv(tmp / "feature_importance.csv")
        plots.feature_importance_plot(importance, tmp / "feature_importance.png")
        plots.revenue_trend_plot(analytics["monthly_by_category"], tmp / "revenue_trend.png")
        plot_dir = tmp / "forecast_plots"
        plot_dir.mkdir()
        top_products = analytics["products"]["product_id"].head(5)
        for pid in top_products:
            plots.forecast_plot(sales, fc, pid, plot_dir / f"{pid}.png")

        mlflow.log_metrics({"forecast_total_units": float(fc["forecast"].sum())})
        mlflow.log_artifact(str(s.forecast_path), "forecast")
        mlflow.log_artifacts(str(tmp), "evaluation")
        for p in analytics_files:
            mlflow.log_artifact(str(p), "analytics")

        # 3) Log + register the model ------------------------------------------------
        sample = build_features(sales.tail(2000), model.categories).dropna(subset=["lag_28"])[FEATURES].head(5)
        preds = model.predict_frame(sample)
        sample = sample.astype({c: str for c in model.categories})  # pyfunc takes plain strings
        model_dir = tmp / "model_files"
        model_dir.mkdir()
        model.model.save_model(model_dir / "model.ubj")
        (model_dir / "metadata.json").write_text(json.dumps({"features": FEATURES, "categories": model.categories}))
        info = mlflow.pyfunc.log_model(
            name="model",
            python_model=DemandModel(),
            artifacts={"xgb_model": str(model_dir / "model.ubj"), "metadata": str(model_dir / "metadata.json")},
            code_paths=[str(Path(__file__).parent)],
            signature=infer_signature(sample, preds),
            input_example=sample,
            registered_model_name=s.registered_model,
            pip_requirements=[f"xgboost=={xgboost.__version__}", f"pandas=={pd.__version__}",
                              f"numpy=={np.__version__}", f"mlflow=={mlflow.__version__}"],
        )
        version = str(info.registered_model_version)
        promoted = _promote_if_better(client, s.registered_model, version, overall["backtest_wape"])
        mlflow.set_tag("promoted_to_champion", str(promoted).lower())

    model_info = {
        "run_id": run_id, "run_name": run_name, "experiment": s.experiment,
        "registered_model": s.registered_model, "model_version": version,
        "promoted_to_champion": promoted, "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_end": last_date.date().isoformat(), "horizon": s.horizon,
        "forecast_start": fc["date"].min().date().isoformat(),
        "forecast_end": fc["date"].max().date().isoformat(),
        "metrics": overall, "tracking_uri": s.tracking_uri,
    }
    s.model_info_path.write_text(json.dumps(model_info, indent=2))
    log.info("Wrote %s (%d rows) and %s", s.forecast_path, len(fc), s.model_info_path)
    return model_info


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("mlflow").setLevel(logging.WARNING)
    info = run()
    print(json.dumps({k: info[k] for k in ("run_id", "model_version", "promoted_to_champion", "metrics")}, indent=2))


if __name__ == "__main__":
    main()
