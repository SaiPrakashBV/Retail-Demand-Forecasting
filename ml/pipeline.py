"""Training job: backtest candidates, select, forecast 30 days, track in MLflow, store, plan reorders.

    python -m ml.pipeline      # run one training job locally (no queue)
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, time
from pathlib import Path

import mlflow
from sqlalchemy import create_engine, text

from . import forecast_store, model_registry
from . import mlflow_tracking as track
from .config import MlSettings
from .data import load_daily, load_prices
from .evaluate import per_product
from .predict import backtest_frames, combine, production_demand, production_price
from .train_demand import eligible_skus, run_backtest
from .train_price import run_price_backtest

log = logging.getLogger(__name__)
Progress = Callable[[str, int, str], None]


class TrainingError(RuntimeError):
    """A failure with a message meant for users (shown in the UI and the job record)."""


def _noop(stage: str, pct: int, msg: str) -> None:
    log.info("[%3d%%] %s: %s", pct, stage, msg)


def _reorders(conn, run_id: str) -> int:
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.services.reorder_service import generate_for_run

    return generate_for_run(conn, run_id)


def run_training(settings: MlSettings | None = None, job_id: str | None = None, params: dict | None = None,
                 progress: Progress = _noop) -> dict:
    s = settings or MlSettings()
    params = params or {}
    horizon = int(params.get("horizon_days", s.horizon))
    folds = int(params.get("backtest_folds", s.backtest_folds))
    job_id = job_id or str(uuid.uuid4())
    engine = create_engine(s.database_url, pool_pre_ping=True)

    progress("loading", 3, "Loading sales, prices and inventory history")
    daily, prices = load_daily(engine), load_prices(engine)
    if daily.empty:
        raise TrainingError("No sales data in the database yet. Run the retail_etl pipeline first.")
    last = daily["date"].max()
    skus = eligible_skus(daily, last, s.min_demand_history_days)
    if not skus:
        raise TrainingError(f"No product has {s.min_demand_history_days}+ days of sales history yet.")
    skipped = sorted(set(daily["sku"].astype(str)) - set(skus))

    # 1) Demand candidates ------------------------------------------------------------
    stage = iter(range(8, 45, max(1, 36 // max(1, folds * len(s.demand_candidates)))))
    demand_bt = run_backtest(daily, list(s.demand_candidates), horizon, folds, s.min_demand_history_days,
                             s.seed, s.n_jobs, progress=lambda m: progress("demand_backtest", next(stage, 44), m))
    progress("demand_backtest", 45, f"Selected demand model: {demand_bt.selected} "
             f"(WAPE {demand_bt.overall[demand_bt.selected]['wape']:.3f})")

    # 2) Price candidates -------------------------------------------------------------
    progress("price_backtest", 48, "Backtesting price models")
    price_bt = run_price_backtest(prices, horizon, folds, s.min_price_history_days, s.seed, s.n_jobs)
    price_model_name = price_bt.selected if price_bt else None

    # 3) Final fits + 30-day forecasts --------------------------------------------------
    progress("forecasting", 60, f"Fitting {demand_bt.selected} on full history for {len(skus)} products")
    demand_model, demand_fc = production_demand(daily, skus, demand_bt.selected, demand_bt, horizon, s.seed, s.n_jobs)
    progress("forecasting", 70, "Forecasting prices")
    price_model, price_fc, price_skus = production_price(prices, price_model_name or "naive_last_regular", price_bt,
                                                         horizon, s.min_price_history_days, s.seed, s.n_jobs)
    frame = combine(demand_fc, price_fc)
    generated_at = datetime.now(UTC)

    # 4) MLflow ---------------------------------------------------------------------------
    progress("tracking", 76, "Logging runs, metrics and models to MLflow")
    track.setup(s.tracking_uri)
    tags = {"job_id": job_id, "data_end": last.date().isoformat()}
    demand_pp = {m: per_product(g[g["in_stock"] == 1], "actual", "forecast")
                 for m, g in demand_bt.predictions.groupby("model")}
    with track.parent_run(s.demand_experiment, f"demand-{last:%Y%m%d}-{job_id[:8]}", tags) as parent:
        mlflow.log_params({"horizon": horizon, "backtest_folds": folds, "candidates": ",".join(s.demand_candidates),
                           "selected_model": demand_bt.selected, "products": len(skus), "data_end": last.date(),
                           "min_history_days": s.min_demand_history_days})
        for name in s.demand_candidates:
            track.log_candidate(name, _describe(name, demand_model, s), demand_bt.overall[name],
                                demand_bt.fold_metrics, demand_pp[name], name == demand_bt.selected)
        sel = demand_bt.overall[demand_bt.selected]
        naive = demand_bt.overall["seasonal_naive"]
        mlflow.log_metrics({f"backtest_{k}": v for k, v in sel.items()} | {
            "naive_wape": naive["wape"], "wape_skill_vs_naive": 1 - sel["wape"] / naive["wape"],
            **{f"{n}_wape": demand_bt.overall[n]["wape"] for n in s.demand_candidates}})
        track.log_figure(track.backtest_chart(demand_bt.predictions, "actual", "forecast",
                                              [*s.demand_candidates, "seasonal_naive"],
                                              "Backtest: total daily units, all products", "Units"),
                         "evaluation/backtest.png")
        if hasattr(demand_model, "feature_importance"):
            track.log_figure(track.importance_chart(demand_model.feature_importance()),
                             "evaluation/feature_importance.png")
        track.log_frame(demand_bt.fold_metrics, "evaluation/fold_metrics.csv")
        track.log_frame(frame, "forecast/forecast.csv")
        track.log_json({"skipped_insufficient_history": skipped}, "forecast/eligibility.json")
        _, demand_version = track.log_forecaster("demand", demand_model, daily[daily["sku"].isin(skus)],
                                                 horizon, s.demand_model_name, skus)
        model_registry.promote(s.demand_model_name, demand_version, demand_bt.selected,
                               {k: v for k, v in sel.items() if k != "n_obs"}, job_id)
        demand_run_id = parent.info.run_id

    price_run_id = price_version = None
    price_pp = {}
    if price_bt is not None and price_model is not None:
        price_pp = {m: per_product(g, "price", "price_forecast") for m, g in price_bt.predictions.groupby("model")}
        with track.parent_run(s.price_experiment, f"price-{last:%Y%m%d}-{job_id[:8]}", tags) as parent:
            mlflow.log_params({"horizon": horizon, "selected_model": price_model_name, "products": len(price_skus),
                               "min_price_history_days": s.min_price_history_days})
            for name in price_bt.overall:
                track.log_candidate(name, getattr(price_model, "describe", dict)() if name == price_model_name else {},
                                    price_bt.overall[name], price_bt.fold_metrics, price_pp[name],
                                    name == price_model_name)
            psel = price_bt.overall[price_model_name]
            mlflow.log_metrics({f"backtest_{k}": v for k, v in psel.items()})
            track.log_figure(track.backtest_chart(price_bt.predictions, "price", "price_forecast",
                                                  list(price_bt.overall), "Backtest: average selling price",
                                                  "Price", agg="mean"), "evaluation/price_backtest.png")
            _, price_version = track.log_forecaster("price", price_model, prices[prices["sku"].isin(price_skus)],
                                                    horizon, s.price_model_name, price_skus)
            model_registry.promote(s.price_model_name, price_version, price_model_name,
                                   {k: v for k, v in psel.items() if k != "n_obs"}, job_id)
            price_run_id = parent.info.run_id

    # 5) Store in PostgreSQL --------------------------------------------------------------
    progress("storing", 88, "Saving forecasts, accuracy and backtest predictions")
    with engine.begin() as conn:
        sku_to_id = dict(conn.execute(text("SELECT sku, product_id FROM products")).fetchall())
        common = dict(job_id=job_id, model_name=demand_bt.selected, price_model_name=price_model_name,
                      demand_model_version=demand_version, price_model_version=price_version,
                      mlflow_run_id=demand_run_id, price_mlflow_run_id=price_run_id,
                      data_start=daily["date"].min().date(), horizon=horizon)
        metrics = {"demand": {k: v for k, v in demand_bt.overall.items()},
                   "price": price_bt.overall if price_bt else None, "selected_demand_model": demand_bt.selected,
                   "selected_price_model": price_model_name, "products_without_demand_forecast": skipped,
                   "price_forecast_products": len(price_skus)}
        run_id = forecast_store.create_run(conn, run_type="production", cutoff=last.date(),
                                           products=len(skus), metrics=metrics, **common)
        forecast_store.insert_forecasts(conn, run_id, frame, sku_to_id, generated_at, demand_run_id)
        forecast_store.insert_accuracy(conn, run_id, "demand", demand_pp, demand_bt.selected, sku_to_id)
        if price_pp:
            forecast_store.insert_accuracy(conn, run_id, "price", price_pp, price_model_name, sku_to_id)

        for cutoff, bt_frame in backtest_frames(demand_bt, price_bt).items():
            fold = demand_bt.fold_metrics[(demand_bt.fold_metrics["cutoff"] == cutoff.date().isoformat())
                                          & (demand_bt.fold_metrics["model"] == demand_bt.selected)]
            bt_run = forecast_store.create_run(conn, run_type="backtest", cutoff=cutoff.date(),
                                               products=bt_frame["sku"].nunique(),
                                               metrics={"demand": fold.drop(columns=["model"]).to_dict("records")},
                                               **common)
            as_of = datetime.combine(cutoff.date(), time(23, 59), tzinfo=UTC)
            forecast_store.insert_forecasts(conn, bt_run, bt_frame, sku_to_id, as_of, demand_run_id)
        pruned = forecast_store.prune_backtest_runs(conn, job_id)

        progress("reorders", 95, "Calculating reorder recommendations")
        recs = _reorders(conn, run_id)

    result = {"run_id": run_id, "demand_model": demand_bt.selected, "price_model": price_model_name,
              "demand_wape": demand_bt.overall[demand_bt.selected]["wape"],
              "naive_wape": demand_bt.overall["seasonal_naive"]["wape"],
              "products": len(skus), "price_products": len(price_skus), "recommendations": recs,
              "demand_model_version": demand_version, "price_model_version": price_version,
              "pruned_backtest_runs": pruned}
    progress("done", 100, f"Forecasts ready: {len(skus)} products, demand model {demand_bt.selected}, "
                          f"price model {price_model_name or 'n/a'}")
    return result


def _describe(name: str, fitted, s: MlSettings) -> dict:
    from .train_demand import make_model

    model = fitted if getattr(fitted, "name", None) == name else make_model(name, s.seed, s.n_jobs)
    return model.describe()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("cmdstanpy", "prophet", "mlflow"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    print(run_training())
