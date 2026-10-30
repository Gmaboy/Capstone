import json

import numpy as np
import pandas as pd
import pytest

from tests.conftest import CFG_SMALL, CUSTOMERS, SERIES, small_daily
from tools.model.demand import FEATURES, build_features, train_demand
from tools.model.explain import forecast_breakdown, permutation_importance_table
from tools.model.forecast import CANDIDATES, forecast_monthly
from tools.synth.config import load_config

CFG = load_config(CFG_SMALL)


def test_features_have_no_lookahead():
    daily = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=10), "peak_mw": range(10),
                          "demand_level": ["Low"] * 10, "year": 2025, "pct_of_annual_peak": 0.5})
    f = build_features(daily, CFG)
    row = f[f.date == pd.Timestamp("2025-01-09")].iloc[0]
    assert row.prev_day_peak == 7
    assert row.mean_7d_peak == np.mean([1, 2, 3, 4, 5, 6, 7])
    assert f.date.min() == pd.Timestamp("2025-01-08")  # first 7 days dropped


def test_calendar_features():
    f = build_features(small_daily(), CFG)
    jan1 = f[f.date == pd.Timestamp("2025-01-08")].iloc[0]
    assert jan1.month == 1 and jan1.day_of_week == 2  # Wednesday
    assert set(f.is_holiday.unique()) <= {0, 1}
    assert f[(f.date.dt.month == 12) & (f.date.dt.day == 25)].is_holiday.eq(1).all()


def test_train_demand_reports_metrics_on_test_year_only():
    r = train_demand(build_features(small_daily(), CFG), test_year=2025)
    assert set(r.predictions.date.dt.year) == {2025}
    assert 0 <= r.metrics["macro_f1"] <= 1
    assert r.model_name in {"logistic_regression", "random_forest"}
    p = r.predictions[["p_high", "p_medium", "p_low"]].sum(axis=1)
    assert np.allclose(p, 1)
    assert r.metrics["labels"] == ["High", "Medium", "Low"]
    assert np.array(r.metrics["confusion_matrix"]).shape == (3, 3)
    json.dumps(r.metrics)  # JSON-serializable


def test_importance_covers_all_features():
    r = train_demand(build_features(small_daily(), CFG), test_year=2025)
    imp = permutation_importance_table(r, build_features(small_daily(), CFG))
    assert list(imp.sort_values("feature").feature) == sorted(FEATURES)


@pytest.mark.parametrize("model_name", list(CANDIDATES))
def test_breakdown_sums_to_point_forecast(model_name):
    bd = forecast_breakdown(SERIES, CUSTOMERS, model_name)
    assert list(bd.columns) == ["year", "month", "trend", "seasonality", "customer_growth"]
    assert len(bd) == 24
    assert (bd.year.iloc[0], bd.month.iloc[0]) == (2026, 1)
    assert (bd.year.iloc[-1], bd.month.iloc[-1]) == (2027, 12)
    point = forecast_monthly(SERIES, CUSTOMERS, model_name)["forecast_mwh"].to_numpy()
    total = (bd.trend + bd.seasonality + bd.customer_growth).to_numpy()
    # Exact for HW/regression; STL residual makes sarima/seasonal_naive inexact: allow 5%.
    tol = 0.05 if model_name in {"sarima", "seasonal_naive"} else 0.01
    assert np.all(np.abs(total - point) / point < tol)
    if model_name != "regression":
        assert (bd.customer_growth == 0).all()
