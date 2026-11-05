.PHONY: up down logs test test-all lint frontend-check retrain etl clean

up:              ## Build and start the whole stack
	docker compose up -d --build

down:            ## Stop the stack (data is kept in volumes)
	docker compose down

logs:
	docker compose logs -f api forecast-worker airflow-scheduler

test:            ## Python unit tests
	pytest -m "not integration"

test-all:        ## Unit + integration tests (needs TEST_DATABASE_URL pointing at a disposable database)
	pytest

lint:
	ruff check backend ml airflow mock_odata database tests
	cd frontend && npm run lint && npm run typecheck

frontend-check:
	cd frontend && npm ci && npm run lint && npm run typecheck && npm test && npm run build

etl:             ## Trigger the ingestion DAG now
	docker compose exec airflow-scheduler airflow dags trigger retail_etl

retrain:         ## Trigger forecast training now
	docker compose exec airflow-scheduler airflow dags trigger forecast_training

clean:           ## Stop and DELETE all data volumes
	docker compose down -v
