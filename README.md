# Retail Sales Analytics & Demand Forecasting

A 30-day demand forecast for every product, made by a single global **XGBoost** model.
Every training run is tracked in **MLflow** (params, backtest metrics, plots and a
registered model), a **Streamlit** dashboard shows the forecasts and sales analytics,
and the whole stack runs with **Docker Compose**.

```
┌──────────┐    ┌──────────────────────┐    ┌───────────────┐
│ postgres │◄───│ mlflow (UI :5000)    │◄───│ trainer (job) │── outputs/ ──► api (:8000) ──► dashboard (:8501)
└──────────┘    │ registry + artifacts │    └───────────────┘   forecast.csv  FastAPI        Streamlit
                └──────────────────────┘                        analytics/
```

| Service    | Role |
|------------|------|
| `postgres` | MLflow backend store (runs, params, metrics, model registry) |
| `mlflow`   | Tracking server + UI; proxies artifact uploads into the `mlflow-artifacts` volume |
| `trainer`  | One-shot job: analytics → rolling backtest → final fit → 30-day forecast → MLflow logging and registration, then it exits |
| `api`      | FastAPI service that serves forecasts and analytics from `outputs/` and reloads them when they change |
| `dashboard`| Streamlit app over the API: product forecasts, portfolio view, sales analytics, model metrics |

## Quick start

```bash
cp .env.example .env   # optional: ports, horizon, folds
make up                # = docker compose up -d --build
```

- MLflow UI: http://localhost:5000 (experiment `retail-demand-forecast`, model `retail-demand-xgb`)
- API docs: http://localhost:8000/docs
- Dashboard: http://localhost:8501

If `data/sales.csv` doesn't exist, the trainer generates a realistic synthetic dataset:
40 products in 5 categories over 3 years, with trend, weekly and yearly seasonality,
US-holiday effects, promotions with price elasticity, and some intermittent products.
To retrain later, run `make retrain` (`docker compose run --rm trainer`). Note that
`make up` also runs the trainer each time it starts the stack.

## Bring your own data

Put a CSV at `data/sales.csv` with one row per product per day:

| column | type | notes |
|---|---|---|
| `date` | YYYY-MM-DD | |
| `product_id` | str | |
| `category` | str | |
| `price` | float | selling price that day |
| `on_promo` | 0/1 | promotion running |
| `units_sold` | number | the target |

Missing product-days become zero sales, and duplicate rows are summed. You need about 13 months
of history for the 364-day lag to work; with less, it is left empty, which XGBoost handles.

**Planned promotions (optional):** `data/promo_plan.csv` with columns
`date, product_id, price, on_promo` overrides price and promo for future days. Without it,
the forecast assumes each product's latest regular price and no promotions.

## The model

- **One global XGBoost model** for all products (`reg:tweedie`, which suits zero-heavy count data).
  `product_id` and `category` are native categorical features, so products share what they learn.
- **Features:** calendar (day of week, month, week of year, holidays, days to/since a holiday),
  price and promo (price vs. its 28-day max), lags 1/2/3/7/14/21/28/364, rolling 7/28-day mean,
  28-day std, EWM, and the same-weekday mean over the last 4 weeks.
- **Recursive 30-day forecast:** each day is predicted from actuals plus the predictions
  for earlier forecast days.
- **Backtest:** 3 non-overlapping 30-day folds (rolling origin), scored against a seasonal-naive
  baseline (repeat last week). Promo and price for the test window come from the actuals,
  because promotions are planned in advance in retail.
- **Prediction intervals:** an empirical 80% band per product, from the 10th and 90th
  percentile of its backtest residuals.

Results on the synthetic data:

| metric | XGBoost | seasonal naive |
|---|---|---|
| WAPE | **0.292** | 0.416 |
| Bias | -2.6% | |

That is about **30% lower error** than the baseline.

### What gets logged to MLflow (per run)

