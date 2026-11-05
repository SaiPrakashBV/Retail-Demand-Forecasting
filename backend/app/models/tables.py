"""Database entity definitions (SQLAlchemy Core), mirroring database/migrations.

The migrations are the source of truth; tests check these definitions against the live
schema so the two cannot drift apart silently.
"""

from __future__ import annotations

from sqlalchemy import (Boolean, Column, Date, DateTime, Float, Integer, MetaData, Numeric, Table, Text)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

products = Table(
    "products", metadata,
    Column("product_id", Integer, primary_key=True), Column("sku", Text), Column("name", Text),
    Column("category", Text), Column("brand", Text), Column("current_price", Numeric),
    Column("unit_cost", Numeric), Column("supplier_lead_time_days", Integer), Column("min_order_qty", Integer),
    Column("pack_size", Integer), Column("launch_date", Date), Column("is_active", Boolean),
    Column("source_modified_at", DateTime(timezone=True)), Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

sales_transactions = Table(
    "sales_transactions", metadata,
    Column("transaction_id", Text, primary_key=True), Column("product_id", Integer), Column("sale_date", Date),
    Column("quantity", Integer), Column("unit_price", Numeric), Column("on_promo", Boolean),
    Column("revenue", Numeric), Column("loaded_at", DateTime(timezone=True)),
)

price_history = Table(
    "price_history", metadata,
    Column("product_id", Integer, primary_key=True), Column("price_date", Date, primary_key=True),
    Column("actual_price", Numeric), Column("price_type", Text), Column("loaded_at", DateTime(timezone=True)),
)

inventory = Table(
    "inventory", metadata,
    Column("product_id", Integer, primary_key=True), Column("available_quantity", Integer),
    Column("reserved_quantity", Integer), Column("incoming_quantity", Integer),
    Column("incoming_expected_date", Date), Column("backordered_quantity", Integer),
    Column("updated_at", DateTime(timezone=True)),
)

inventory_snapshots = Table(
    "inventory_snapshots", metadata,
    Column("product_id", Integer, primary_key=True), Column("snapshot_date", Date, primary_key=True),
    Column("quantity", Integer),
)

forecast_runs = Table(
    "forecast_runs", metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True), Column("job_id", UUID(as_uuid=True)),
    Column("run_type", Text), Column("product_id", Integer), Column("model_name", Text),
    Column("price_model_name", Text), Column("demand_model_version", Text), Column("price_model_version", Text),
    Column("mlflow_run_id", Text), Column("price_mlflow_run_id", Text), Column("trained_at", DateTime(timezone=True)),
    Column("data_start_date", Date), Column("cutoff_date", Date), Column("horizon_days", Integer),
    Column("products_forecast", Integer), Column("status", Text), Column("metrics", JSONB),
)

forecasts = Table(
    "forecasts", metadata,
    Column("forecast_id", Integer, primary_key=True), Column("run_id", UUID(as_uuid=True)),
    Column("product_id", Integer), Column("generated_at", DateTime(timezone=True)), Column("forecast_date", Date),
    Column("demand_prediction", Numeric), Column("demand_lower", Numeric), Column("demand_upper", Numeric),
    Column("price_prediction", Numeric), Column("price_lower", Numeric), Column("price_upper", Numeric),
    Column("price_status", Text), Column("model_run_id", Text),
)

model_accuracy = Table(
    "model_accuracy", metadata,
    Column("run_id", UUID(as_uuid=True), primary_key=True), Column("product_id", Integer, primary_key=True),
    Column("target", Text, primary_key=True), Column("model_name", Text, primary_key=True),
    Column("mae", Float), Column("rmse", Float), Column("wape", Float), Column("bias", Float), Column("mape", Float),
    Column("n_obs", Integer), Column("is_selected", Boolean),
)

forecast_jobs = Table(
    "forecast_jobs", metadata,
    Column("job_id", UUID(as_uuid=True), primary_key=True), Column("status", Text), Column("requested_by", Text),
    Column("requested_at", DateTime(timezone=True)), Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)), Column("progress", Integer), Column("stage", Text),
    Column("message", Text), Column("error", Text), Column("params", JSONB), Column("run_id", UUID(as_uuid=True)),
)

reorder_recommendations = Table(
    "reorder_recommendations", metadata,
    Column("recommendation_id", Integer, primary_key=True), Column("run_id", UUID(as_uuid=True)),
    Column("product_id", Integer), Column("generated_at", DateTime(timezone=True)),
    Column("available_quantity", Integer), Column("reserved_quantity", Integer), Column("incoming_quantity", Integer),
    Column("backordered_quantity", Integer), Column("inventory_position", Integer), Column("lead_time_days", Integer),
    Column("review_period_days", Integer), Column("lead_time_demand", Numeric), Column("safety_stock", Numeric),
    Column("reorder_point", Numeric), Column("target_stock", Numeric), Column("reorder_quantity", Integer),
    Column("days_of_cover", Numeric), Column("predicted_stockout_date", Date), Column("priority", Text),
    Column("explanation", Text),
)

data_pipeline_runs = Table(
    "data_pipeline_runs", metadata,
    Column("pipeline_id", Text, primary_key=True), Column("dag_id", Text), Column("start_time", DateTime(timezone=True)),
    Column("end_time", DateTime(timezone=True)), Column("status", Text), Column("source", Text),
    Column("records_extracted", Integer), Column("records_processed", Integer), Column("records_quarantined", Integer),
    Column("details", JSONB), Column("error", Text),
)

quarantine_records = Table(
    "quarantine_records", metadata,
    Column("quarantine_id", Integer, primary_key=True), Column("pipeline_id", Text), Column("entity", Text),
    Column("reason", Text), Column("record", JSONB), Column("quarantined_at", DateTime(timezone=True)),
)
