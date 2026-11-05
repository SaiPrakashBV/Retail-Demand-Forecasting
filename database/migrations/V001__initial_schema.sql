-- Retail analytics schema. Business identifier = sku; internal key = product_id.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ------------------------------------------------------------------ catalog & facts
CREATE TABLE products (
    product_id              SERIAL PRIMARY KEY,
    sku                     TEXT NOT NULL UNIQUE,
    name                    TEXT NOT NULL,
    category                TEXT NOT NULL,
    brand                   TEXT NOT NULL,
    current_price           NUMERIC(12, 2) NOT NULL CHECK (current_price > 0),
    unit_cost               NUMERIC(12, 2),
    supplier_lead_time_days INTEGER NOT NULL DEFAULT 7 CHECK (supplier_lead_time_days >= 0),
    min_order_qty           INTEGER NOT NULL DEFAULT 1 CHECK (min_order_qty >= 1),
    pack_size               INTEGER NOT NULL DEFAULT 1 CHECK (pack_size >= 1),
    launch_date             DATE,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    source_modified_at      TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX products_category_idx ON products (category);
CREATE INDEX products_brand_idx ON products (brand);
CREATE INDEX products_name_trgm_idx ON products USING gin (name gin_trgm_ops);
CREATE INDEX products_sku_trgm_idx ON products USING gin (sku gin_trgm_ops);

CREATE TABLE sales_transactions (
    transaction_id  TEXT PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products (product_id),
    sale_date       DATE NOT NULL,
    quantity        INTEGER NOT NULL CHECK (quantity >= 0),
    unit_price      NUMERIC(12, 2) NOT NULL CHECK (unit_price > 0),
    on_promo        BOOLEAN NOT NULL DEFAULT FALSE,
    revenue         NUMERIC(14, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX sales_product_date_idx ON sales_transactions (product_id, sale_date);
CREATE INDEX sales_date_idx ON sales_transactions (sale_date);

CREATE TABLE price_history (
    product_id    INTEGER NOT NULL REFERENCES products (product_id),
    price_date    DATE NOT NULL,
    actual_price  NUMERIC(12, 2) NOT NULL CHECK (actual_price > 0),
    price_type    TEXT NOT NULL CHECK (price_type IN ('regular', 'promo')),
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (product_id, price_date)
);

CREATE TABLE inventory (
    product_id              INTEGER PRIMARY KEY REFERENCES products (product_id),
    available_quantity      INTEGER NOT NULL CHECK (available_quantity >= 0),
    reserved_quantity       INTEGER NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
    incoming_quantity       INTEGER NOT NULL DEFAULT 0 CHECK (incoming_quantity >= 0),
    incoming_expected_date  DATE,
    backordered_quantity    INTEGER NOT NULL DEFAULT 0 CHECK (backordered_quantity >= 0),
    updated_at              TIMESTAMPTZ NOT NULL
);

CREATE TABLE inventory_snapshots (
    product_id     INTEGER NOT NULL REFERENCES products (product_id),
    snapshot_date  DATE NOT NULL,
    quantity       INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (product_id, snapshot_date)
);

-- ------------------------------------------------------------------ forecasting
-- One row per forecast generation: production forecasts, and the backtest forecasts made
-- "as of" earlier cutoffs (used to compare earlier predictions with later actuals).
CREATE TABLE forecast_runs (
    run_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id               UUID,
    run_type             TEXT NOT NULL CHECK (run_type IN ('production', 'backtest')),
    product_id           INTEGER REFERENCES products (product_id),  -- NULL = all eligible products
    model_name           TEXT NOT NULL,                              -- demand model used
    price_model_name     TEXT,
    demand_model_version TEXT,
    price_model_version  TEXT,
    mlflow_run_id        TEXT,
    price_mlflow_run_id  TEXT,
    trained_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_start_date      DATE,
    cutoff_date          DATE NOT NULL,                              -- last date of data used
    horizon_days         INTEGER NOT NULL,
    products_forecast    INTEGER,
    status               TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    metrics              JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX forecast_runs_type_idx ON forecast_runs (run_type, trained_at DESC);

CREATE TABLE forecasts (
    forecast_id        BIGSERIAL PRIMARY KEY,
    run_id             UUID NOT NULL REFERENCES forecast_runs (run_id) ON DELETE CASCADE,
    product_id         INTEGER NOT NULL REFERENCES products (product_id),
    generated_at       TIMESTAMPTZ NOT NULL,   -- when the prediction was made
    forecast_date      DATE NOT NULL,          -- the day being predicted
    demand_prediction  NUMERIC(12, 2) NOT NULL,
    demand_lower       NUMERIC(12, 2),
    demand_upper       NUMERIC(12, 2),
    price_prediction   NUMERIC(12, 2),         -- NULL when price forecasting is unavailable
    price_lower        NUMERIC(12, 2),
    price_upper        NUMERIC(12, 2),
    price_status       TEXT NOT NULL DEFAULT 'unavailable' CHECK (price_status IN ('forecast', 'unavailable')),
    model_run_id       TEXT,                   -- MLflow run id of the demand model
    UNIQUE (run_id, product_id, forecast_date)
);
CREATE INDEX forecasts_product_date_idx ON forecasts (product_id, forecast_date);

-- Backtest accuracy per product, target (demand / price) and candidate model.
CREATE TABLE model_accuracy (
    run_id        UUID NOT NULL REFERENCES forecast_runs (run_id) ON DELETE CASCADE,
    product_id    INTEGER NOT NULL REFERENCES products (product_id),
    target        TEXT NOT NULL CHECK (target IN ('demand', 'price')),
    model_name    TEXT NOT NULL,
    mae           DOUBLE PRECISION,
    rmse          DOUBLE PRECISION,
    wape          DOUBLE PRECISION,
    bias          DOUBLE PRECISION,
    mape          DOUBLE PRECISION,
    n_obs         INTEGER,
    is_selected   BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run_id, product_id, target, model_name)
);

CREATE TABLE forecast_jobs (
    job_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status        TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    requested_by  TEXT NOT NULL,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    progress      INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    stage         TEXT,
    message       TEXT,
    error         TEXT,
    params        JSONB NOT NULL DEFAULT '{}'::jsonb,
    run_id        UUID REFERENCES forecast_runs (run_id) ON DELETE SET NULL
);
CREATE INDEX forecast_jobs_status_idx ON forecast_jobs (status, requested_at);
-- At most one queued-or-running job at a time.
CREATE UNIQUE INDEX forecast_jobs_one_active_idx ON forecast_jobs ((true)) WHERE status IN ('queued', 'running');

-- ------------------------------------------------------------------ inventory planning
CREATE TABLE reorder_recommendations (
    recommendation_id       BIGSERIAL PRIMARY KEY,
    run_id                  UUID NOT NULL REFERENCES forecast_runs (run_id) ON DELETE CASCADE,
    product_id              INTEGER NOT NULL REFERENCES products (product_id),
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_quantity      INTEGER NOT NULL,
    reserved_quantity       INTEGER NOT NULL,
    incoming_quantity       INTEGER NOT NULL,
    backordered_quantity    INTEGER NOT NULL,
    inventory_position      INTEGER NOT NULL,
    lead_time_days          INTEGER NOT NULL,
    review_period_days      INTEGER NOT NULL,
    lead_time_demand        NUMERIC(12, 2) NOT NULL,
    safety_stock            NUMERIC(12, 2) NOT NULL,
    reorder_point           NUMERIC(12, 2) NOT NULL,
    target_stock            NUMERIC(12, 2) NOT NULL,
    reorder_quantity        INTEGER NOT NULL CHECK (reorder_quantity >= 0),
    days_of_cover           NUMERIC(8, 1),
    predicted_stockout_date DATE,
    priority                TEXT NOT NULL CHECK (priority IN ('critical', 'high', 'medium', 'low')),
    explanation             TEXT NOT NULL,
    UNIQUE (run_id, product_id)
);

-- ------------------------------------------------------------------ pipeline monitoring
CREATE TABLE data_pipeline_runs (
    pipeline_id          TEXT PRIMARY KEY,         -- Airflow run id
    dag_id               TEXT NOT NULL,
    start_time           TIMESTAMPTZ NOT NULL,
    end_time             TIMESTAMPTZ,
    status               TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    source               TEXT,
    records_extracted    INTEGER NOT NULL DEFAULT 0,
    records_processed    INTEGER NOT NULL DEFAULT 0,
    records_quarantined  INTEGER NOT NULL DEFAULT 0,
    details              JSONB NOT NULL DEFAULT '{}'::jsonb,
    error                TEXT
);
CREATE INDEX data_pipeline_runs_start_idx ON data_pipeline_runs (start_time DESC);

CREATE TABLE quarantine_records (
    quarantine_id    BIGSERIAL PRIMARY KEY,
    pipeline_id      TEXT NOT NULL,
    entity           TEXT NOT NULL,
    reason           TEXT NOT NULL,
    record           JSONB NOT NULL,
    quarantined_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX quarantine_pipeline_idx ON quarantine_records (pipeline_id);

-- Incremental extraction high-water marks per source entity.
CREATE TABLE etl_watermarks (
    entity      TEXT PRIMARY KEY,
    last_value  TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