- **Params:** every XGBoost hyperparameter, horizon, folds, lags, data range and size
- **Metrics:** `backtest_{mae,rmse,wape,bias}`, `naive_wape`, `wape_skill_vs_naive`, per-fold metrics (by step)
- **Artifacts:** `forecast/forecast.csv`, `evaluation/` (backtest predictions, per-product
  metrics, fold metrics, feature importance, backtest/forecast/revenue charts),
  `analytics/` (KPI summary, category mix, ABC classes, promo lift, monthly trend)
- **Model:** a pyfunc wrapper around the booster, registered as `retail-demand-xgb`.
  The `@champion` alias moves to a new version only if its backtest WAPE beats the current champion.

```python
import mlflow
mlflow.set_tracking_uri("http://localhost:5000")
model = mlflow.pyfunc.load_model("models:/retail-demand-xgb@champion")
model.predict(feature_rows)   # columns = retail_forecast.features.FEATURES; ids as plain strings
```

## Dashboard

http://localhost:8501. It gets everything from the API (`API_URL`) and holds no model code.

- **Product forecast:** pick a product to see recent actuals (promo days marked), the 30-day
  forecast with its 80% band, totals against the last 30 days, and a downloadable daily table.
- **All products:** forecast units by category, the products with the biggest forecast changes
  vs. the last period, and a sortable table of every product's forecast.
- **Sales analytics:** revenue KPIs, monthly revenue by category, revenue share, promo lift,
  and top products.
- **Model:** backtest metrics vs. the naive baseline, model and champion version, and links to
  the MLflow run and registry (`MLFLOW_UI_URL`, default http://localhost:5000).

Sidebar filters (category, ABC class, history window) apply across tabs. Data is cached for
60 seconds; **Refresh data** reloads it after a retrain.

## API

| Endpoint | Returns |
|---|---|
| `GET /health` | status, and whether a forecast is ready |
| `GET /model` | MLflow run id, model version, champion flag, backtest metrics |
| `GET /forecast?category=` | per-product 30-day totals with 80% bounds, and actuals for the previous 30 days |
| `GET /forecast/{product_id}` | daily forecast with lower/upper bounds, price and promo |
| `GET /history/{product_id}?days=` | daily actual sales, price and promo flag |
| `GET /products?category=&abc_class=` | product catalogue with ABC class |
| `GET /analytics/summary` | revenue/unit KPIs, change vs. prior 30 days and same period last year |
| `GET /analytics/categories` | revenue share and growth by category |
| `GET /analytics/top-products?n=` | products ranked by revenue |
| `GET /analytics/promo-lift` | average promo uplift by category |
| `GET /analytics/monthly?category=` | monthly revenue and units |

```bash
curl localhost:8000/forecast/P001
```

## Local development (no Docker)

```bash
pip install -r requirements-dev.txt
make test          # unit + API tests
make train-local   # tracks to sqlite:///mlflow.db; view with: mlflow ui --backend-store-uri sqlite:///mlflow.db
make api-local
make dashboard-local   # needs: pip install -r dashboard/requirements.txt
```

Configuration is read from environment variables: `DATA_PATH`, `OUTPUT_DIR`, `FORECAST_HORIZON`,
`BACKTEST_FOLDS`, `MLFLOW_TRACKING_URI`, `MLFLOW_EXPERIMENT`, `MLFLOW_REGISTERED_MODEL`,
`SYNTHETIC_PRODUCTS`, `SEED` (see `src/retail_forecast/config.py`).

## Layout

```
src/retail_forecast/
  data.py        load/validate/fill sales; synthetic generator
  features.py    calendar, price, lag and rolling features
  model.py       DemandForecaster: fit + recursive forecast
  evaluate.py    metrics, seasonal-naive baseline, rolling backtest, residual intervals
  analytics.py   KPIs, category mix, ABC classes, promo lift, day-of-week profile
  plots.py       charts logged to MLflow
  serving.py     MLflow pyfunc wrapper for the registered model
  pipeline.py    training job (entry point)
  api.py         FastAPI service
dashboard/       Streamlit app (talks to the API only)
docker/          app, MLflow and dashboard images
tests/           pytest suite
```
