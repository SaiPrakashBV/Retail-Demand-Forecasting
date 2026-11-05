# Forecasting

Demand and price are two separate prediction problems, each with its own models, backtest
and accuracy figures.

## Demand: units per product per day, 30 days ahead

**Eligibility.** A product needs `MIN_DEMAND_HISTORY_DAYS` (90) days since its first sale. Newer
products get no forecast, and the UI says why.

**Candidates** (`DEMAND_MODELS=xgboost,prophet`):

| Model | How it works |
|---|---|
| `xgboost` | One global model across products (Tweedie objective for zero-heavy counts). Features: calendar, US holidays, days to Black Friday, price and price ratio, promotion, lags 1–364 days, rolling means/std, same-weekday mean, recent stock-out days. Forecasts recursively, one day at a time. |
| `prophet` | One Prophet model per product on log(1+units), with weekly and yearly seasonality, US holidays plus a Black Friday window, and promotion and price-ratio regressors. A smearing correction turns the log-scale median back into a mean. Fitted in parallel. |
| `seasonal_naive` | Baseline only: repeats each product's last week. |

**Backtest and selection.** Three non-overlapping 30-day windows end at the latest data date
(rolling origin; never random splits). Every candidate is trained only on data before each cutoff
and scored on the following 30 days. Stock-out days are left out of scoring, because sales on
those days understate demand. The candidate with the lowest volume-weighted error (WAPE) produces
the production forecast for that run. Both candidates' numbers are kept in MLflow and in
`model_accuracy`.

**Stock-outs.** Training data marks days that ended with zero stock (`in_stock = 0`). XGBoost
learns that sales drop on those days, and Prophet ignores them. Forecasts assume stock is
available, so they estimate real demand, which is what reorder planning needs.

**Intervals.** 80% bands. Prophet produces them natively. For XGBoost they come from each
product's backtest error quantiles, falling back to pooled relative errors for products the
backtest did not cover.

## Price: expected selling price per day, 30 days ahead

**Eligibility.** A product needs `PRICE_MIN_HISTORY_DAYS` (180) recorded prices, with the latest
in the last 7 days. Sales quantities alone are not used to infer prices. Products without
history show their latest catalog price, and their future price is marked unavailable with a
reason ("the source has no price history" or "only N days").

| Model | How it works |
|---|---|
| `naive_last_regular` | The last regular (non-promotional) price, carried forward |
| `xgboost_price` | A global direct multi-horizon model of price ÷ last regular price. It uses promotion frequency and depth, days since the last promotion and the last list-price change, recent list-price trend, and target-date calendar features such as the Black Friday window. Trained on absolute error, so it predicts the typical (median) price. |

Selection is by backtest MAPE. Forecast prices are estimates for planning: nothing in the system
changes catalog prices.

## Tracking (MLflow)

Each training job creates, per target (experiments `retail-demand-forecast` and
`retail-price-forecast`):

- A parent run with run settings, the selected model, its backtest metrics (MAE, RMSE, WAPE,
  bias, MAPE), the naive baseline and a skill score. Artifacts include the backtest chart, feature
  importance, metrics per fold, the forecast CSV, and which products were skipped and why.
- A nested run per candidate, with its parameters, metrics per fold and per-product accuracy.
- A registered model version (`retail-demand-model` and `retail-price-model`), stored as a
  self-contained forecaster. The `production` alias points at the version that produced the
  current forecasts; the previous version is tagged `replaced_by`.

```python
import mlflow, pandas as pd
mlflow.set_tracking_uri("http://localhost:5000")
model = mlflow.pyfunc.load_model("models:/retail-demand-model@production")
model.predict(pd.DataFrame({"sku": ["SKU-1001"]}))   # next 30 days
```

## Storage

- `forecast_runs`: one `production` run per job, plus `backtest` runs for each cutoff. Backtest
  runs are the "earlier forecasts" compared with actuals in the UI, and only the latest job's are
  kept.
- `forecasts`: one row per product per day, with demand and its band, price and its band, and a
  `price_status`. `generated_at` (when the prediction was made) is stored separately from
  `forecast_date` (the day being predicted). Production forecasts therefore turn into
  forecast-vs-actual comparisons as soon as the real sales for those days arrive.
- `model_accuracy`: backtest metrics per product, target and candidate.

## Accuracy views

- **Backtest** (stored at training time): per model, per product, demand WAPE/MAE/bias and price MAPE.
- **Forecast vs actual** (computed live): for every earlier run whose dates now have actuals.
  This is the ongoing check once production forecasts age into the past.

Passing CI does not mean the forecasts are accurate. Watch these accuracy figures over time.
