FROM apache/airflow:3.3.2-python3.12
# The ETL task code only needs pandas, SQLAlchemy, psycopg2 and requests, which the
# official image already ships. DAGs and tasks are baked in (and bind-mounted in dev).
USER root
# Named volumes copy ownership from the image on first use, so create the work dirs here.
RUN mkdir -p /opt/airflow/etl-data /opt/airflow/incoming && chown -R airflow:root /opt/airflow/etl-data /opt/airflow/incoming
USER airflow
COPY --chown=airflow:root airflow/dags /opt/airflow/project/dags
COPY --chown=airflow:root airflow/tasks /opt/airflow/project/tasks
COPY --chown=airflow:root docker/airflow/bootstrap.sh /opt/airflow/bootstrap.sh
ENV PYTHONPATH=/opt/airflow/project AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/project/dags
