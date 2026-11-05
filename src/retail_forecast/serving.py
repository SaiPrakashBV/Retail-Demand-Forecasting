"""MLflow pyfunc wrapper so the registered model scores raw feature rows directly.

``mlflow.pyfunc.load_model("models:/retail-demand-xgb@champion").predict(df)``
accepts a DataFrame with the columns in ``features.FEATURES`` where product_id and
category are plain strings; the wrapper restores the training category levels.
"""

from __future__ import annotations

import json

import mlflow.pyfunc
import numpy as np
import pandas as pd


class DemandModel(mlflow.pyfunc.PythonModel):
    def load_context(self, context):
        from xgboost import XGBRegressor

        self.model = XGBRegressor()
        self.model.load_model(context.artifacts["xgb_model"])
        with open(context.artifacts["metadata"]) as f:
            meta = json.load(f)
        self.features = meta["features"]
        self.categories = meta["categories"]

    def predict(self, context, model_input: pd.DataFrame, params=None):
        X = model_input[self.features].copy()
        for col, levels in self.categories.items():
            X[col] = pd.Categorical(X[col].astype(str), categories=levels)
        return np.clip(self.model.predict(X), 0, None)
