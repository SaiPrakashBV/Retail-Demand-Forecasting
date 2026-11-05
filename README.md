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
