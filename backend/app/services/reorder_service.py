"""Reorder calculations and business rules.

    reorder point   = expected demand during supplier lead time + safety stock
    safety stock    = z(service level) x daily forecast error x sqrt(lead time)
    inventory pos.  = available - reserved + incoming - backordered
    target stock    = expected demand over (lead time + review period) + safety stock
    order quantity  = max(0, target - position) when position <= reorder point,
                      raised to the minimum order quantity and rounded up to whole packs

Priority:
    critical  out of stock now, or predicted to run out before a new order could arrive
    high      at or below the reorder point: order now
    medium    will cross the reorder point within the review period
    low       comfortably stocked
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from statistics import NormalDist

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..config import get_settings
from ..repositories import inventory_repository as repo
from ..repositories.base import fetch_all

Z_80 = NormalDist().inv_cdf(0.9)  # forecasts carry 80% intervals (10th..90th percentile)


@dataclass
class Recommendation:
    available_quantity: int
    reserved_quantity: int
    incoming_quantity: int
    backordered_quantity: int
    inventory_position: int
    lead_time_days: int
    review_period_days: int
    lead_time_demand: float
    safety_stock: float
    reorder_point: float
    target_stock: float
    reorder_quantity: int
    days_of_cover: float | None
    predicted_stockout_date: date | None
    priority: str
    explanation: str


def _extend(values: list[float], n: int) -> list[float]:
    """Pad a daily forecast beyond its horizon with the average of its last week."""
    if len(values) >= n:
        return values[:n]
    tail = values[-7:] or [0.0]
    return values + [sum(tail) / len(tail)] * (n - len(values))


def compute_recommendation(
    *, as_of: date, lead_time_days: int, min_order_qty: int, pack_size: int,
    available: int, reserved: int, incoming: int, backordered: int, incoming_expected_date: date | None,
    demand: list[float], demand_lower: list[float] | None = None, demand_upper: list[float] | None = None,
    daily_error_sd: float | None = None, review_period_days: int = 7, service_level: float = 0.95,
) -> Recommendation:
    """``demand`` is the daily forecast starting the day after ``as_of``."""
    L = max(int(lead_time_days), 1)
    R = max(int(review_period_days), 1)
    pack = max(int(pack_size), 1)
    moq = max(int(min_order_qty), 1)
    horizon = len(demand)

    if daily_error_sd is None:
        if demand_lower and demand_upper:
            widths = [(u - lo) / (2 * Z_80) for lo, u in zip(demand_lower, demand_upper)]
            daily_error_sd = sum(widths) / len(widths)
        else:
            daily_error_sd = 0.0
    z = NormalDist().inv_cdf(service_level)

    lt_demand = sum(_extend(demand, L))
    safety = z * daily_error_sd * math.sqrt(L)
    reorder_point = lt_demand + safety
    target = sum(_extend(demand, L + R)) + safety
    net_on_hand = available - reserved - backordered
    position = available - reserved + incoming - backordered

    qty = 0
    if position <= reorder_point and target - position > 0:
        qty = max(moq, math.ceil((target - position) / pack) * pack)
        qty = math.ceil(qty / pack) * pack

    # Stock-out date: deplete on-hand stock day by day, adding the open order on arrival.
    stockout = None
    stock = float(net_on_hand)
    if stock <= 0:
        stockout = as_of + timedelta(days=1)
    else:
        for i, d in enumerate(demand):
            day = as_of + timedelta(days=i + 1)
            if incoming and incoming_expected_date and day == incoming_expected_date:
                stock += incoming
            stock -= d
            if stock <= 0:
                stockout = day
                break

    avg_daily = sum(demand[:30]) / max(min(horizon, 30), 1)
    cover = round(min(max(net_on_hand, 0) / avg_daily, 365.0), 1) if avg_daily > 0 else None

    arrival_if_ordered_now = as_of + timedelta(days=L)
    if net_on_hand <= 0 or (stockout is not None and stockout <= arrival_if_ordered_now):
        priority = "critical"
    elif position <= reorder_point:
        priority = "high"
    elif position <= reorder_point + avg_daily * R:
        priority = "medium"
    else:
        priority = "low"

    explanation = _explain(position, net_on_hand, incoming, incoming_expected_date, reorder_point, lt_demand, safety,
                           L, target, qty, pack, moq, stockout, priority, arrival_if_ordered_now)
    return Recommendation(
        available_quantity=available, reserved_quantity=reserved, incoming_quantity=incoming,
        backordered_quantity=backordered, inventory_position=position, lead_time_days=L, review_period_days=R,
        lead_time_demand=round(lt_demand, 2), safety_stock=round(safety, 2), reorder_point=round(reorder_point, 2),
        target_stock=round(target, 2), reorder_quantity=int(qty), days_of_cover=cover,
        predicted_stockout_date=stockout, priority=priority, explanation=explanation,
    )


def _explain(position, on_hand, incoming, eta, rop, ltd, safety, L, target, qty, pack, moq, stockout, priority,
             arrival) -> str:
    stock_txt = f"{on_hand} on hand" + (f" + {incoming} incoming" + (f" on {eta:%b %d}" if eta else "") if incoming else "")
    parts = [f"Inventory position is {position} ({stock_txt}); reorder point is {rop:.0f} "
             f"({ltd:.0f} units expected over the {L}-day lead time + {safety:.0f} safety stock)."]
    if qty > 0:
        rounding = []
        if pack > 1:
            rounding.append(f"packs of {pack}")
        if moq > 1:
            rounding.append(f"minimum order {moq}")
        parts.append(f"Order {qty} units to reach the target of {target:.0f}"
                     + (f" (rounded for {' and '.join(rounding)})." if rounding else "."))
    else:
        parts.append("No order needed yet.")
    if stockout:
        if priority == "critical" and on_hand <= 0:
            parts.append("Out of stock now.")
        elif priority == "critical":
            parts.append(f"Predicted to run out on {stockout:%b %d}, before a new order could arrive "
                         f"({arrival:%b %d}): expedite or rebalance stock.")
        else:
            parts.append(f"Without action, stock runs out around {stockout:%b %d}.")
    return " ".join(parts)


# ------------------------------------------------------------------ persistence (used by the worker)
def generate_for_run(conn: Connection, run_id: str) -> int:
    """Compute and store recommendations for every product in a production forecast run."""
    s = get_settings()
    run = conn.execute(text("SELECT cutoff_date FROM forecast_runs WHERE run_id = CAST(:r AS uuid)"),
                       {"r": run_id}).mappings().one()
    rows = fetch_all(conn, """
        SELECT p.product_id, p.supplier_lead_time_days, p.min_order_qty, p.pack_size,
               COALESCE(i.available_quantity, 0) AS available, COALESCE(i.reserved_quantity, 0) AS reserved,
               COALESCE(i.incoming_quantity, 0) AS incoming, COALESCE(i.backordered_quantity, 0) AS backordered,
               i.incoming_expected_date,
               array_agg(f.demand_prediction::float ORDER BY f.forecast_date) AS demand,
               array_agg(f.demand_lower::float ORDER BY f.forecast_date) AS lower,
               array_agg(f.demand_upper::float ORDER BY f.forecast_date) AS upper,
               (SELECT a.rmse FROM model_accuracy a WHERE a.run_id = CAST(:r AS uuid)
                  AND a.product_id = p.product_id AND a.target = 'demand' AND a.is_selected LIMIT 1) AS rmse
        FROM forecasts f JOIN products p USING (product_id)
        LEFT JOIN inventory i ON i.product_id = p.product_id
        WHERE f.run_id = CAST(:r AS uuid)
        GROUP BY p.product_id, i.product_id""", r=run_id)
    out = []
    for r in rows:
        rec = compute_recommendation(
            as_of=run["cutoff_date"], lead_time_days=r["supplier_lead_time_days"], min_order_qty=r["min_order_qty"],
            pack_size=r["pack_size"], available=r["available"], reserved=r["reserved"], incoming=r["incoming"],
            backordered=r["backordered"], incoming_expected_date=r["incoming_expected_date"], demand=r["demand"],
            demand_lower=r["lower"], demand_upper=r["upper"], daily_error_sd=r["rmse"],
            review_period_days=s.review_period_days, service_level=s.service_level)
        out.append({"run_id": run_id, "product_id": r["product_id"], **asdict(rec)})
    conn.execute(text("DELETE FROM reorder_recommendations WHERE run_id = CAST(:r AS uuid)"), {"r": run_id})
    if out:
        cols = list(out[0])
        conn.execute(text(f"INSERT INTO reorder_recommendations ({', '.join(cols)}) VALUES "
                          f"({', '.join(':' + c for c in cols)})"), out)
    return len(out)


def list_reorders(conn: Connection, **kw) -> dict:
    items, total = repo.reorders(conn, **kw)
    for it in items:
        cost = it.get("unit_cost")
        it["order_value"] = round(float(cost) * it["reorder_quantity"], 2) if cost is not None else None
    return {"items": items, "total": total, "priority_counts": repo.priority_counts(conn)}
