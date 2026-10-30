"""High/Medium/Low daily demand classifier (spec 5.3).

Features use only strictly earlier days (shift(1)), so there is no look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from tools.synth.calendar import holidays

FEATURES = ["month", "day_of_week", "is_holiday", "prev_day_peak", "mean_7d_peak"]
LABELS = ["High", "Medium", "Low"]
PROB_COLS = {"High": "p_high", "Medium": "p_medium", "Low": "p_low"}
SEED = 42


@dataclass
class DemandResult:
    model_name: str
    model: Any
    metrics: dict
    predictions: pd.DataFrame


def build_features(daily: pd.DataFrame, cfg) -> pd.DataFrame:
    """Feature columns plus `date` and `demand_level`; the first 7 days are dropped."""
    d = daily.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)
    d["month"] = d.date.dt.month
    d["day_of_week"] = d.date.dt.day_of_week
    hol: set = set()
    for y in d.date.dt.year.unique():
        hol |= holidays(int(y), cfg)
    d["is_holiday"] = d.date.dt.date.isin(hol).astype(int)
    prev = d["peak_mw"].shift(1)
    d["prev_day_peak"] = prev
    d["mean_7d_peak"] = prev.rolling(7).mean()
    d = d.iloc[7:].reset_index(drop=True)
    return d[["date", *FEATURES, "demand_level"]]


def _candidates() -> dict[str, Any]:
    return {
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=SEED)),
        "random_forest": RandomForestClassifier(n_estimators=300, random_state=SEED),
    }


def _proba(model, X: pd.DataFrame) -> np.ndarray:
    """Probabilities with columns in LABELS order; absent classes get 0."""
    raw = model.predict_proba(X)
    classes = list(model.classes_)
    out = np.zeros((len(X), len(LABELS)))
    for j, lab in enumerate(LABELS):
        if lab in classes:
            out[:, j] = raw[:, classes.index(lab)]
    return out


def _scores(y_true, y_pred) -> dict:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)),
    }


def train_demand(features: pd.DataFrame, test_year: int = 2025) -> DemandResult:
    years = features["date"].dt.year
    train, test = features[years < test_year], features[years == test_year]
    if train.empty or test.empty:
        raise ValueError(f"need training rows before and rows within test year {test_year}")
    fitted, scores = {}, {}
    for name, model in _candidates().items():
        model.fit(train[FEATURES], train["demand_level"])
        fitted[name] = model
        scores[name] = _scores(test["demand_level"], model.predict(test[FEATURES]))
    best = max(fitted, key=lambda n: (scores[n]["macro_f1"], n == "logistic_regression"))
    model = fitted[best]
    pred = model.predict(test[FEATURES])
    proba = _proba(model, test[FEATURES])
    cm = confusion_matrix(test["demand_level"], pred, labels=LABELS)
    metrics = {
        **scores[best],
        "confusion_matrix": [[int(v) for v in row] for row in cm],
        "labels": list(LABELS),
        "baseline_accuracy": scores["logistic_regression"]["accuracy"],
        "baseline_macro_f1": scores["logistic_regression"]["macro_f1"],
    }
    predictions = pd.DataFrame({
        "date": test["date"].to_numpy(),
        "predicted_level": pred,
        PROB_COLS["High"]: proba[:, 0],
        PROB_COLS["Medium"]: proba[:, 1],
        PROB_COLS["Low"]: proba[:, 2],
        "actual_level": test["demand_level"].to_numpy(),
    })
    return DemandResult(best, model, metrics, predictions)
