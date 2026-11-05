"""Forecast worker: claims queued training jobs from PostgreSQL and runs them.

    python -m ml.worker            # poll forever
    python -m ml.worker --once     # run at most one job and exit

Jobs are created by ``POST /api/forecasts/train`` (from the UI or the Airflow
``forecast_training`` DAG). Claiming uses ``FOR UPDATE SKIP LOCKED`` so several workers
could run safely; progress and readable errors are written back to the job row.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
import traceback

from sqlalchemy import create_engine, text

from .config import MlSettings
from .mlflow_tracking import TrackingUnavailable
from .pipeline import TrainingError, run_training

log = logging.getLogger("ml.worker")
_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True
    log.info("Stop requested; finishing the current job first")


def recover_orphans(engine) -> int:
    """Jobs left 'running' by a worker that died can never finish: mark them failed."""
    with engine.begin() as conn:
        return conn.execute(text("""
            UPDATE forecast_jobs SET status = 'failed', finished_at = now(),
                   error = 'The forecast worker restarted while this job was running. Start training again.'
            WHERE status = 'running'""")).rowcount


def claim(engine) -> dict | None:
    with engine.begin() as conn:
        row = conn.execute(text("""
            UPDATE forecast_jobs SET status = 'running', started_at = now(), progress = 1, stage = 'starting',
                   message = 'Worker picked up the job'
            WHERE job_id = (SELECT job_id FROM forecast_jobs WHERE status = 'queued'
                            ORDER BY requested_at FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING job_id, params, requested_by""")).mappings().first()
    return dict(row) if row else None


def make_progress(engine, job_id: str):
    def progress(stage: str, pct: int, message: str) -> None:
        log.info("[%s %3d%%] %s", stage, pct, message)
        with engine.begin() as conn:
            conn.execute(text("""UPDATE forecast_jobs SET stage = :s, progress = GREATEST(progress, :p), message = :m
                                 WHERE job_id = CAST(:j AS uuid)"""), {"s": stage, "p": min(pct, 99), "m": message[:500], "j": job_id})
    return progress


def run_job(engine, settings: MlSettings, job: dict) -> None:
    job_id = str(job["job_id"])
    log.info("Running training job %s (requested by %s)", job_id, job["requested_by"])
    try:
        result = run_training(settings, job_id, job["params"] or {}, make_progress(engine, job_id))
        with engine.begin() as conn:
            conn.execute(text("""UPDATE forecast_jobs SET status = 'succeeded', finished_at = now(), progress = 100,
                                 stage = 'done', run_id = CAST(:r AS uuid),
                                 message = :m WHERE job_id = CAST(:j AS uuid)"""),
                         {"r": result["run_id"], "j": job_id,
                          "m": f"Forecasts ready for {result['products']} products "
                               f"(demand: {result['demand_model']}, WAPE {result['demand_wape']:.3f}; "
                               f"price: {result['price_model'] or 'n/a'})"})
        log.info("Job %s succeeded: %s", job_id, result)
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded on the job
        if isinstance(exc, (TrainingError, TrackingUnavailable)):
            message = str(exc)
        else:
            message = f"Training failed: {type(exc).__name__}: {exc}"
        log.error("Job %s failed: %s\n%s", job_id, message, traceback.format_exc())
        with engine.begin() as conn:
            conn.execute(text("""UPDATE forecast_jobs SET status = 'failed', finished_at = now(), error = :e
                                 WHERE job_id = CAST(:j AS uuid)"""), {"e": message[:2000], "j": job_id})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll-seconds", type=float, default=5.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("cmdstanpy", "prophet", "mlflow", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    settings = MlSettings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    while True:
        try:
            n = recover_orphans(engine)
            break
        except Exception as exc:  # noqa: BLE001 - database may still be starting
            log.warning("Waiting for the database: %s", exc)
            time.sleep(3)
    if n:
        log.warning("Marked %d orphaned running job(s) as failed", n)
    log.info("Forecast worker ready; polling for jobs every %.0fs", args.poll_seconds)
    while not _stop:
        job = claim(engine)
        if job:
            run_job(engine, settings, job)
            if args.once:
                return
        elif args.once:
            log.info("No queued job")
            return
        else:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
