.PHONY: up down retrain logs test train-local api-local dashboard-local clean

up:            ## Build and start postgres, MLflow, the training job and the API
	docker compose up -d --build

down:          ## Stop the stack (keeps MLflow volumes)
	docker compose down

retrain:       ## Run the training job again; the API picks up new outputs automatically
	docker compose run --rm trainer

logs:
	docker compose logs -f trainer api dashboard mlflow

test:
	python -m pytest -q

train-local:   ## Train without Docker (tracks to ./mlflow.db)
	PYTHONPATH=src python -m retail_forecast.pipeline

api-local:
	PYTHONPATH=src uvicorn retail_forecast.api:app --reload --port 8000

dashboard-local:
	cd dashboard && API_URL=http://localhost:8000 streamlit run app.py

clean:         ## Remove generated data/outputs and all MLflow volumes
	docker compose down -v
	rm -rf outputs/*.csv outputs/*.json outputs/analytics mlflow.db mlruns
