import joblib
import numpy as np
import pytest

import tools.model.forecast as fm
from tests.conftest import CUSTOMERS, SERIES

torch_tests = pytest.mark.skipif(not fm.TORCH_AVAILABLE, reason="torch not installed")
COLS = ["forecast_mwh", "lo80", "hi80", "lo95", "hi95"]


class _ZeroResid:
    """Statsmodels results proxy whose residuals are all zero."""

    def __init__(self, res):
        self._res = res
        self.resid = np.zeros(len(np.asarray(res.resid)))

    def __getattr__(self, name):
        return getattr(self._res, name)


@torch_tests
def test_shape_and_interval_order():
    fc = fm.HybridBlstmSarima(SERIES, CUSTOMERS).predict(24)
    assert list(fc.columns) == COLS and len(fc) == 24
    assert (fc.lo95 <= fc.lo80).all() and (fc.lo80 <= fc.forecast_mwh).all()
    assert (fc.forecast_mwh <= fc.hi80).all() and (fc.hi80 <= fc.hi95).all()


@torch_tests
def test_deterministic():
    import torch

    a = fm.HybridBlstmSarima(SERIES, CUSTOMERS).predict(24).forecast_mwh
    torch.rand(5)  # disturb the global RNG between fits
    b = fm.HybridBlstmSarima(SERIES, CUSTOMERS).predict(24).forecast_mwh
    assert np.allclose(a, b, atol=1e-6)


@torch_tests
def test_correction_changes_sarima():
    h = fm.HybridBlstmSarima(SERIES, CUSTOMERS).predict(24).forecast_mwh.to_numpy()
    s = fm.Sarima(SERIES, CUSTOMERS).predict(24).forecast_mwh.to_numpy()
    assert not np.allclose(h, s, atol=1e-3)


@torch_tests
def test_short_series_equals_sarima():
    short = SERIES.iloc[:24]  # 24 - 13 = 11 residuals -> 5 windows < MIN_WINDOWS
    h = fm.HybridBlstmSarima(short, CUSTOMERS.loc[short.index])
    assert h.nets == []
    s = fm.Sarima(short, CUSTOMERS.loc[short.index]).predict(12)
    assert np.allclose(h.predict(12).to_numpy(), s.to_numpy())


@torch_tests
def test_constant_residuals_give_sarima(monkeypatch):
    class ZeroSarima(fm.Sarima):
        def __init__(self, y, customers):
            super().__init__(y, customers)
            self.res = _ZeroResid(self.res)

    monkeypatch.setattr(fm, "Sarima", ZeroSarima)
    c = fm.HybridBlstmSarima(SERIES, CUSTOMERS)._correction(12)
    assert np.all(np.isfinite(c)) and np.allclose(c, 0, atol=1e-6)


@torch_tests
def test_nonfinite_correction_is_zeroed(monkeypatch):
    h = fm.HybridBlstmSarima(SERIES, CUSTOMERS)
    monkeypatch.setattr(h, "nets", [lambda x: x[:, -1, :] * float("nan")])
    assert np.all(h._correction(6) == 0)


@torch_tests
def test_pickle_roundtrip(tmp_path):
    h = fm.HybridBlstmSarima(SERIES, CUSTOMERS)
    joblib.dump(h, tmp_path / "h.joblib")
    h2 = joblib.load(tmp_path / "h.joblib")
    assert np.allclose(h.predict(12).to_numpy(), h2.predict(12).to_numpy())


@torch_tests
def test_backtest_scores_hybrid():
    bt = fm.backtest(SERIES, CUSTOMERS)
    rows = bt[bt.model_name == "hybrid_blstm_sarima"]
    assert set(rows.fold) == {"2024", "2025"} and np.isfinite(rows.mape).all()


def test_backtest_runs_without_torch(monkeypatch):
    monkeypatch.setattr(fm, "TORCH_AVAILABLE", False)
    monkeypatch.setattr(fm, "CANDIDATES", {k: v for k, v in fm.CANDIDATES.items() if k != "hybrid_blstm_sarima"})
    bt = fm.backtest(SERIES, CUSTOMERS)
    assert "hybrid_blstm_sarima" not in set(bt.model_name)
