"""Model registry: which registered version produced the current production forecasts.

Every training job registers its selected model. The ``production`` alias points at the
version whose forecasts are currently served; the previous production version is tagged so
it is easy to roll back or compare.
"""

from __future__ import annotations

from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

PRODUCTION = "production"


def current_production(name: str) -> str | None:
    try:
        return MlflowClient().get_model_version_by_alias(name, PRODUCTION).version
    except MlflowException:
        return None


def promote(name: str, version: str, model_type: str, metrics: dict, job_id: str) -> str | None:
    client = MlflowClient()
    previous = current_production(name)
    client.set_model_version_tag(name, version, "model_type", model_type)
    client.set_model_version_tag(name, version, "job_id", job_id)
    for k, v in metrics.items():
        client.set_model_version_tag(name, version, f"backtest_{k}", f"{v:.4f}")
    if previous and previous != version:
        client.set_model_version_tag(name, previous, "replaced_by", version)
    client.set_registered_model_alias(name, PRODUCTION, version)
    return previous
