"""ETL unit tests: extraction paging, cleaning, data-quality rules, transform."""

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from mock_odata.app import app
from tasks.clean_data import clean_all, clean_entity
from tasks.extract_odata import extract_csv, fetch_entity_set, incremental_filter, read_raw
from tasks.common import EtlSettings
from tasks.transform_data import transform
from tasks.validate_data import validate


@pytest.fixture(scope="module")
def odata():
    return TestClient(app)


def test_fetch_follows_next_links(odata):
    all_rows = fetch_entity_set(odata, "http://testserver/odata", "SalesTransactions")
    assert len(all_rows) > 5000  # more than one server page
    assert len({r["TransactionId"] for r in all_rows}) < len(all_rows)  # source contains duplicate ids


def test_incremental_filter_uses_watermark_with_overlap():
    assert incremental_filter("SalesTransactions", {}, 3) is None
    flt = incremental_filter("SalesTransactions", {"SalesTransactions": "2026-11-04"}, 3)
    assert flt == "SaleDate ge '2026-11-01'"
    assert incremental_filter("Products", {"Products": "x"}, 3) is None  # always full


def _raw(**cols):
    return pd.DataFrame(cols)


def test_clean_standardises_and_drops_exact_duplicates():
    raw = _raw(TransactionId=["T1", "T1", "T2"], Sku=[" sku-1001 ", " sku-1001 ", None],
               SaleDate=["2026-11-01", "2026-11-01", "2026-13-01"], Quantity=["3", "3", "x"],
               UnitPrice=["9.99", "9.99", "1"], OnPromo=["true", "true", None])
    df, dropped = clean_entity("sales", raw.assign(_source="odata"))
    assert dropped == 1 and len(df) == 2
    assert df.loc[0, "sku"] == "SKU-1001" and df.loc[0, "on_promo"] is True
    assert pd.isna(df.loc[1, "sale_date"]) and pd.isna(df.loc[1, "quantity"])
    assert df.loc[1, "_raw"]["SaleDate"] == "2026-13-01"  # original kept for quarantine


def _frames(sales: pd.DataFrame) -> dict:
    products = _raw(Sku=["SKU-1001"], Name=["Coffee Maker"], Category=["home"], Brand=["Casa"],
                    CurrentPrice=[79.5], SupplierLeadTimeDays=[7], MinOrderQty=[6], PackSize=[2])
    raw = {"Products": products.assign(_source="odata"), "SalesTransactions": sales.assign(_source="odata")}
    frames, _ = clean_all(raw)
    return frames


def test_validation_quarantines_bad_records_with_reasons():
    sales = _raw(TransactionId=["T1", "T2", "T3", "T4", "T5", "T1"],
                 Sku=["SKU-1001", "SKU-9999", "SKU-1001", "SKU-1001", "", "SKU-1001"],
                 SaleDate=["2026-11-01", "2026-11-01", "2026-11-01", "2099-01-01", "2026-11-01", "2026-11-01"],
                 Quantity=[3, 1, -2, 1, 1, 4], UnitPrice=[79.5, 9, 79.5, 79.5, 9, 79.5])
    res = validate(_frames(sales), known_skus=set(), max_invalid_ratio=1.0, today=date(2026, 11, 5))
    reasons = {(q["record"]["TransactionId"], q["reason"]) for q in res.quarantine}
    assert ("T2", "unknown SKU (not in product catalog)") in reasons
    assert ("T3", "quantity must be a non-negative integer") in reasons
    assert ("T4", "sale_date in the future") in reasons
    assert ("T5", "invalid or missing SKU") in reasons
    assert ("T1", "conflicting duplicate transaction_id (first record kept)") in reasons
    assert res.valid["sales"]["transaction_id"].tolist() == ["T1"]
    assert not res.critical


def test_too_many_invalid_records_is_critical():
    sales = _raw(TransactionId=["T1", "T2"], Sku=["SKU-1001", "SKU-1001"], SaleDate=["2026-11-01", "bad"],
                 Quantity=[1, 1], UnitPrice=[1.0, 1.0])
    res = validate(_frames(sales), known_skus=set(), max_invalid_ratio=0.05, today=date(2026, 11, 5))
    assert any(c.startswith("sales: 1 of 2 records invalid") for c in res.critical)


def test_transform_prefers_csv_corrections(tmp_path):
    sales = _raw(TransactionId=["T1"], Sku=["SKU-1001"], SaleDate=["2026-11-01"], Quantity=[3], UnitPrice=[79.5])
    frames = _frames(sales)
    corrected = frames["sales"].assign(quantity=5, _source="csv")
    frames["sales"] = pd.concat([frames["sales"], corrected], ignore_index=True)
    res = validate(frames, set(), max_invalid_ratio=1.0, today=date(2026, 11, 5))
    rows = transform(res.valid)
    assert rows["products"]["category"].tolist() == ["Home"]
    assert rows["sales"]["quantity"].tolist() == [3]  # duplicate id: the first (odata) record is kept by validation


def test_csv_drop_zone_is_read_and_archived(tmp_path):
    import shutil
    from pathlib import Path

    incoming = tmp_path / "incoming"
    shutil.copytree(Path(__file__).resolve().parents[2] / "data" / "sample", incoming)
    s = EtlSettings(incoming_dir=incoming)
    out = tmp_path / "run1"
    summary = extract_csv(s, out)
    assert summary["SalesTransactions"]["records"] == 4
    assert not (incoming / "sales.csv").exists() and (incoming / "processed" / "run1" / "sales.csv").exists()
    frames, _ = clean_all(read_raw(out))
    res = validate(frames, set(), max_invalid_ratio=1.0, today=date(2026, 11, 5))
    assert res.stats["sales"]["quarantined"] == 1  # the negative quantity row
    assert res.valid["inventory"]["sku"].tolist() == ["SKU-2001", "SKU-2002"]
