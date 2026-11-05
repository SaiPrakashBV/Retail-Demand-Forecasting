"""Data-quality rules. Invalid records are quarantined; critical failures stop the run."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

SKU_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,31}$")


class CriticalDataQualityError(RuntimeError):
    """Raised when a batch is too broken to load; downstream tasks must not run."""


@dataclass
class ValidationResult:
    valid: dict[str, pd.DataFrame]
    quarantine: list[dict] = field(default_factory=list)
    stats: dict[str, dict] = field(default_factory=dict)
    critical: list[str] = field(default_factory=list)


def _rule(df: pd.DataFrame, bad: pd.Series, reason: str, reasons: pd.Series) -> None:
    hit = bad.fillna(True) & reasons.isna()
    reasons[hit] = reason


def _valid_sku(s: pd.Series) -> pd.Series:
    return s.map(lambda v: isinstance(v, str) and bool(SKU_RE.match(v))).astype(bool)


def _int_like(s: pd.Series) -> pd.Series:
    return s.notna() & np.isclose(s.fillna(0) % 1, 0)


def validate(frames: dict[str, pd.DataFrame], known_skus: set[str], max_invalid_ratio: float = 0.05,
             today: date | None = None, full_product_load: bool = True) -> ValidationResult:
    today = today or date.today()
    latest_ok = today + timedelta(days=1)
    result = ValidationResult(valid={})

    # --- products first: they define which SKUs other entities may reference
    p = frames["products"]
    r = pd.Series(None, index=p.index, dtype=object)
    _rule(p, ~_valid_sku(p["sku"]), "invalid or missing SKU", r)
    _rule(p, p["name"].isna(), "missing product name", r)
    _rule(p, p["category"].isna(), "missing category", r)
    _rule(p, ~(p["current_price"] > 0), "current_price must be > 0", r)
    for c in ("supplier_lead_time_days", "min_order_qty", "pack_size"):
        _rule(p, ~_int_like(p[c]) | (p[c] < (0 if c == "supplier_lead_time_days" else 1)), f"invalid {c}", r)
    _rule(p, p.duplicated("sku", keep="last"), "duplicate SKU in batch (later record kept)", r)
    _collect(result, "products", p, r)
    skus = known_skus | set(result.valid["products"]["sku"])

    checks = {
        "sales": [
            (lambda d: d["transaction_id"].isna(), "missing transaction_id"),
            (lambda d: ~_valid_sku(d["sku"]), "invalid or missing SKU"),
            (lambda d: ~d["sku"].isin(skus), "unknown SKU (not in product catalog)"),
            (lambda d: d["sale_date"].isna(), "invalid sale_date"),
            (lambda d: d["sale_date"].map(lambda x: x is not None and not pd.isna(x) and x > latest_ok),
             "sale_date in the future"),
            (lambda d: ~_int_like(d["quantity"]) | (d["quantity"] < 0), "quantity must be a non-negative integer"),
            (lambda d: ~(d["unit_price"] > 0), "unit_price must be > 0"),
            (lambda d: d.duplicated("transaction_id", keep="first"),
             "conflicting duplicate transaction_id (first record kept)"),
        ],
        "prices": [
            (lambda d: ~d["sku"].isin(skus), "unknown SKU (not in product catalog)"),
            (lambda d: d["price_date"].isna(), "invalid price_date"),
            (lambda d: ~(d["actual_price"] > 0), "price must be > 0"),
            (lambda d: ~d["price_type"].isin(["regular", "promo"]), "price_type must be regular or promo"),
            (lambda d: d.duplicated(["sku", "price_date"], keep="last"), "duplicate price for SKU/date"),
        ],
        "inventory": [
            (lambda d: ~d["sku"].isin(skus), "unknown SKU (not in product catalog)"),
            *[(lambda d, c=c: ~_int_like(d[c]) | (d[c] < 0), f"{c} must be a non-negative integer")
              for c in ("available_quantity", "reserved_quantity", "incoming_quantity", "backordered_quantity")],
            (lambda d: d.duplicated("sku", keep="last"), "duplicate inventory record for SKU"),
        ],
        "snapshots": [
            (lambda d: ~d["sku"].isin(skus), "unknown SKU (not in product catalog)"),
            (lambda d: d["snapshot_date"].isna(), "invalid snapshot_date"),
            (lambda d: ~_int_like(d["quantity"]) | (d["quantity"] < 0), "quantity must be a non-negative integer"),
            (lambda d: d.duplicated(["sku", "snapshot_date"], keep="last"), "duplicate snapshot"),
        ],
    }
    for entity, rules in checks.items():
        d = frames[entity]
        r = pd.Series(None, index=d.index, dtype=object)
        if len(d):
            for fn, reason in rules:
                _rule(d, fn(d), reason, r)
        _collect(result, entity, d, r)

    for entity, st in result.stats.items():
        if st["received"] and st["invalid_ratio"] > max_invalid_ratio:
            result.critical.append(
                f"{entity}: {st['quarantined']} of {st['received']} records invalid "
                f"({st['invalid_ratio']:.1%} > {max_invalid_ratio:.0%} limit)")
    if full_product_load and result.stats["products"]["valid"] == 0:
        result.critical.append("products: no valid products in a full catalog load")
    return result


def _collect(result: ValidationResult, entity: str, df: pd.DataFrame, reasons: pd.Series) -> None:
    bad = reasons.notna()
    for raw, reason in zip(df.loc[bad, "_raw"], reasons[bad], strict=True):
        result.quarantine.append({"entity": entity, "reason": reason, "record": raw})
    result.valid[entity] = df.loc[~bad].drop(columns=["_raw"]).reset_index(drop=True)
    n = len(df)
    result.stats[entity] = {
        "received": n, "valid": int((~bad).sum()), "quarantined": int(bad.sum()),
        "invalid_ratio": round(float(bad.sum()) / n, 4) if n else 0.0,
        "reasons": reasons[bad].value_counts().to_dict(),
    }
