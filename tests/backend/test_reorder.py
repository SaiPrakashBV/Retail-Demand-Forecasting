"""Reorder business rules."""

from datetime import date

from app.services.reorder_service import compute_recommendation

AS_OF = date(2026, 11, 4)


def rec(**kw):
    args = dict(as_of=AS_OF, lead_time_days=7, min_order_qty=1, pack_size=1, available=100, reserved=0, incoming=0,
                backordered=0, incoming_expected_date=None, demand=[10.0] * 30, daily_error_sd=3.0,
                review_period_days=7, service_level=0.95)
    args.update(kw)
    return compute_recommendation(**args)


def test_reorder_point_and_quantity():
    r = rec(available=60)
    # lead-time demand 70 + safety 1.645 * 3 * sqrt(7) = 13.06
    assert r.lead_time_demand == 70 and round(r.safety_stock, 1) == 13.1
    assert r.reorder_point == round(70 + r.safety_stock, 2)
    # target = 14 days * 10 + safety; order = target - position, rounded up
    assert r.reorder_quantity == 94 and r.priority == "critical"  # runs out on day 6, before day-7 arrival
    assert r.predicted_stockout_date == date(2026, 11, 10)


def test_inventory_position_counts_incoming_reserved_and_backorders():
    r = rec(available=50, reserved=10, incoming=80, backordered=5, incoming_expected_date=date(2026, 11, 6))
    assert r.inventory_position == 50 - 10 + 80 - 5
    assert r.reorder_quantity == 0  # 115 > reorder point (~83)


def test_moq_and_pack_size_rounding():
    r = rec(available=70, min_order_qty=100, pack_size=12)
    assert r.reorder_quantity >= 100 and r.reorder_quantity % 12 == 0


def test_well_stocked_is_low_priority_with_no_order():
    r = rec(available=400)
    assert r.reorder_quantity == 0 and r.priority == "low" and r.predicted_stockout_date is None
    assert r.days_of_cover == 40.0 and "No order needed" in r.explanation


def test_out_of_stock_is_critical():
    r = rec(available=0)
    assert r.priority == "critical" and r.predicted_stockout_date == date(2026, 11, 5)
    assert "Out of stock now" in r.explanation


def test_late_incoming_order_is_explained():
    r = rec(available=20, incoming=200, incoming_expected_date=date(2026, 11, 12))
    assert r.priority == "critical" and r.reorder_quantity == 0
    assert "before the incoming order arrives (Nov 12)" in r.explanation


def test_interval_used_when_no_error_estimate():
    r = rec(available=200, daily_error_sd=None, demand_lower=[5.0] * 30, demand_upper=[15.0] * 30)
    assert r.safety_stock > 0
