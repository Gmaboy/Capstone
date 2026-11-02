# Hybrid BLSTM–SARIMA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a residual Hybrid BLSTM–SARIMA as a sixth monthly-energy candidate that competes in the existing rolling-origin backtest.

**Architecture:** `HybridBlstmSarima` wraps the existing `Sarima`. It trains an ensemble of 5 tiny PyTorch bidirectional LSTMs on SARIMA's scaled in-sample residuals and adds their recursive residual forecast to SARIMA's forecast. It registers in `CANDIDATES` only when torch imports. Everything downstream (backtest, selection, training, reports) iterates `CANDIDATES` unchanged.

**Tech Stack:** Python 3.12, PyTorch (CPU), statsmodels, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-11-02-hybrid-blstm-sarima-design.md`

## Global Constraints

- Candidate key: `hybrid_blstm_sarima`. Display label: `Hybrid BLSTM–SARIMA`.
- `LOOKBACK = 6`, `HIDDEN = 8` (per direction, 1 layer), `EPOCHS = 300` full batch, Adam lr `0.01`, MSE, `SEEDS = (42, 43, 44, 45, 46)`, `torch.set_num_threads(1)`, `MIN_WINDOWS = 8`, `BURN_IN = 13`.
- `select_model`, `nested_metric`, `backtest` and the baseline rule are not modified.
- `torch` goes in `requirements-dev.txt` only; `requirements.txt` stays Flask-only.
- Training must still run when torch is absent: the hybrid is simply missing from `CANDIDATES`.
- The same input gives the same forecast (atol 1e-6).

## Review Focus

1. A constant residual series (std 0) must not divide by zero. The scale floor of 1e-9 applies, and the correction is ≈ 0. → Task 1, `test_constant_residuals_give_sarima`.
2. A non-finite network output must not poison the forecast. The correction for that step is 0. → Task 1, `test_nonfinite_correction_is_zeroed`.
3. Global torch state must not leak between fits, since a seed set inside one fit affects later random draws. Use a local `torch.Generator` or re-seed per network, and test it with the determinism test after an unrelated `torch.rand` call. → Task 1, `test_deterministic`.
4. `joblib.dump` of a fitted hybrid must round-trip, because `train()` dumps the winner. → Task 1, `test_pickle_roundtrip`.
5. The existing `tests/test_forecast.py::test_backtest_has_two_folds_per_model` compares against `set(CANDIDATES)`. It must pass both with and without torch. → Task 1, Step 6.

---

### Task 1: `HybridBlstmSarima` candidate

**Files:**
- Modify: `tools/model/forecast.py` (add the optional torch import near the top, the class after `Sarima`, and the `CANDIDATES` entry)
- Modify: `requirements-dev.txt` (add `torch` with a pinned CPU version that installs on Python 3.12 Windows)
- Create: `tests/test_hybrid_blstm.py`

**Interfaces:**
- Consumes: `Sarima(y, customers)` with `.res` (statsmodels results, `.resid`) and `.predict(steps) -> DataFrame`; `_frame(index, point, lo80, hi80, lo95, hi95)`; `_ts`; `SERIES`, `CUSTOMERS` from `tests.conftest`.
- Produces:
  - `TORCH_AVAILABLE: bool`
  - `class HybridBlstmSarima(y: pd.Series, customers: pd.Series)` with these attributes:
    - `.sarima: Sarima`
    - `.nets: list` (empty when skipped)
    - `.scale: float`
    - `.last_window: np.ndarray` (scaled, length `LOOKBACK`)
  - `.predict(steps: int, exog_future=None) -> pd.DataFrame`
  - `HybridBlstmSarima._correction(steps: int) -> np.ndarray` (un-scaled MWh, length `steps`)
  - `CANDIDATES["hybrid_blstm_sarima"]`, present only if `TORCH_AVAILABLE`

- [ ] **Step 1: Install torch in the project venv**

Run: `.venv/Scripts/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu`
Expected: `python -c "import torch; print(torch.__version__)"` prints a version. Pin that exact version in `requirements-dev.txt` as `torch==<version>`, with a comment line above it: `# CPU build: pip install -r requirements-dev.txt --extra-index-url https://download.pytorch.org/whl/cpu`.

