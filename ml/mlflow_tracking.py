"""MLflow tracking: parameters, metrics, artifacts and the forecasting models themselves.

Each training job writes one parent run per target (demand, price) with a nested run per
candidate model, so candidates can be compared side by side in the MLflow UI.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import mlflow  # noqa: E402
import pandas as pd  # noqa: E402
from mlflow.models import infer_signature  # noqa: E402
from mlflow.pyfunc import PythonModel  # noqa: E402

log = logging.getLogger(__name__)
ML_DIR = Path(__file__).resolve().parent

SURFACE, TEXT, TEXT_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]


class TrackingUnavailable(RuntimeError):
    pass


def setup(tracking_uri: str, timeout: int = 90) -> None:
    if tracking_uri.startswith("http"):
        deadline = time.time() + timeout
        while True:
            try:
                with urllib.request.urlopen(f"{tracking_uri.rstrip('/')}/health", timeout=5):
                    break
            except OSError as exc:
                if time.time() > deadline:
                    raise TrackingUnavailable(f"MLflow tracking server at {tracking_uri} is not reachable "
                                              f"({exc}). Check that the mlflow service is running.") from exc
                time.sleep(3)
    mlflow.set_tracking_uri(tracking_uri)


@contextmanager
def parent_run(experiment: str, run_name: str, tags: dict):
    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name, tags=tags) as run:
        yield run


def log_candidate(name: str, params: dict, overall: dict, fold_metrics: pd.DataFrame,
                  per_product: pd.DataFrame, selected: bool) -> str:
    with mlflow.start_run(run_name=name, nested=True, tags={"candidate": name, "selected": str(selected).lower()}) as r:
        mlflow.log_params({k: str(v)[:250] for k, v in params.items()})
        mlflow.log_metrics({f"backtest_{k}": float(v) for k, v in overall.items() if pd.notna(v)})
        for row in fold_metrics[fold_metrics["model"] == name].itertuples():
            mlflow.log_metrics({"fold_wape": float(row.wape), "fold_mae": float(row.mae),
                                "fold_mape": float(row.mape)}, step=int(row.fold))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "per_product_metrics.csv"
            per_product.to_csv(p, index=False)
            mlflow.log_artifact(str(p))
        return r.info.run_id


def _style(ax, title: str, ylabel: str = "") -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=TEXT, fontsize=12, fontweight="semibold")
    ax.set_ylabel(ylabel, color=TEXT_2)
    ax.tick_params(colors=TEXT_2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


def backtest_chart(pred: pd.DataFrame, actual: str, forecast: str, models: list[str], title: str,
                   ylabel: str, agg: str = "sum") -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 4), dpi=120)
    fig.patch.set_facecolor(SURFACE)
    base = pred[pred["model"] == models[0]].groupby("date")[actual].agg(agg)
    ax.plot(base.index, base.values, color=TEXT, linewidth=1.6, label="Actual")
    for i, m in enumerate(models):
        s = pred[pred["model"] == m].groupby("date")[forecast].agg(agg)
        ax.plot(s.index, s.values, color=SERIES[i % len(SERIES)], linewidth=1.6, label=m)
    _style(ax, title, ylabel)
    ax.legend(frameon=False, labelcolor=TEXT_2, fontsize=9, loc="upper left")
    fig.tight_layout()
    return fig


def importance_chart(importance: pd.Series, top: int = 15) -> plt.Figure:
    imp = importance.head(top)[::-1]
    fig, ax = plt.subplots(figsize=(8, 5), dpi=120)
    fig.patch.set_facecolor(SURFACE)
    ax.barh(imp.index, imp.values, color=SERIES[0], height=0.6)
    _style(ax, f"Top {top} features by gain")
    ax.grid(axis="x", color=GRID)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    return fig


class ForecasterPyfunc(PythonModel):
    """Self-contained forecaster: ``predict(DataFrame(sku=[...]))`` -> next ``horizon`` days.

    Holds the fitted model plus the history it needs (lags for XGBoost, nothing for Prophet).
    """

    def __init__(self, kind: str, model, history: pd.DataFrame, horizon: int):
        self.kind, self.model, self.history, self.horizon = kind, model, history, horizon

    def predict(self, context, model_input: pd.DataFrame, params=None):
        horizon = int((params or {}).get("horizon", self.horizon))
        skus = set(model_input["sku"].astype(str)) if "sku" in model_input and len(model_input) else None
        hist = self.history if skus is None else self.history[self.history["sku"].astype(str).isin(skus)]
        if self.kind == "demand" and hasattr(self.model, "forecast_from_fitted"):
            out = self.model.forecast_from_fitted(hist, horizon)
        else:
            out = self.model.forecast(hist, horizon)
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
        return out.reset_index(drop=True)


def log_forecaster(kind: str, model, history: pd.DataFrame, horizon: int, registered_name: str,
                   example_skus: list[str]) -> tuple[str, str]:
    """Log + register the selected model; returns (model uri, registered version)."""
    wrapper = ForecasterPyfunc(kind, model, history, horizon)
    example = pd.DataFrame({"sku": example_skus[:2]})
    output = wrapper.predict(None, example)
    info = mlflow.pyfunc.log_model(
        name="model", python_model=wrapper, code_paths=[str(ML_DIR)],
        signature=infer_signature(example, output), input_example=example,
        registered_model_name=registered_name,
        pip_requirements=_requirements(),
    )
    return info.model_uri, str(info.registered_model_version)


def _requirements() -> list[str]:
    import numpy
    import prophet
    import xgboost

    return [f"mlflow=={mlflow.__version__}", f"pandas=={pd.__version__}", f"numpy=={numpy.__version__}",
            f"xgboost=={xgboost.__version__}", f"prophet=={prophet.__version__}", "holidays", "joblib"]


def log_figure(fig: plt.Figure, path: str) -> None:
    mlflow.log_figure(fig, path)
    plt.close(fig)


def log_frame(df: pd.DataFrame, path: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / Path(path).name
        df.to_csv(p, index=False)
        mlflow.log_artifact(str(p), str(Path(path).parent) if Path(path).parent != Path(".") else None)


def log_json(obj: dict, path: str) -> None:
    mlflow.log_text(json.dumps(obj, indent=2, default=str), path)
