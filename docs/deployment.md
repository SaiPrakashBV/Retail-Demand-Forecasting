# CI/CD and deployment

## Continuous integration (`.github/workflows/ci.yml`)

Runs on every push to `main` and on every pull request:

| Job | Checks |
|---|---|
| `python` | Ruff lint; migrations apply to a fresh PostgreSQL, `--check` reports nothing pending, and re-applying is a no-op; unit tests (data quality, ETL, models, reorder rules); integration test (migrate → ETL from the mock OData source → async training job → API, CSV and Excel reports) |
| `airflow` | Both DAGs import in the real Airflow 3.3.2 image, with the expected task order |
| `frontend` | ESLint, TypeScript type check, Vitest, production build |
| `docker` | `docker compose config` and a build of every image (after the others pass) |

Passing CI shows the system works; it does not show the forecasts are accurate. Watch model
accuracy separately, on the Forecasts page or in MLflow (backtest WAPE/MAPE and forecast vs
actual over time).

## Release images (`.github/workflows/release.yml`)

Pushing a tag such as `v2.0.0` builds the five images and publishes them to GitHub Container
Registry, tagged with the version, major.minor and commit SHA:

```
ghcr.io/<owner>/retail-analytics-app        # api, forecast-worker, migrate
ghcr.io/<owner>/retail-analytics-airflow    # Airflow with DAGs and ETL tasks
ghcr.io/<owner>/retail-analytics-frontend   # nginx + React build
ghcr.io/<owner>/retail-analytics-mlflow
ghcr.io/<owner>/retail-analytics-mock-odata
```

## Deploying

Deployment depends on where the stack runs, so it is not automated here. For a single host:

1. Copy `docker-compose.yml` and a `.env` to the server. Replace each `build:` with the published
   `image:` tags, or keep `build:` and check out the tag.
2. In `.env`, set real secrets: `POSTGRES_PASSWORD`, `TRAIN_API_KEY`, `AIRFLOW_JWT_SECRET`,
   `AIRFLOW_SECRET_KEY` and `AIRFLOW_FERNET_KEY`. Set `AIRFLOW_ALL_ADMINS=False` and configure
   Airflow users.
3. Point `ODATA_BASE_URL` at the real source, and drop the `mock-odata` service.
4. Put a TLS-terminating proxy in front of `frontend` (:3000). Do not expose Postgres, MLflow or
   Airflow publicly without authentication.
5. Run `docker compose up -d`. Migrations run automatically on every start.

To automate this, add a job to `release.yml` that runs after `publish`. For example, SSH to the
host and run `docker compose pull && docker compose up -d`, using credentials stored as
GitHub secrets.
