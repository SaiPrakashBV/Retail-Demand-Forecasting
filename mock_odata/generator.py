"""Deterministic simulation of a mid-size retailer, used by the mock OData service.

What it simulates, per product and per day:

* true customer demand: base level, trend, weekly and yearly seasonality by category,
  US holidays and Black Friday, promotions with price elasticity, negative-binomial noise;
* selling prices: regular price changes every few months plus promotional discounts
  ("dynamic" products) or a fixed catalog price;
* inventory: an (s, S) replenishment policy with supplier lead times, occasional late
  planners and late suppliers, so stock-outs happen and *cap sales* (censored demand);
* a small rate of bad records (negative quantities, unknown/missing SKUs, duplicate
  transaction ids, zero prices, impossible dates) so data-quality checks have work to do.

Everything is generated once for a fixed calendar (SIM_START..SIM_END) with one random
stream per product, so the data published up to any "as of" date never changes when
the clock moves forward: each new day simply appends rows, like a real source system.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import holidays
import numpy as np
import pandas as pd

SIM_START = date(2023, 11, 1)
SIM_END = date(2028, 12, 31)

# category: (brands, items, price range, weekly profile Mon..Sun, yearly peak doy, yearly amplitude)
CATALOG: dict[str, tuple] = {
    "Electronics": (
        ["Sonix", "Voltra", "Nimbus"],
        ["Wireless Headphones", "Smart Watch", "Bluetooth Speaker", "USB-C Charger", "Fitness Tracker",
         "HD Webcam", "Wireless Mouse", "Mechanical Keyboard", "Portable SSD 1TB", "Power Bank 20000mAh"],
        (15, 220), [0.9, 0.9, 0.95, 1.0, 1.1, 1.35, 1.2], 345, 0.30,
    ),
    "Home": (
        ["Hearth & Co", "Casa Nova", "Brightline"],
        ["Coffee Maker", "Desk Lamp", "Air Purifier", "Blender", "Electric Kettle", "Toaster",
         "Throw Blanket", "Scented Candle Set", "Storage Baskets 3pk", "Non-stick Pan 28cm"],
        (12, 160), [1.0, 0.95, 0.95, 1.0, 1.05, 1.3, 1.2], 350, 0.22,
    ),
    "Fashion": (
        ["Northway", "Urban Thread", "Peak & Pine"],
        ["Running Shoes", "Denim Jacket", "Canvas Backpack", "Sunglasses", "Wool Scarf",
         "Rain Jacket", "Leather Belt", "Cotton T-Shirt 3pk", "Beanie Hat", "Hiking Socks 2pk"],
        (10, 140), [0.85, 0.85, 0.9, 1.0, 1.15, 1.45, 1.3], 300, 0.25,
    ),
    "Grocery": (
        ["Daily Harvest", "Green Basket", "Golden Mill"],
        ["Ground Coffee 1kg", "Green Tea 100ct", "Olive Oil 1L", "Granola 500g", "Dark Chocolate 6pk",
         "Sparkling Water 12pk", "Pasta 1kg", "Almond Butter", "Honey 500g", "Oat Milk 6pk"],
        (2, 25), [1.0, 0.95, 0.95, 1.0, 1.1, 1.3, 1.15], 355, 0.08,
    ),
    "Beauty": (
        ["Lumi", "Pure Petal", "Avena"],
        ["Face Moisturizer", "Shampoo 500ml", "Sunscreen SPF50", "Lip Balm 3pk", "Body Wash",
         "Hand Cream", "Hair Conditioner", "Facial Cleanser", "Vitamin C Serum", "Bath Salts"],
        (4, 60), [1.0, 1.0, 1.0, 1.0, 1.05, 1.15, 1.0], 170, 0.15,
    ),
    "Sports": (
        ["Stride", "Apex Gear", "TrailForm"],
        ["Yoga Mat", "Dumbbell Set 10kg", "Water Bottle 1L", "Resistance Bands", "Jump Rope",
         "Foam Roller", "Cycling Gloves", "Tennis Balls 4pk", "Gym Towel", "Kettlebell 12kg"],
        (8, 120), [1.1, 1.05, 1.0, 0.95, 0.9, 1.15, 1.1], 15, 0.25,
    ),
}

# Products launched recently (for "not enough history" handling); fixed so data never shifts.
NEW_PRODUCT_LAUNCH_WINDOW = (date(2026, 6, 1), date(2026, 10, 10))


@dataclass
class SimulatedRetailer:
    products: pd.DataFrame          # one row per product (static attributes)
    daily: pd.DataFrame             # product-day facts for the whole calendar
    purchase_orders: pd.DataFrame   # replenishment orders: placed / arrival dates


def _round_price(p: np.ndarray) -> np.ndarray:
    """Retail price endings: x.99 above $5, otherwise to the cent."""
    return np.where(p >= 5, np.maximum(np.round(p) - 0.01, 0.99), np.round(p, 2))


def _event_shape(dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Return (pre_holiday_boost, black_friday_window) indicator arrays."""
    cal = holidays.UnitedStates(years=range(dates.year.min(), dates.year.max() + 1))
    hol_idx = np.flatnonzero(np.isin(dates.date, list(cal)))
    pre = np.zeros(len(dates))
    for i in hol_idx:
        pre[max(0, i - 3):i] = 1.0
    is_hol = np.zeros(len(dates), dtype=bool)
    is_hol[hol_idx] = True
    # Black Friday = day after US Thanksgiving; Cyber week runs to the following Monday.
    bf = np.zeros(len(dates))
    for y in range(dates.year.min(), dates.year.max() + 1):
        thanksgiving = [d for d, n in cal.items() if d.year == y and "Thanksgiving" in n]
        if thanksgiving:
            start = pd.Timestamp(thanksgiving[0] + timedelta(days=1))
            bf[(dates >= start) & (dates <= start + pd.Timedelta(days=3))] = 1.0
    return pre - 0.3 * is_hol, bf