- [ ] **Step 2: Write the failing tests** in `tests/test_hybrid_blstm.py`

```python
import joblib
import numpy as np
import pandas as pd
import pytest

from tests.conftest import CUSTOMERS, SERIES
import tools.model.forecast as fm

torch_tests = pytest.mark.skipif(not fm.TORCH_AVAILABLE, reason="torch not installed")
COLS = ["forecast_mwh", "lo80", "hi80", "lo95", "hi95"]

@torch_tests
def test_shape_and_interval_order():
    fc = fm.HybridBlstmSarima(SERIES, CUSTOMERS).predict(24)
    assert list(fc.columns) == COLS and len(fc) == 24
    assert (fc.lo95 <= fc.lo80).all() and (fc.lo80 <= fc.forecast_mwh).all()
    assert (fc.forecast_mwh <= fc.hi80).all() and (fc.hi80 <= fc.hi95).all()

@torch_tests
def test_deterministic():
    a = fm.HybridBlstmSarima(SERIES, CUSTOMERS).predict(24).forecast_mwh
    import torch; torch.rand(5)  # disturb global RNG
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
    # The real fit, but with residuals forced to zero: the scale floor applies and the correction is 0.
    ...  # build via monkeypatching Sarima.res.resid to zeros; assert np.allclose(h._correction(12), 0, atol=1e-6)

@torch_tests
def test_nonfinite_correction_is_zeroed(monkeypatch):
    h = fm.HybridBlstmSarima(SERIES, CUSTOMERS)
    monkeypatch.setattr(h, "nets", [lambda x: x * float("nan")])
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
```

For `test_constant_residuals_give_sarima`, the implementer writes the body. Patch `fm.Sarima.__init__`, or wrap it, so that `.res.resid` returns zeros of the same length. Then fit the hybrid and assert that `_correction(12)` is all ≈ 0 and finite. `nets` should be a list of callables taking a `(1, LOOKBACK, 1)` float tensor and returning `(1, 1)`. That keeps `test_nonfinite_correction_is_zeroed` valid, and `_correction` calls each net under `torch.no_grad()`.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_hybrid_blstm.py -v`
Expected: FAIL with `AttributeError: module 'tools.model.forecast' has no attribute 'TORCH_AVAILABLE'`.

- [ ] **Step 4: Implement in `tools/model/forecast.py`**

- Put the optional import at module top:
  ```python
  try:
      import torch
      from torch import nn
      TORCH_AVAILABLE = True
  except ImportError:
      TORCH_AVAILABLE = False
  ```
- Define the module constants from Global Constraints.
- Define the network `_Blstm(nn.Module)` at module level so it pickles: `nn.LSTM(1, HIDDEN, batch_first=True, bidirectional=True)` followed by `nn.Linear(2 * HIDDEN, 1)` on `out[:, -1, :]`.
- `__init__`:
  1. `resid = np.asarray(self.sarima.res.resid)[BURN_IN:]`.
  2. `self.scale = max(float(np.std(resid, ddof=1)), 1e-9)` when there are at least 2 residuals, otherwise 1.0. The residuals are already centred, so the mean is 0.
  3. Build the windows. If there are fewer than `MIN_WINDOWS`, set `nets = []`.
  4. Otherwise train one network per seed:
     - call `torch.manual_seed(seed)` immediately before building that network;
     - wrap all training in `torch.set_num_threads(1)`, restoring the previous thread count afterwards;
     - call `.eval()` on each network after training.
  5. Store `last_window = scaled residuals[-LOOKBACK:]`. When there are fewer residuals, left-pad it with zeros.
- `_correction(steps)`:
  - Run the recursive loop with the window as `(1, LOOKBACK, 1)` float32.
  - Each step's prediction is the mean of `float(net(x))` over `nets`.
  - A non-finite value becomes 0.
  - Append the prediction to the window, and return the predictions × `scale`.
  - Return `np.zeros(steps)` when `nets` is empty.
- `predict`:
  - `base = self.sarima.predict(steps)` and `c = self._correction(steps)`.
  - `return _frame(base.index, base.forecast_mwh + c, base.lo80 + c, base.hi80 + c, base.lo95 + c, base.hi95 + c)`.
- Register: `if TORCH_AVAILABLE: CANDIDATES["hybrid_blstm_sarima"] = HybridBlstmSarima`.

- [ ] **Step 5: Run the new tests**

Run: `.venv/Scripts/python -m pytest tests/test_hybrid_blstm.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the existing model tests**

