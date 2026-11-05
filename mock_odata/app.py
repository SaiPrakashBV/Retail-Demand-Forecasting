"""Minimal OData v4 service over the simulated retailer.

Implements what the ETL extractor needs from a real OData source:

* service document (``/odata/``) and ``$metadata``
* entity sets: Products, SalesTransactions, PriceHistory, Inventory, InventorySnapshots
* ``$filter`` (eq ne gt ge lt le, combined with ``and``), ``$select``, ``$orderby``,
  ``$top``, ``$skip``, ``$count=true``
* server-driven paging through ``@odata.nextLink`` (``$skiptoken``)

Data is published up to ``MOCK_AS_OF`` (default: yesterday), so a new day of sales
appears every day, just like a live system.
"""

from __future__ import annotations

import math
import os
import re
from datetime import date, timedelta
from functools import lru_cache
from urllib.parse import urlencode

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .generator import SIM_END, build_entity_sets, simulate

PAGE_SIZE = int(os.environ.get("MOCK_PAGE_SIZE", "5000"))
N_PRODUCTS = int(os.environ.get("MOCK_PRODUCTS", "80"))
SEED = int(os.environ.get("MOCK_SEED", "7"))

KEYS = {
    "Products": ["Sku"], "SalesTransactions": ["TransactionId"], "PriceHistory": ["Sku", "PriceDate"],
    "Inventory": ["Sku"], "InventorySnapshots": ["Sku", "SnapshotDate"],
}

app = FastAPI(title="Mock Retail OData Service", version="1.0")


def as_of() -> date:
    raw = os.environ.get("MOCK_AS_OF")
    d = date.fromisoformat(raw) if raw else date.today() - timedelta(days=1)
    return min(d, SIM_END)


@lru_cache(maxsize=1)
def _sim():
    return simulate(n_products=N_PRODUCTS, seed=SEED)


@lru_cache(maxsize=4)
def _entities(day: date) -> dict[str, pd.DataFrame]:
    return build_entity_sets(_sim(), day)


def entities() -> dict[str, pd.DataFrame]:
    return _entities(as_of())


# --------------------------------------------------------------------------- query options
_COND = re.compile(r"^\s*(\w+)\s+(eq|ne|gt|ge|lt|le)\s+(.+?)\s*$", re.IGNORECASE)
_OPS = {"eq": "__eq__", "ne": "__ne__", "gt": "__gt__", "ge": "__ge__", "lt": "__lt__", "le": "__le__"}


def _literal(raw: str):
    raw = raw.strip()
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if raw.lower() == "null":
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?", raw):
        return raw  # dates are compared as ISO strings, which sort correctly
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError as exc:
        raise HTTPException(400, f"Unsupported literal in $filter: {raw}") from exc


def apply_filter(df: pd.DataFrame, expr: str) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for part in re.split(r"\s+and\s+", expr.strip(), flags=re.IGNORECASE):
        m = _COND.match(part)
        if not m:
            raise HTTPException(400, f"Unsupported $filter clause: {part!r} (use 'Field op value' joined by 'and')")
        field, op, value = m.group(1), m.group(2).lower(), _literal(m.group(3))
        if field not in df.columns:
            raise HTTPException(400, f"Unknown property in $filter: {field}")
        col = df[field]
        if value is None:
            cond = col.isna() if op == "eq" else col.notna()
        else:
            if isinstance(value, str):
                col = col.astype("string")
            cond = getattr(col, _OPS[op])(value).fillna(False)
        mask &= cond
    return df[mask]


def _records(df: pd.DataFrame) -> list[dict]:
    out = df.astype(object).where(df.notna(), None).to_dict(orient="records")
    for r in out:
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                r[k] = None
    return out


# --------------------------------------------------------------------------- endpoints
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "as_of": as_of().isoformat()}


@app.get("/odata/")
@app.get("/odata")
def service_document(request: Request) -> dict:
    base = str(request.base_url).rstrip("/") + "/odata"
    return {"@odata.context": f"{base}/$metadata",
            "value": [{"name": n, "kind": "EntitySet", "url": n} for n in KEYS]}


@app.get("/odata/$metadata")
def metadata() -> Response:
    ents = entities()
    edm = {"int64": "Edm.Int64", "float64": "Edm.Decimal", "bool": "Edm.Boolean"}
    types = []
    for name, df in ents.items():
        props = "".join(
            f'<Property Name="{c}" Type="{edm.get(str(df[c].dtype), "Edm.String")}"/>' for c in df.columns
        )
        keys = "".join(f'<PropertyRef Name="{k}"/>' for k in KEYS[name])
        types.append(f'<EntityType Name="{name}"><Key>{keys}</Key>{props}</EntityType>')
    sets = "".join(f'<EntitySet Name="{n}" EntityType="Retail.{n}"/>' for n in KEYS)
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx"><edmx:DataServices>'
        f'<Schema Namespace="Retail" xmlns="http://docs.oasis-open.org/odata/ns/edm">{"".join(types)}'
        f'<EntityContainer Name="Container">{sets}</EntityContainer></Schema></edmx:DataServices></edmx:Edmx>'
    )
    return Response(xml, media_type="application/xml")


@app.get("/odata/{entity_set}")
def query(entity_set: str, request: Request) -> JSONResponse:
    ents = entities()
    if entity_set not in ents:
        raise HTTPException(404, f"Entity set {entity_set!r} not found. Available: {', '.join(ents)}")
    q = request.query_params
    df = ents[entity_set]

    if f := q.get("$filter"):
        df = apply_filter(df, f)
    if ob := q.get("$orderby"):
        cols, asc = [], []
        for item in ob.split(","):
            parts = item.strip().split()
            if parts[0] not in df.columns:
                raise HTTPException(400, f"Unknown property in $orderby: {parts[0]}")
            cols.append(parts[0])
            asc.append(len(parts) < 2 or parts[1].lower() != "desc")
        df = df.sort_values(cols, ascending=asc, kind="stable")
    total = len(df)

    skip = int(q.get("$skip", 0)) + int(q.get("$skiptoken", 0))
    top = int(q["$top"]) if "$top" in q else None
    remaining = df.iloc[skip:] if top is None else df.iloc[skip:skip + top - int(q.get("$skiptoken", 0))]
    page = remaining.iloc[:PAGE_SIZE]

    if sel := q.get("$select"):
        cols = [c.strip() for c in sel.split(",")]
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise HTTPException(400, f"Unknown properties in $select: {missing}")
        page = page[cols]

    base = str(request.base_url).rstrip("/")
    body: dict = {"@odata.context": f"{base}/odata/$metadata#{entity_set}"}
    if q.get("$count", "").lower() == "true":
        body["@odata.count"] = total
    body["value"] = _records(page)
    if len(remaining) > PAGE_SIZE:
        params = {k: v for k, v in q.items() if k != "$skiptoken"}
        params["$skiptoken"] = str(int(q.get("$skiptoken", 0)) + PAGE_SIZE)
        body["@odata.nextLink"] = f"{base}/odata/{entity_set}?{urlencode(params)}"
    return JSONResponse(body)
