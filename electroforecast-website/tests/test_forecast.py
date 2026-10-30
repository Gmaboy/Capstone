import calendar

import numpy as np
import pandas as pd
import pytest

from tests.conftest import ANCHORS, CUSTOMERS, SERIES
from tools.model.forecast import (
    CANDIDATES,
    backtest,
    forecast_monthly,
    forecast_peak,
    select_model,
)


def test_backtest_has_two_folds_per_model():
    bt = backtest(SERIES, CUSTOMERS)
    assert set(bt.fold) == {"2024", "2025"}
    assert set(bt.model_name) == set(CANDIDATES)
    assert (bt.mape > 0).all()


def test_select_model_falls_back_to_baseline():
    bt = pd.DataFrame({"model_name": ["seasonal_naive", "x"], "fold": ["2024", "2024"], "mape": [5.0, 6.0], "rmse": [1, 1]})
    assert select_model(bt) == ("seasonal_naive", False)


def test_forecast_shape_and_interval_order():
    fc = forecast_monthly(SERIES, CUSTOMERS, "holt_winters_add")
    assert len(fc) == 24 and (fc.year.iloc[0], fc.month.iloc[0]) == (2026, 1)
    assert (fc.lo95 <= fc.lo80).all() and (fc.lo80 <= fc.forecast_mwh).all()
    assert (fc.forecast_mwh <= fc.hi80).all() and (fc.hi80 <= fc.hi95).all()


def test_peak_formula():
    fc = pd.DataFrame({"year": [2026] * 12, "month": range(1, 13), "forecast_mwh": [4000.0] * 12,
                       "lo80": 0, "hi80": 0, "lo95": 0, "hi95": 0})
    p = forecast_peak(ANCHORS, fc).iloc[0]
    lfs = [sum(ANCHORS.monthly_mwh[(y, m)] for m in range(1, 13)) / (ANCHORS.peak_mw[y] * (8784 if calendar.isleap(y) else 8760)) for y in ANCHORS.years]
    assert abs(p.peak_mw - 48000 / (np.mean(lfs) * 8760)) < 1e-6
    assert p.lo < p.peak_mw < p.hi


def test_peak_requires_full_year():
    fc = pd.DataFrame({"year": [2026] * 6, "month": range(1, 7), "forecast_mwh": [4000.0] * 6})
    with pytest.raises(ValueError):
        forecast_peak(ANCHORS, fc)


def test_select_model_requires_baseline():
    bt = pd.DataFrame({"model_name": ["a", "b"], "fold": ["2024"] * 2, "mape": [5.0, 6.0], "rmse": [1, 1]})
    with pytest.raises(ValueError):
        select_model(bt)


def test_backtest_does_not_leak_test_year():
    years = np.asarray(SERIES.index.year)
    base = backtest(SERIES, CUSTOMERS)
    for test_year in (2024, 2025):
        perturbed = SERIES.copy()
        perturbed[years >= test_year] *= 10
        # fold test_year forecasts depend only on data before test_year, so
        # recompute the forecast directly and compare against the clean series
        train_clean = SERIES[years < test_year]
        train_pert = perturbed[years < test_year]
        for name, make in CANDIDATES.items():
            a = make(train_clean, CUSTOMERS.loc[train_clean.index]).predict(12, None)
            b = make(train_pert, CUSTOMERS.loc[train_pert.index]).predict(12, None)
            pd.testing.assert_frame_equal(a, b)
        # and the 2024 fold must be unchanged when only 2025 is perturbed
    p25 = SERIES.copy()
    p25[years == 2025] *= 10
    bt25 = backtest(p25, CUSTOMERS)
    f24 = lambda d: d[d.fold == "2024"].reset_index(drop=True)
    pd.testing.assert_frame_equal(f24(base), f24(bt25))


def test_seasonal_naive_metrics_match_hand_computation():
    bt = backtest(SERIES, CUSTOMERS)
    row = bt[(bt.model_name == "seasonal_naive") & (bt.fold == "2025")].iloc[0]
    actual = np.array([ANCHORS.monthly_mwh[(2025, m)] for m in range(1, 13)])
    pred = np.array([ANCHORS.monthly_mwh[(2024, m)] for m in range(1, 13)])
    assert row.mape == pytest.approx(np.mean(np.abs(actual - pred) / actual) * 100)
    assert row.rmse == pytest.approx(np.sqrt(np.mean((actual - pred) ** 2)))
