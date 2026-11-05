#!/usr/bin/env bash
# First-start helper: once the DAG is parsed, trigger the initial ingestion if it never ran.
set -euo pipefail
echo "Waiting for the retail_etl DAG to be parsed..."
for _ in $(seq 1 120); do
  if airflow dags details retail_etl >/dev/null 2>&1; then break; fi
  sleep 5
done
airflow dags unpause retail_etl >/dev/null 2>&1 || true
airflow dags unpause forecast_training >/dev/null 2>&1 || true
# Count run rows (the CLI can print warnings on stdout, so do not parse it as JSON).
runs=$(airflow dags list-runs retail_etl -o plain 2>/dev/null | grep -c "retail_etl" || true)
if [ "${runs:-0}" -eq 0 ]; then
  airflow dags trigger retail_etl -r "bootstrap__$(date -u +%Y%m%dT%H%M%S)"
  echo "Triggered the first retail_etl run."
else
  echo "retail_etl has ${runs} run(s) already; nothing to do."
fi
