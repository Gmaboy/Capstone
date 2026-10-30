"""Explainability outputs: permutation importance and forecast breakdown (spec 5.4)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from statsmodels.tsa.seasonal import STL

from tools.model.demand import FEATURES, DemandResult
from tools.model.forecast import CANDIDATES, _extrapolate_customers, _ts, forecast_monthly

STEPS = 24
START = (2026, 1)


def permutation_importance_table(result: DemandResult, features: pd.DataFrame, test_year: int = 2025) -> pd.DataFrame:
    """Permutation importance of the selected model on the test year."""
    test = features[features["date"].dt.year == test_year]
    r = permutation_importance(
        result.model, test[FEATURES], test["demand_level"],
        n_repeats=10, random_state=42, scoring="f1_macro",
    )
    return (
        pd.DataFrame({"feature": FEATURES, "importance": r.importances_mean.astype(float)})
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )


def _index(n_fc: int, series: pd.Series) -> pd.DatetimeIndex:
    last = _ts(series).index[-1]
    return pd.date_range(last + pd.offsets.MonthBegin(1), periods=n_fc, freq="MS")


def _components(series: pd.Series, customers: pd.Series, model_name: str):
    """Return (trend, seasonality, customer_growth) arrays for the 24 forecast months."""
    n = STEPS
    if model_name in ("holt_winters_add", "holt_winters_mul"):
        res = CANDIDATES[model_name](series, customers).res
        point = np.asarray(res.forecast(n), dtype=float)
        h = np.arange(1, n + 1)
        base = float(np.asarray(res.level)[-1]) + h * float(np.asarray(res.trend)[-1])  # level + trend
        return base, point - base, np.zeros(n)
    if model_name == "regression":
        model = CANDIDATES[model_name](series, customers)
        beta = np.asarray(model.res.params)
        idx = _index(n, series)
        cust_f = np.asarray(_extrapolate_customers(model.cust, n), dtype=float)
        t = np.arange(model.n, model.n + n, dtype=float)
        months = np.asarray(idx.month)
        dummies = np.column_stack([(months == m).astype(float) for m in range(2, 13)])
        cust_last = float(model.cust.iloc[-1])
        trend = beta[0] + beta[1] * t + beta[2] * cust_last
        growth = beta[2] * (cust_f - cust_last)
        return trend, dummies @ beta[3:], growth
    # sarima / seasonal_naive: STL on history + point forecast
    point = forecast_monthly(series, customers, model_name, START, n)["forecast_mwh"].to_numpy()
    hist = _ts(series)
    full = pd.concat([hist, pd.Series(point, index=_index(n, series))])
    full.index = pd.DatetimeIndex(full.index, freq="MS")
    stl = STL(full, period=12, robust=True).fit()
    return stl.trend.to_numpy()[-n:], stl.seasonal.to_numpy()[-n:], np.zeros(n)


def forecast_breakdown(series: pd.Series, customers: pd.Series, model_name: str) -> pd.DataFrame:
    """trend / seasonality / customer_growth contributions for 2026-01..2027-12."""
    trend, seas, growth = _components(series, customers, model_name)
    idx = _index(STEPS, series)
    return pd.DataFrame({
        "year": idx.year, "month": idx.month,
        "trend": trend, "seasonality": seas, "customer_growth": growth,
    })
