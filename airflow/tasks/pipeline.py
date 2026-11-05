"""ETL steps as plain functions (used by the Airflow DAG and runnable without Airflow).

    python -m tasks.pipeline            # run the whole ETL once, locally

Each step reads its inputs from files written by the previous step, so Airflow only
passes small path dictionaries between tasks through XCom.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

from .clean_data import clean_all
from .common import EtlSettings, engine, load_frames, run_dir, save_frames
from .extract_odata import extract_csv, extract_odata, read_raw
from .load_postgres import load
from .transform_data import transform
from .update_data_status import finish_run, merge_details, record_quarantine, start_run
from .validate_data import CriticalDataQualityError, validate

log = logging.getLogger(__name__)


def step_start(pipeline_id: str, dag_id: str, settings: EtlSettings | None = None) -> str:
    s = settings or EtlSettings()
    start_run(engine(s), pipeline_id, dag_id, source=f"odata:{s.odata_url}")
    return str(run_dir(s, pipeline_id))


def step_extract(work: str, pipeline_id: str, settings: EtlSettings | None = None, http=None) -> dict:
    s = settings or EtlSettings()
    out = Path(work)
    summary = {"odata": extract_odata(s, out, http=http), "csv": extract_csv(s, out)}
    merge_details(engine(s), pipeline_id, {"extract": summary})
    return summary


def step_clean(work: str, pipeline_id: str, settings: EtlSettings | None = None) -> dict[str, str]:
    s = settings or EtlSettings()
    frames, dupes = clean_all(read_raw(Path(work)))
    merge_details(engine(s), pipeline_id, {"clean": {"exact_duplicates_dropped": dupes}})
    return save_frames(frames, Path(work) / "clean")


def step_validate(work: str, pipeline_id: str, clean_paths: dict[str, str],
                  extract_summary: dict, settings: EtlSettings | None = None) -> dict[str, str]:
    s = settings or EtlSettings()
    eng = engine(s)
    with eng.connect() as conn:
        known = {r[0] for r in conn.execute(text("SELECT sku FROM products"))}
    result = validate(load_frames(clean_paths), known, s.max_invalid_ratio,
                      full_product_load=extract_summary["odata"]["Products"]["mode"] == "full")
    record_quarantine(eng, pipeline_id, result.quarantine)
    merge_details(eng, pipeline_id, {"validation": result.stats, "critical": result.critical})
    if result.critical:
        raise CriticalDataQualityError("Data-quality check failed, nothing was loaded: " + "; ".join(result.critical))
    return save_frames(result.valid, Path(work) / "valid")


def step_transform(work: str, valid_paths: dict[str, str]) -> dict[str, str]:
    return save_frames(transform(load_frames(valid_paths)), Path(work) / "transformed")


def step_load(pipeline_id: str, rows_paths: dict[str, str], settings: EtlSettings | None = None) -> dict:
    s = settings or EtlSettings()
    counts = load(engine(s), load_frames(rows_paths))
    merge_details(engine(s), pipeline_id, {"loaded": counts})
    return counts


def step_finish(pipeline_id: str, settings: EtlSettings | None = None) -> dict:
    """Mark the run succeeded, summing counts from the details recorded by earlier steps."""
    s = settings or EtlSettings()
    eng = engine(s)
    with eng.connect() as conn:
        details = conn.execute(text("SELECT details FROM data_pipeline_runs WHERE pipeline_id = :p"),
                               {"p": pipeline_id}).scalar_one()
    extracted = sum(v["records"] for src in details.get("extract", {}).values() for v in src.values())
    processed = sum(details.get("loaded", {}).values())
    quarantined = sum(v["quarantined"] for v in details.get("validation", {}).values())
    finish_run(eng, pipeline_id, "succeeded", extracted=extracted, processed=processed, quarantined=quarantined)
    return {"extracted": extracted, "processed": processed, "quarantined": quarantined}


def step_fail(pipeline_id: str, error: str, settings: EtlSettings | None = None) -> None:
    s = settings or EtlSettings()
    eng = engine(s)
    with eng.connect() as conn:
        q = conn.execute(text("SELECT count(*) FROM quarantine_records WHERE pipeline_id = :p"),
                         {"p": pipeline_id}).scalar_one()
    finish_run(eng, pipeline_id, "failed", quarantined=q, error=error[:2000])


def run_all(pipeline_id: str | None = None, settings: EtlSettings | None = None, http=None) -> dict:
    s = settings or EtlSettings()
    pid = pipeline_id or f"manual__{uuid.uuid4().hex[:12]}"
    work = step_start(pid, "retail_etl", s)
    try:
        summary = step_extract(work, pid, s, http=http)
        clean = step_clean(work, pid, s)
        valid = step_validate(work, pid, clean, summary, s)
        rows = step_transform(work, valid)
        step_load(pid, rows, s)
        return step_finish(pid, s)
    except Exception as exc:
        step_fail(pid, f"{type(exc).__name__}: {exc}", s)
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run_all(sys.argv[1] if len(sys.argv) > 1 else None), indent=2))
