// Shapes returned by the FastAPI backend (see backend/app/schemas and services).

export type StockStatus = "in_stock" | "low_stock" | "out_of_stock";
export type Priority = "critical" | "high" | "medium" | "low";

export interface ProductCard {
  sku: string;
  name: string;
  category: string;
  brand: string;
  current_price: number;
  forecast_price: number | null;
  forecast_price_change: number | null;
  price_forecast_available: boolean;
  available_quantity: number;
  reserved_quantity: number;
  incoming_quantity: number;
  stock_status: StockStatus;
  stock_status_label: string;
  forecast_demand_30d: number | null;
  units_30d: number;
  revenue_30d: number | null;
  days_of_cover: number | null;
  reorder_priority: Priority | null;
  reorder_quantity: number | null;
}

export interface ProductPage {
  items: ProductCard[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface FacetValue {
  value: string;
  count: number;
}

export interface FilterOptions {
  categories: FacetValue[];
  brands: FacetValue[];
  stock_statuses: FacetValue[];
  min_price: number | null;
  max_price: number | null;
  max_forecast: number | null;
}

export interface PriceAvailability {
  available: boolean;
  reason: string | null;
  history_days: number;
}

export interface Recommendation {
  available_quantity: number;
  reserved_quantity: number;
  incoming_quantity: number;
  backordered_quantity: number;
  inventory_position: number;
  lead_time_days: number;
  review_period_days: number;
  lead_time_demand: number;
  safety_stock: number;
  reorder_point: number;
  target_stock: number;
  reorder_quantity: number;
  days_of_cover: number | null;
  predicted_stockout_date: string | null;
  priority: Priority;
  explanation: string;
  generated_at: string;
}

export interface ProductDetail extends ProductCard {
  unit_cost: number | null;
  launch_date: string | null;
  is_active: boolean;
  supplier_lead_time_days: number;
  min_order_qty: number;
  pack_size: number;
  incoming_expected_date: string | null;
  inventory_updated_at: string | null;
  forecast_generated_at: string | null;
  price_forecast: PriceAvailability;
  reorder: Recommendation | null;
  data_end_date: string | null;
}

export interface SalesPoint {
  date: string;
  units: number;
  revenue: number;
  avg_price: number | null;
  on_promo: boolean;
  stock_on_hand?: number | null;
  in_stock?: boolean | null;
  stockout_days?: number;
}

export interface SalesHistory {
  sku: string;
  start: string;
  end: string;
  granularity: "day" | "week" | "month";
  points: SalesPoint[];
  totals: { units: number; revenue: number };
}

export interface PricePoint {
  date: string;
  actual_price: number;
  price_type: "regular" | "promo";
}

export interface PriceHistory {
  sku: string;
  start: string;
  end: string;
  current_price: number;
  points: PricePoint[];
  has_history: boolean;
  forecast: PriceAvailability;
}

export interface RunSummary {
  run_id: string;
  run_type: "production" | "backtest";
  status: string;
  generated_at: string;
  cutoff_date: string;
  horizon_days: number;
  demand_model: string;
  demand_model_version: string | null;
  price_model: string | null;
  price_model_version: string | null;
  mlflow_run_id: string | null;
  price_mlflow_run_id: string | null;
  products_forecast: number | null;
  metrics: Record<string, unknown>;
}

export interface ForecastPoint {
  date: string;
  demand: number;
  demand_lower: number | null;
  demand_upper: number | null;
  price: number | null;
  price_lower: number | null;
  price_upper: number | null;
  price_status: "forecast" | "unavailable";
  actual_units: number | null;
  actual_price: number | null;
}

export interface ProductForecast {
  sku: string;
  name: string;
  run: RunSummary;
  generated_at: string;
  summary: {
    total_demand: number;
    total_demand_lower: number;
    total_demand_upper: number;
    avg_daily_demand: number;
    current_price: number;
    forecast_price_end: number | null;
    forecast_price_change: number | null;
    price_forecast_available: boolean;
  };
  price_forecast: PriceAvailability;
  points: ForecastPoint[];
}

export interface AccuracyMetrics {
  n_obs: number | null;
  products: number | null;
  actual_units: number | null;
  forecast_units: number | null;
  mae: number | null;
  rmse: number | null;
  wape: number | null;
  bias: number | null;
  price_n_obs: number | null;
  price_mae: number | null;
  price_mape: number | null;
  price_bias: number | null;
}

export interface ComparisonRun {
  run_id: string;
  run_type: "production" | "backtest";
  model_name: string;
  price_model_name: string | null;
  trained_at: string;
  cutoff_date: string;
  horizon_days: number;
  generated_at: string;
  days_with_actuals: number;
  metrics: AccuracyMetrics | null;
}

export interface ForecastComparisonData {
  sku: string;
  runs: ComparisonRun[];
  selected_run_id: string;
  points: {
    date: string;
    forecast: number | null;
    lower: number | null;
    upper: number | null;
    actual: number | null;
    forecast_price: number | null;
    actual_price: number | null;
  }[];
}

export interface BacktestModelRow {
  target: "demand" | "price";
  model_name: string;
  is_selected: boolean;
  products: number;
  n_obs: number;
  mae: number | null;
  rmse: number | null;
  wape: number | null;
  bias: number | null;
  mape: number | null;
}

export interface ProductAccuracyRow {
  sku: string;
  name: string;
  category: string;
  model_name: string;
  mae: number | null;
  rmse: number | null;
  wape: number | null;
  bias: number | null;
  mape: number | null;
  n_obs: number;
}

export interface AccuracyReport {
  run: RunSummary;
  backtest: { demand: BacktestModelRow[]; price: BacktestModelRow[] };
  forecast_vs_actual: {
    run_id: string;
    run_type: string;
    cutoff_date: string;
    generated_at: string;
    demand_model: string;
    price_model: string | null;
    metrics: AccuracyMetrics | null;
  }[];
  products: { demand: ProductAccuracyRow[]; price: ProductAccuracyRow[] } | null;
}

export interface Kpi {
  value: number;
  previous?: number;
  change?: number | null;
}

export interface Dashboard {
  has_data: boolean;
  message?: string;
  period: {
    start: string;
    end: string;
    days: number;
    previous_start: string;
    previous_end: string;
    data_start: string;
    data_end: string;
  };
  kpis: {
    revenue: Kpi;
    units: Kpi;
    transactions: Kpi;
    active_products: { value: number; selling: number };
    low_stock_skus: { value: number; out_of_stock: number };
    forecast_demand_30d: { value: number; revenue: number; change_vs_last_30d: number | null; available: boolean };
  };
  trend: { bucket: "day" | "week" | "month"; points: { period: string; revenue: number; units: number }[] };
  top_products: { sku: string; name: string; category: string; brand: string; units: number; revenue: number }[];
  categories: { category: string; revenue: number; units: number; products: number }[];
  low_stock: ProductCard[];
  reorder_priorities: Partial<Record<Priority, number>>;
}

export interface Portfolio {
  run: RunSummary;
  daily: { date: string; demand: number; demand_lower: number | null; demand_upper: number | null; revenue: number }[];
  total_demand: number;
  total_revenue: number;
}

export interface TrainingJob {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  requested_by: string;
  requested_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: number;
  stage: string | null;
  message: string | null;
  error: string | null;
  params: Record<string, unknown>;
  run_id: string | null;
}

export interface ReorderItem extends Recommendation {
  sku: string;
  name: string;
  category: string;
  brand: string;
  current_price: number;
  unit_cost: number | null;
  min_order_qty: number;
  pack_size: number;
  order_value: number | null;
}

export interface ReorderList {
  items: ReorderItem[];
  total: number;
  priority_counts: Partial<Record<Priority, number>>;
}

export interface ProductInventory {
  sku: string;
  available_quantity: number;
  reserved_quantity: number;
  incoming_quantity: number;
  incoming_expected_date: string | null;
  backordered_quantity: number;
  updated_at: string | null;
  stock_status: StockStatus;
  stock_status_label: string;
  supplier_lead_time_days: number;
  min_order_qty: number;
  pack_size: number;
  recommendation: Recommendation | null;
  snapshots: { date: string; quantity: number }[];
}

export interface ReportInfo {
  id: string;
  title: string;
}

export interface ReportPreview {
  report: string;
  total_rows: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface PipelineRun {
  pipeline_id: string;
  dag_id: string;
  start_time: string;
  end_time: string | null;
  status: "running" | "succeeded" | "failed";
  source: string | null;
  records_extracted: number;
  records_processed: number;
  records_quarantined: number;
  error: string | null;
  critical: string[] | null;
  duration_seconds: number | null;
}

export interface PipelineStatus {
  freshness: {
    data_start: string | null;
    data_end: string | null;
    hours_since_data_end: number | null;
    is_stale: boolean;
    stale_after_hours: number;
    last_successful_ingestion: string | null;
    latest_forecast_at: string | null;
    latest_forecast_cutoff: string | null;
  };
  ingestion_runs: PipelineRun[];
  latest_quarantine: { entity: string; reason: string; count: number }[];
  forecast_jobs: TrainingJob[];
  latest_forecast_run: RunSummary | null;
  table_counts: Record<string, number>;
  links: { airflow: string; mlflow: string };
}

export interface QuarantineRecord {
  quarantine_id: number;
  entity: string;
  reason: string;
  record: Record<string, unknown>;
  quarantined_at: string;
}