def simulate(n_products: int = 80, seed: int = 7) -> SimulatedRetailer:
    dates = pd.date_range(SIM_START, SIM_END, freq="D")
    n = len(dates)
    t = np.arange(n)
    doy = dates.dayofyear.to_numpy()
    dow = dates.dayofweek.to_numpy()
    holiday_fx, black_friday = _event_shape(dates)

    cats = list(CATALOG)
    products, frames, pos = [], [], []
    used_names: set[str] = set()

    for p in range(n_products):
        rng = np.random.default_rng([seed, p])
        cat = cats[p % len(cats)]
        brands, items, (pmin, pmax), weekly, peak_doy, amp = CATALOG[cat]
        item = items[(p // len(cats)) % len(items)]
        brand = brands[(p // (len(cats) * len(items)) + p) % len(brands)]
        name = f"{brand} {item}"
        while name in used_names:
            brand = brands[(brands.index(brand) + 1) % len(brands)]
            name = f"{brand} {item}" if f"{brand} {item}" not in used_names else f"{name} II"
        used_names.add(name)

        sku = f"SKU-{1001 + p}"
        price_mode = "dynamic" if rng.random() < 0.75 else "fixed"
        catalog_only = price_mode == "fixed" and rng.random() < 0.6  # no price history published
        is_new = rng.random() < 0.12
        if is_new:
            lo, hi = NEW_PRODUCT_LAUNCH_WINDOW
            launch = lo + timedelta(days=int(rng.integers(0, (hi - lo).days)))
        else:
            launch = SIM_START
        launch_idx = (launch - SIM_START).days

        # ---- prices -------------------------------------------------------------------
        base_price = float(np.exp(rng.uniform(np.log(pmin), np.log(pmax))))
        regular = np.full(n, base_price)
        promo = np.zeros(n, dtype=bool)
        discount = np.zeros(n)
        if price_mode == "dynamic":
            i = int(rng.integers(30, 120))
            level = base_price
            while i < n:
                level *= 1 + float(np.clip(rng.normal(0.025, 0.04), -0.10, 0.12))
                regular[i:] = level
                i += int(rng.integers(60, 200))
            i = int(rng.integers(0, 20))
            while i < n:
                if rng.random() < 0.35:
                    length = int(rng.integers(3, 8))
                    promo[i:i + length] = True
                    discount[i:i + length] = rng.choice([0.10, 0.15, 0.20, 0.25, 0.30, 0.35])
                    i += length + int(rng.integers(12, 35))
                else:
                    i += int(rng.integers(6, 18))
            # Black Friday: most dynamic products are discounted.
            bf_promo = (black_friday > 0) & (rng.random(n) < 0.85)
            promo |= bf_promo
            discount = np.where(bf_promo, np.maximum(discount, 0.25), discount)
        regular = _round_price(regular)
        price = _round_price(regular * (1 - discount))

        # ---- demand ------------------------------------------------------------------
        intermittent = rng.random() < 0.1
        base = float(rng.lognormal(0.5 if intermittent else 2.4, 0.6))
        trend = rng.normal(0.0, 0.3) / 1100
        amp_p = amp * rng.uniform(0.6, 1.4)
        elasticity = rng.uniform(1.3, 2.8)
        weekly_arr = np.asarray(weekly)
        bf_lift = {"Electronics": 3.0, "Home": 2.2, "Fashion": 2.0}.get(cat, 1.4)
        ramp = np.clip((t - launch_idx) / 30, 0, 1)  # new products ramp up over a month
        lam = (
            base * np.maximum(1 + trend * t, 0.2)
            * (1 + amp_p * np.cos(2 * np.pi * (doy - peak_doy) / 365.25))
            * weekly_arr[dow]
            * (1 + 0.35 * holiday_fx)
            * (1 + (bf_lift - 1) * black_friday)
            * (price / regular) ** (-elasticity)       # promo lift
            * (regular / base_price) ** (-0.6)         # mild response to list price moves
            * ramp
        )
        lam = np.clip(lam, 0.02, None)
        r = 2.5 if intermittent else 10.0
        demand = rng.poisson(rng.gamma(r, lam / r))
        demand[:launch_idx] = 0

        # ---- inventory: (s, S) policy with lead time --------------------------------
        mean_daily = float(np.mean(lam[launch_idx:]))
        lead_time = int(rng.choice([3, 5, 7, 10, 14, 21]))
        pack = int(rng.choice([1, 2, 4, 6, 12]))
        moq = int(max(pack, pack * np.ceil(mean_daily * rng.uniform(3, 8) / pack)))
        s_level = mean_daily * (lead_time + 5) * rng.uniform(0.8, 1.3)
        S_level = s_level + mean_daily * rng.uniform(14, 35)
        late_planner = rng.random(n) < 0.06          # order needed but placed late
        supplier_delay = rng.integers(0, max(2, lead_time // 3), size=n)

        on_hand = np.zeros(n, dtype=int)
        sales = np.zeros(n, dtype=int)
        stock = int(S_level) if launch_idx == 0 else 0
        arrivals: dict[int, int] = {}
        open_qty = 0
        planner_hold = 0
        for d in range(n):
            if d == launch_idx and launch_idx > 0:
                stock = int(S_level)
            got = arrivals.pop(d, 0)
            stock += got
            open_qty -= got
            sold = min(int(demand[d]), stock)
            sales[d] = sold
            stock -= sold
            on_hand[d] = stock
            if d < launch_idx:
                continue
            if planner_hold > 0:
                planner_hold -= 1
                continue
            if stock + open_qty <= s_level:
                if late_planner[d]:
                    planner_hold = int(rng.integers(4, 12))
                    continue
                qty = max(moq, int(np.ceil((S_level - stock - open_qty) / pack)) * pack)
                arrive = d + lead_time + int(supplier_delay[d])
                arrivals[arrive] = arrivals.get(arrive, 0) + qty
                open_qty += qty
                pos.append((sku, dates[d].date(), dates[min(arrive, n - 1)].date(), qty))

        # ---- bad-record flags (deterministic per product-day) ------------------------
        u = rng.random(n)
        noise = np.select(
            [u < 0.0015, u < 0.0025, u < 0.0040, u < 0.0045, u < 0.0050],
            ["negative_qty", "missing_sku", "duplicate_tx", "bad_date", "zero_price"],
            default="",
        )

        products.append({
            "Sku": sku, "Name": name, "Category": cat, "Brand": brand,
            "UnitCost": round(base_price * rng.uniform(0.5, 0.7), 2),
            "SupplierLeadTimeDays": lead_time, "MinOrderQty": moq, "PackSize": pack,
            "LaunchDate": launch.isoformat(), "PriceMode": price_mode, "CatalogOnly": bool(catalog_only),
            "_reserved_rate": float(rng.uniform(0.0, 0.06)),
        })
        frames.append(pd.DataFrame({
            "Sku": sku, "date": dates, "demand": demand, "sales": sales, "on_hand": on_hand,
            "price": price, "regular_price": regular, "on_promo": promo, "noise": noise,
            "launched": t >= launch_idx,
        }))

    po = pd.DataFrame(pos, columns=["Sku", "placed", "arrival", "qty"])
    return SimulatedRetailer(pd.DataFrame(products), pd.concat(frames, ignore_index=True), po)


# ------------------------------------------------------------------------------- entity sets
def build_entity_sets(sim: SimulatedRetailer, as_of: date) -> dict[str, pd.DataFrame]:
    """Materialise the OData entity sets as the source system would show them on ``as_of``."""
    d = sim.daily[(sim.daily["date"].dt.date <= as_of) & sim.daily["launched"]]
    as_of_iso = as_of.isoformat()
    modified = lambda s: (pd.to_datetime(s) + pd.Timedelta(hours=26)).dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731

    last = d.sort_values("date").groupby("Sku").tail(1).set_index("Sku")
    products = sim.products.copy()
    products["CurrentPrice"] = products["Sku"].map(last["regular_price"]).round(2)
    products["IsActive"] = products["Sku"].isin(last.index)
    products["ModifiedAt"] = f"{as_of_iso}T02:00:00Z"
    products = products[products["IsActive"]]

    # Sales: one daily POS summary row per product-day with sales.
    s = d[d["sales"] > 0]
    sales = pd.DataFrame({
        "TransactionId": "TX-" + s["Sku"].str[4:] + "-" + s["date"].dt.strftime("%Y%m%d"),
        "Sku": s["Sku"], "SaleDate": s["date"].dt.strftime("%Y-%m-%d"),
        "Quantity": s["sales"].astype(int), "UnitPrice": s["price"].round(2), "OnPromo": s["on_promo"],
        "ModifiedAt": modified(s["date"]), "_noise": s["noise"],
    })
    sales.loc[sales["_noise"] == "negative_qty", "Quantity"] *= -1
    sales.loc[sales["_noise"] == "missing_sku", "Sku"] = ""
    sales.loc[sales["_noise"] == "bad_date", "SaleDate"] = sales["SaleDate"].str[:5] + "13" + sales["SaleDate"].str[7:]
    sales.loc[sales["_noise"] == "zero_price", "UnitPrice"] = 0.0
    dupes = sales[sales["_noise"] == "duplicate_tx"].assign(Quantity=lambda x: x["Quantity"] + 1)
    unknown = sales.iloc[::997].assign(Sku="SKU-9999", TransactionId=lambda x: x["TransactionId"] + "-X")
    sales = pd.concat([sales, dupes, unknown]).drop(columns="_noise").sort_values(["SaleDate", "TransactionId"])

    # Price history: only for products that publish it.
    publish = set(sim.products.loc[~sim.products["CatalogOnly"], "Sku"])
    ph = d[d["Sku"].isin(publish)]
    prices = pd.DataFrame({
        "Sku": ph["Sku"], "PriceDate": ph["date"].dt.strftime("%Y-%m-%d"), "Price": ph["price"].round(2),
        "PriceType": np.where(ph["on_promo"], "Promo", "Regular"), "_noise": ph["noise"],
    })
    prices.loc[prices["_noise"] == "zero_price", "Price"] = 0.0
    prices = prices.drop(columns="_noise")

    snaps = pd.DataFrame({"Sku": d["Sku"], "SnapshotDate": d["date"].dt.strftime("%Y-%m-%d"),
                          "Quantity": d["on_hand"].astype(int)})

    po = sim.purchase_orders
    open_po = po[(po["placed"] <= as_of) & (po["arrival"] > as_of)]
    incoming = open_po.groupby("Sku").agg(qty=("qty", "sum"), eta=("arrival", "min"))
    rates = sim.products.set_index("Sku")["_reserved_rate"]
    inv = last[["on_hand"]].rename(columns={"on_hand": "AvailableQuantity"}).reset_index()
    inv["ReservedQuantity"] = np.floor(inv["AvailableQuantity"] * inv["Sku"].map(rates)).astype(int)
    inv["IncomingQuantity"] = inv["Sku"].map(incoming["qty"]).fillna(0).astype(int)
    inv["IncomingExpectedDate"] = inv["Sku"].map(incoming["eta"]).map(lambda x: x.isoformat() if pd.notna(x) else None)
    inv["BackorderedQuantity"] = 0
    inv["UpdatedAt"] = f"{as_of_iso}T23:59:00Z"

    public = ["Sku", "Name", "Category", "Brand", "CurrentPrice", "UnitCost", "SupplierLeadTimeDays",
              "MinOrderQty", "PackSize", "LaunchDate", "IsActive", "ModifiedAt"]
    return {
        "Products": products[public].reset_index(drop=True),
        "SalesTransactions": sales.reset_index(drop=True),
        "PriceHistory": prices.reset_index(drop=True),
        "Inventory": inv.reset_index(drop=True),
        "InventorySnapshots": snaps.reset_index(drop=True),
    }