Run: `.venv/Scripts/python -m pytest tests/test_forecast.py tests/test_train.py -q`
Expected: all PASS. If `test_backtest_does_not_leak_test_year` or another test hard-codes the five model names, update it to use `set(fm.CANDIDATES)`. Do not change any assertion about selection.

- [ ] **Step 7: Commit**

```bash
git add tools/model/forecast.py requirements-dev.txt tests/test_hybrid_blstm.py tests/test_forecast.py
git commit -m "feat(forecast): add hybrid BLSTM-SARIMA backtest candidate"
```

---

### Task 2: Labels and wording

**Files:**
- Modify: `reports.html`, in `renderBacktest` around line 195
- Modify: `about.html`, at line 31
- Modify: `README.md`, around line 76

**Interfaces:**
- Consumes: the model key `hybrid_blstm_sarima` from Task 1.
- Produces: nothing used later.

- [ ] **Step 1: Add a model-name label map to `reports.html`.** Define `const MODEL_LABELS = { hybrid_blstm_sarima: 'Hybrid BLSTM–SARIMA', sarima: 'SARIMA' };` and `const modelLabel = m => MODEL_LABELS[m] || ElectroAPI.titleCase(m);`. Use `modelLabel` in place of the three `ElectroAPI.titleCase(...)` calls for model names in `renderBacktest`: the row name, `backtestSub` and `nestedNote`.
- [ ] **Step 2: Update the model list in `about.html`.** It becomes: "(SARIMA, a hybrid BLSTM–SARIMA that adds a bidirectional LSTM trained on SARIMA's errors, Holt-Winters, regression, and a seasonal-naive baseline)".
- [ ] **Step 3: Add the CPU-wheel note to `README.md`.** Directly under the `pip install -r requirements-dev.txt` line, add: "PyTorch (CPU) is needed only for the hybrid BLSTM–SARIMA model; install with `--extra-index-url https://download.pytorch.org/whl/cpu`. Without it, training skips that model."
- [ ] **Step 4: Verify.** Run `.venv/Scripts/python -m pytest tests/test_demo_db.py tests/test_api.py -q` and expect PASS. Open `/reports.html` and `/about.html` in the local preview with no console errors.
- [ ] **Step 5: Commit** with `git commit -m "docs(ui): show Hybrid BLSTM–SARIMA in reports and about"`.

---

### Task 3: Retrain and check the results

**Files:**
- Modified by the run: the local `database/*.db`, `models/`, `reports/`. These are git-ignored or already tracked as artefacts, so commit only what is already tracked.

- [ ] **Step 1: Retrain.** Use the project's existing training command (see the README training section). Expected: it finishes, and the stored monthly-energy run's `metrics.backtest` contains `hybrid_blstm_sarima` rows for 2024 and 2025.
- [ ] **Step 2: Check.** Open the Reports page locally. The backtest table lists "Hybrid BLSTM–SARIMA" with its 2024, 2025 and mean MAPE. Record the selected model and the hybrid's mean MAPE against SARIMA's, for the user's paper.
- [ ] **Step 3: Run the full suite.** Run `.venv/Scripts/python -m pytest -q` and expect all pass.
- [ ] **Step 4: Commit any tracked artefact changes** (for example the `reports/*.png` files) with `git commit -m "chore(model): retrain with hybrid BLSTM-SARIMA candidate"`.
- [ ] **Step 5: Do not rebuild `deploy/demo.db` or redeploy Vercel without asking the user.** Report that both are needed for the live demo to show the new row.
