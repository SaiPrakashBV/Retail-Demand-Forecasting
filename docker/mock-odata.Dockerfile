FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY mock_odata/requirements.txt .
RUN pip install -r requirements.txt
COPY mock_odata ./mock_odata
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8080
CMD ["uvicorn", "mock_odata.app:app", "--host", "0.0.0.0", "--port", "8080"]
