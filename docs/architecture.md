# Architecture

```
 Data sources                 Orchestration              Storage                  Serving
 ─────────────                ─────────────              ───────                  ───────
 OData service ──┐                                                                React UI (:3000)
 (mock-odata)    │   Airflow  retail_etl (daily)        PostgreSQL                    │  nginx /api
 CSV drop-zone ──┴─▶ extract → clean → validate ──────▶ retail  (products, sales,     ▼
 data/incoming/      → transform → load → status         prices, inventory,       FastAPI (:8000)
                         │      (quarantine)              forecasts, reorders,       ▲
                         ▼                                pipeline runs)              │ reads
                     forecast_training DAG                    ▲                       │
                         │ POST /api/forecasts/train          │ writes                │
                         ▼                                    │                       │
                     forecast_jobs (queue) ──▶ forecast-worker ─┘                      │
                                               │ backtest XGBoost vs Prophet, price models
                                               ▼
                                            MLflow (:5000)  runs, metrics, registry
                                            (backend store: PostgreSQL "mlflow" DB)
```

## Services (docker-compose.yml)

| Container | Image | Role |
|---|---|---|
| `postgres` | postgres:17 | One server, three databases: `retail` (application), `mlflow`, `airflow` |
| `migrate` | app | Applies `database/migrations` once, then exits |
| `mock-odata` | mock-odata | OData v4 source with a simulated retailer (replace with a real service via `ODATA_BASE_URL`) |
| `airflow-init` | airflow | `airflow db migrate`, then exits |
| `airflow-api-server` | airflow | Airflow 3 UI and API (:8080), also the task execution API |
| `airflow-scheduler` | airflow | Schedules DAGs and runs tasks (LocalExecutor) |
| `airflow-dag-processor` | airflow | Parses DAG files (required separately in Airflow 3) |
| `airflow-bootstrap` | airflow | First start only: triggers `retail_etl` if it has never run |
| `mlflow` | mlflow | Tracking server and model registry, artifacts proxied into a volume |
| `api` | app | FastAPI backend |
| `forecast-worker` | app | Runs queued training jobs |
| `frontend` | frontend | nginx serving the React build and proxying `/api` |

**Executor.** Airflow uses the LocalExecutor, so tasks run inside `airflow-scheduler` and there is no
separate `airflow-worker` container. For more parallelism, switch to the CeleryExecutor (adds Redis
and `airflow-worker`) without changing the DAG code.

**Why training is not an Airflow task.** Training is CPU- and memory-heavy and needs the ML stack
(XGBoost, Prophet, MLflow), which the Airflow image does not carry. Airflow only *requests* a job
through the API and waits for it; the worker does the work. The UI uses the same path, so training
never runs inside a web request (no timeouts or opaque HTTP 500s), and only one job runs at a time
(enforced by a unique index on active jobs).

## Startup sequence

1. `postgres` becomes healthy; its init script creates the `mlflow` and `airflow` databases.
2. `migrate` creates or updates the application schema.
3. `airflow-init` migrates Airflow's metadata database. Then the API server, scheduler and
   DAG processor start, and the DAGs become available unpaused.
4. The first `retail_etl` run loads products, sales, prices and inventory. The scheduler usually
   queues it right away; `airflow-bootstrap` triggers it if not.
5. `retail_etl` triggers `forecast_training`, which queues a job; `forecast-worker` trains,
   tracks the run in MLflow and stores forecasts and reorder recommendations.
6. FastAPI and the React app serve the results. Until each step has run, the UI says what is
   missing (for example "No forecast has been generated yet") instead of showing empty charts.

## Code layout

| Path | Contents |
|---|---|
| `database/` | `migrations/V*.sql`, `migrate.py` (ordered, checksummed, `--check` for CI), init script |
| `mock_odata/` | `generator.py` (simulation), `app.py` (OData v4 endpoints) |
| `airflow/dags/` | `retail_etl_dag.py`, `forecast_training_dag.py` |
| `airflow/tasks/` | Framework-free ETL steps: `extract_odata`, `clean_data`, `validate_data`, `transform_data`, `load_postgres`, `update_data_status`, `pipeline` |
| `backend/app/` | `main.py`, `config.py`, `database.py`, `errors.py`, `routes/`, `services/`, `repositories/`, `schemas/`, `models/` |
| `ml/` | `data.py`, `features.py`, `train_demand.py`, `train_price.py`, `evaluate.py`, `predict.py`, `mlflow_tracking.py`, `model_registry.py`, `forecast_store.py`, `pipeline.py`, `worker.py` |
| `frontend/src/` | `App.tsx`, `pages/*Page.tsx`, `components/` (ProductSearch, DemandChart, PriceChart, ForecastComparison, …), `api/apiClient.ts`, `api/types.ts` |
| `tests/` | `pipeline/`, `ml/`, `backend/`, `integration/` |
| `docker/` | Dockerfiles, nginx config, Airflow bootstrap script |
| `.github/workflows/` | `ci.yml` (every push/PR), `release.yml` (versioned images on tags) |
