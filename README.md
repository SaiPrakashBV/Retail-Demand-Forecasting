# Retail Sales Analytics and Demand Forecasting System

> **Work in progress:** the project is being rebuilt into the full multi-service system
> (React UI, FastAPI, Airflow ETL, PostgreSQL, demand + price forecasting, inventory
> planning, MLflow, CI). Each phase is committed as it lands; the full README with run
> instructions arrives with the Docker Compose integration phase.

## Done so far

| Phase | Contents |
|---|---|
| 1. Database & source | PostgreSQL schema and migrations (`database/`), mock OData v4 service with a simulated retailer (`mock_odata/`) |
| 2. Airflow ETL | `retail_etl` DAG: extract (OData + CSV drop-zone) → clean → validate (quarantine, critical stop) → transform → idempotent load → status; `forecast_training` DAG (`airflow/`) |
| 3. FastAPI backend | `backend/app`: routes, services, repositories, schemas, models; product search, sales/prices, forecasts, inventory, analytics, reports (CSV/Excel), pipeline status, async training jobs with API key |
| 4. Forecasting | `ml/`: demand candidates XGBoost (global) vs Prophet (per product) backtested on the same folds, best one used per run; separate price model (XGBoost vs naive last-regular) for products with price history; MLflow runs, registry `production` alias; forecast worker processing async jobs |
| 5. Inventory & reports | Reorder point / safety stock / MOQ / pack-size recommendations with stock-out dates and explanations; forecast-vs-actual accuracy (backtest and production); CSV/Excel reports |
| 6. React frontend | `frontend/`: Vite + React + TypeScript + Material UI + Recharts; dashboard, product catalog search, product details (demand, price, forecast vs actual, inventory, daily table), forecasts and training, inventory reorders, reports, pipeline status; light/dark themes |

