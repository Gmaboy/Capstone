import numpy as np
import pandas as pd

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
    lfs = [sum(ANCHORS.monthly_mwh[(y, m)] for m in range(1, 13)) / (ANCHORS.peak_mw[y] * 8760) for y in ANCHORS.years]
    assert abs(p.peak_mw - 48000 / (np.mean(lfs) * 8760)) < 1e-6
    assert p.lo < p.peak_mw < p.hi
