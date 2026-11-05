# Retail Sales Analytics and Demand Forecasting System

An end-to-end retail analytics platform:

- **Data:** collects product, sales, price and inventory data through a scheduled Airflow ETL.
- **Analytics:** analyses historical sales.
- **Forecasts:** predicts daily demand and selling prices for the next 30 days.
- **Reorders:** recommends when and how much to order.

Results are served through a FastAPI backend and an interactive React app. Experiments and model
versions are tracked in MLflow, and the whole stack runs with Docker Compose.

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Material UI, Recharts (Vite) |
| Backend | Python, FastAPI, SQLAlchemy |
| Data pipeline | Apache Airflow 3 (OData + CSV sources) |
| Database | PostgreSQL 17 |
| Machine learning | XGBoost and Prophet (demand), XGBoost (price), backtested against baselines |
| ML tracking | MLflow (runs, metrics, artifacts, model registry) |
| Containers | Docker Compose |
| CI/CD | GitHub Actions |

## Quick start

You need Docker with Compose v2, and about 6 GB of free memory for the stack.

```bash
git clone https://github.com/SaiPrakashBV/Retail-Demand-Forecasting.git
```

```bash
cd Retail-Demand-Forecasting && docker compose up -d --build
```

The first start builds the images (5–10 minutes). Then it runs the first ingestion (about
1 minute) and the first training job (about 2 minutes). Follow progress on the **Pipeline status**
page, or with:

```bash
docker compose logs -f forecast-worker
```

| Open | URL |
|---|---|
| Web app | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Airflow | http://localhost:8080 (no login in local mode) |
| MLflow | http://localhost:5000 |
| Mock OData source | http://localhost:8081/odata/ |

Everything works with the defaults. To change ports or secrets, copy `.env.example` to `.env`
first. On macOS, port 5000 may be taken by AirPlay Receiver, so set `MLFLOW_PORT=5001`.

**Starting training by hand:** use the **Train models** button on the Forecasts page (the default
key is `local-dev-train-key`), or trigger `forecast_training` in Airflow.

## What it does

1. **Ingestion** (`retail_etl` DAG, daily): reads the OData source (and any CSV files in
   `data/incoming/`) incrementally. It cleans and validates the data, quarantines bad records with a
   reason, and stops on critical data-quality failures. It loads PostgreSQL with idempotent upserts,
   then triggers forecasting. See [docs/data-pipeline.md](docs/data-pipeline.md).
2. **Demand forecasting:** a global XGBoost model and per-product Prophet models are backtested
   on the same rolling 30-day windows, scored on in-stock days. The more accurate one produces the
   run's 30-day forecasts with 80% intervals.
3. **Price forecasting:** a separate model (XGBoost vs the last regular price), only for products
   with enough recorded price history. Other products show their catalog price and a clear
   "unavailable" reason. See [docs/forecasting.md](docs/forecasting.md).
4. **MLflow:** every job logs both candidates, their metrics and charts, and registers the selected
   models. The `production` alias marks the version behind the current forecasts.
5. **Inventory:** reorder point = demand over the supplier lead time + safety stock. The order
   quantity covers lead time plus a review period, rounded to the minimum order and pack size. Each
   recommendation includes a predicted stock-out date, a priority and a plain-language explanation.
6. **App:** dashboard KPIs; product search and filters; product pages comparing historical and
   forecast demand and prices, and earlier forecasts against actuals; inventory and reorder lists;
   CSV/Excel reports; pipeline status. See [docs/user-guide.md](docs/user-guide.md).

The bundled `mock-odata` service simulates a retailer: 80 products in 6 categories and 3 years of
history. The history includes seasonality, Black Friday, promotions, price changes, supplier lead
times, stock-outs and a small share of deliberately bad records. Each day new data appears, like a
live system. To use a real OData service, set `ODATA_BASE_URL`.

## Results on the simulated data

| | Demand (WAPE) | Price (MAPE) |
|---|---|---|
| XGBoost (selected) | **35.2%** | **3.37%** |
| Prophet | 35.9% | — |
| Baseline | 50.9% (seasonal naive) | 3.41% (last regular price) |

These are backtest numbers over three 30-day windows. Passing CI does not mean the forecasts are
accurate; keep watching accuracy on the Forecasts page.

## Development

```bash
pip install -r requirements-dev.txt
```

Unit tests (no database needed):

```bash
pytest -m "not integration"
```

Full flow against a disposable database:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://retail:retail@localhost:5432/retail_test pytest tests/integration
```

Frontend, with a dev server that proxies `/api` to localhost:8000:

```bash
cd frontend && npm ci && npm run dev
```

The `Makefile` has shortcuts (`make up`, `make test`, `make lint`, `make retrain`, …).
Contributions are checked by GitHub Actions; see [docs/deployment.md](docs/deployment.md).

## Documentation

- [Architecture and startup sequence](docs/architecture.md)
- [Data pipeline and data-quality rules](docs/data-pipeline.md)
- [Forecasting, tracking and accuracy](docs/forecasting.md)
- [API](docs/api.md)
- [User guide](docs/user-guide.md)
- [CI/CD and deployment](docs/deployment.md)

## Acceptance criteria

- [x] Retail data extracted automatically through an Airflow OData pipeline (plus CSV drop-zone)
- [x] Data-quality checks run before PostgreSQL loading (quarantine, plus a hard stop on critical failures)
- [x] Product catalog search by SKU, name, category and brand
- [x] Product details show actual historical prices and sales
- [x] Separate 30-day demand forecast for eligible products
- [x] 30-day price forecast when enough price history exists, with a reason when it doesn't
- [x] Experiments, metrics and versions tracked in MLflow
- [x] Interactive charts compare actuals with earlier predictions
- [x] Inventory view of low-stock products with reorder suggestions
- [x] Readable messages for API, data and model failures
- [x] Docker Compose starts the complete stack
- [x] GitHub Actions validates the application (lint, migrations, DAGs, tests, builds)

## Known limitations

- **Simulated source:** the OData source is simulated. Real sources need the field mapping checked
  (see [docs/data-pipeline.md](docs/data-pipeline.md)).
- **Single host:** Airflow runs with the LocalExecutor, so tasks run inside the scheduler container
  instead of a separate worker.
- **Development settings:** the local defaults (no Airflow login, sample secrets) are for
  development only. See [docs/deployment.md](docs/deployment.md) before sharing the stack.
- **Inventory inputs:** incoming purchase orders are one total per product with the earliest
  arrival date, not individual orders.
