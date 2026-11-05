# Backend API, forecast worker and database migrations share one image.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/backend MPLCONFIGDIR=/tmp/matplotlib GIT_PYTHON_REFRESH=quiet \
    MLFLOW_DISABLE_AGENT_HINT=1

WORKDIR /app
# No apt packages needed: XGBoost and Prophet wheels bundle OpenMP and CmdStan.
COPY backend/requirements.txt backend/requirements.txt
COPY ml/requirements.txt ml/requirements.txt
RUN pip install -r ml/requirements.txt

COPY database ./database
COPY backend ./backend
COPY ml ./ml

RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
