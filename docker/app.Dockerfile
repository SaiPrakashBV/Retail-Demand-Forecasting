# One image for both the training job and the forecast API.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    MPLCONFIGDIR=/tmp/matplotlib \
    GIT_PYTHON_REFRESH=quiet

# No apt packages needed: the XGBoost wheel ships its own OpenMP runtime.
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
RUN mkdir -p /app/data /app/outputs


CMD ["python", "-m", "retail_forecast.pipeline"]
