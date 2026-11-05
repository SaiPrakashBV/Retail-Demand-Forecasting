FROM python:3.13-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN pip install mlflow==3.18.0 psycopg2-binary==2.9.11

EXPOSE 5000
