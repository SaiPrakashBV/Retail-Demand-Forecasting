# API

Interactive documentation: http://localhost:8000/docs (OpenAPI at `/openapi.json`).

Every error uses the same shape, with a message written for people:

```json
{"error": {"code": "forecast_unavailable", "message": "No forecast has been generated yet. …", "details": {}}}
```

| Status | Codes |
|---|---|
| 401 | `unauthorized` (missing/invalid `X-API-Key` for training) |
| 404 | `not_found`, `unknown_report` |
| 409 | `job_already_active` (details carry the active `job_id`) |
| 422 | `invalid_request` (lists each invalid parameter) |
| 503 | `forecast_unavailable`, `comparison_unavailable`, `database_unavailable`, `database_not_ready`, `training_disabled` |
| 500 | `internal_error` with a reference id that appears in the API logs |

## Endpoints

| Method & path | Purpose |
|---|---|
| `GET /api/products` | Search and filter: `q` (SKU, name, brand, category, fuzzy name), `category`, `brand`, `min_price`, `max_price`, `stock_status`, `min_forecast`, `max_forecast`, `sort`, `order`, `page`, `page_size` |
| `GET /api/products/filters` | Facet values and ranges for the filters |
| `GET /api/products/{sku}` | Product details, stock, price-forecast availability, latest recommendation |
| `GET /api/products/{sku}/sales` | Daily, weekly or monthly sales (zero-filled, with stock-out flags) |
| `GET /api/products/{sku}/prices` | Historical selling prices (regular/promo) |
| `GET /api/products/{sku}/forecast` | 30-day demand and price forecast with intervals, run and model versions |
| `GET /api/products/{sku}/forecast-comparison` | Earlier forecasts vs actual units and prices |
| `GET /api/products/{sku}/inventory` | Stock position, recommendation, snapshots |
| `GET /api/analytics/dashboard` | KPIs vs the previous period, trend, top products, categories, low stock |
| `GET /api/analytics/accuracy` | Backtest accuracy by model and target, plus forecast-vs-actual by run |
| `GET /api/inventory/reorders` | Reorder list: `priority`, `category`, `q`, `actionable_only`, `sort` |
| `GET /api/reports` / `GET /api/reports/{id}` | Report list; preview (`format=json`) or download (`csv`, `xlsx`) |
| `GET /api/pipelines/status` | Data freshness, ingestion runs, quarantine summary, jobs, links |
| `GET /api/pipelines/runs/{id}` / `…/quarantine` | One ingestion run and its quarantined records |
| `POST /api/forecasts/train` | Queue a training job (header `X-API-Key: $TRAIN_API_KEY`); returns **202** with a job id |
| `GET /api/forecasts/jobs/{job_id}` | Job status, stage, progress %, message or error |
| `GET /api/forecasts/jobs`, `/runs`, `/portfolio` | Recent jobs, forecast runs, total daily forecast |
| `GET /health` | Liveness and a database check |

Example:

```bash
curl -s -X POST localhost:8000/api/forecasts/train -H "X-API-Key: local-dev-train-key" \
  -H "Content-Type: application/json" -d '{"requested_by": "me"}'
```
