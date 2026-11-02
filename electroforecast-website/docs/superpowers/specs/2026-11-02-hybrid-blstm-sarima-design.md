# Hybrid BLSTM–SARIMA Forecasting Model — Design

- **Date:** 2026-11-02
- **Status:** Draft for review
- **Branch:** `feature/hybrid-blstm-sarima`

## 1. Purpose and context

The project title promises a *Hybrid BLSTM–SARIMA* forecaster, but
`tools/model/forecast.py` has no neural network. The monthly energy model is
chosen from five candidates (seasonal naive, Holt-Winters additive and
multiplicative, SARIMA, regression) by a rolling-origin backtest on the 72 real
GUIMELCO monthly values (2020–2025).

This design adds a real Hybrid BLSTM–SARIMA as a **sixth candidate that
competes on equal terms**. It is used only if it wins the same backtest. If it
loses, the reports show its score next to the others, and the paper says so.

### Success criteria

- `hybrid_blstm_sarima` appears in every backtest run, scored on both the 2024
  and 2025 folds with the same data the other candidates see.
- `select_model`, `nested_metric` and the baseline rule are unchanged; the
  hybrid gets no special treatment.
- Training is deterministic: the same data gives the same forecast.
- The website and the Vercel demo need no new dependency.
- If PyTorch is not installed, training still runs and simply leaves the
  hybrid out.

### Out of scope

- Changing how the winner is chosen, or forcing the hybrid to be selected.
- Hyperparameter search. The settings in §3.2 are fixed, to keep the backtest
  honest on so few points.
- Using the hybrid for daily demand classification or the peak forecast.

## 2. Approach

This is the residual hybrid of Zhang (2003):

1. Fit SARIMA, which captures the trend and the 12-month seasonal pattern.
2. Train a small bidirectional LSTM on SARIMA's in-sample **residuals**, to
   learn the non-linear pattern SARIMA misses.
3. Forecast = SARIMA forecast + BLSTM predicted residual.

The library is **PyTorch (CPU build)**. TensorFlow was rejected because it is a
heavier install with weaker Windows support. A hand-written NumPy LSTM was
rejected because it is harder to verify and to defend.

## 3. Components

### 3.1 `HybridBlstmSarima` in `tools/model/forecast.py`

It follows the existing `FittedModel` protocol:
`__init__(y, customers)` and `predict(steps, exog_future=None) -> DataFrame`
with the columns `forecast_mwh, lo80, hi80, lo95, hi95`, built with `_frame`.

**Fit**

1. `self.sarima = Sarima(y, customers)`, the existing class with the same
   order selection.
2. Residuals are `self.sarima.res.resid`. The first 13 values are dropped,
   because they are start-up values distorted by the differencing
   (d = 1, D = 1, s = 12).
3. Scale the residuals by their standard deviation, with mean 0 and a floor of
   1e-9.
4. Build supervised windows: input = the previous `LOOKBACK` scaled residuals,
   target = the next one.
5. Train `N_SEEDS` networks, one per seed, and keep all of them (an ensemble).

**Predict**

1. `base = self.sarima.predict(steps)`.
2. Starting from the last `LOOKBACK` residuals, predict the next residual as
   the mean of the ensemble's outputs, un-scale it, append it to the window,
   and repeat `steps` times. This is recursive forecasting.
3. `point = base.forecast_mwh + correction`.
4. Intervals: SARIMA's 80 % and 95 % bounds shifted by the same `correction`.
   This is stated as a limitation: the intervals do not include the BLSTM's
   own uncertainty.

### 3.2 Fixed settings (module constants)

| Constant | Value | Reason |
|---|---|---|
| `LOOKBACK` | 6 | The smallest fold has 48 − 13 = 35 residuals. Six gives 29 windows, while 12 would leave only 23. |
| `HIDDEN` | 8 per direction, 1 layer | Keeps parameters (≈ 600) small relative to the data |
| `EPOCHS` | 300, full batch | |
| Optimiser | Adam, lr 0.01, MSE loss | |
| `N_SEEDS` | 5 (seeds 42–46) | Averages out the run-to-run variation of tiny networks |
| Threads | `torch.set_num_threads(1)` | Needed for repeatable results |

Network: `nn.LSTM(1, HIDDEN, bidirectional=True, batch_first=True)`, followed
by `nn.Linear(2 * HIDDEN, 1)` on the last time step.

### 3.3 Optional dependency

- `torch` is imported inside a `try` block. The flag
  `TORCH_AVAILABLE` records whether it loaded.
- `hybrid_blstm_sarima` is added to `CANDIDATES` only when
  `TORCH_AVAILABLE` is true.
- `torch` (CPU) is added to `requirements-dev.txt` only.
  `requirements.txt`, which the Vercel deploy uses, stays Flask-only. The
  website reads saved forecasts and never loads a model.

### 3.4 Pipeline effects (no code change needed)

- `backtest`, `select_model`, `forecast_monthly`, `nested_metric` and
  `train()` all iterate over `CANDIDATES`, so they pick the hybrid up
  automatically.
- If the hybrid wins, `joblib.dump` saves it (PyTorch modules pickle), and
  `forecast_breakdown` uses the STL fallback that SARIMA already uses.
- The Reports backtest table lists every model in the stored metrics, so the
  hybrid shows up without UI changes. Its label is
  `ElectroAPI.titleCase('hybrid_blstm_sarima')`, which gives
  "Hybrid Blstm Sarima". A label map in `reports.html` makes it display as
  "Hybrid BLSTM–SARIMA".

### 3.5 Text updates

- `about.html`: list "a hybrid BLSTM–SARIMA (SARIMA plus a bidirectional LSTM
  on its residuals)" among the compared models.
- `README.md` (training section, if present): `pip install -r
  requirements-dev.txt` now includes PyTorch.

## 4. Error handling

- The training windows can come out fewer than 8, for example on a very short
  test fixture. When that happens the BLSTM step is skipped, the correction is
  0, and the hybrid equals SARIMA. No crash.
- If the BLSTM produces non-finite output, the correction is set to 0 for that
  step.

## 5. Testing — `tests/test_hybrid_blstm.py`

The whole file is skipped with `pytest.importorskip("torch")`, except the last
test.

1. **Shape and ordering:** `predict(24)` returns 24 rows with the five
   columns, and `lo95 ≤ lo80 ≤ forecast ≤ hi80 ≤ hi95` holds for every row.
2. **Deterministic:** fitting twice on the same series gives identical
   `forecast_mwh` values (`np.allclose`, atol 1e-6).
3. **Correction is used:** the hybrid's point forecast differs from plain
   `Sarima` on the real series. This proves the BLSTM step ran.
4. **Short series:** a series too short for 8 windows returns SARIMA's
   forecast unchanged.
5. **Backtest includes it:** `backtest(series, customers)` has rows
   for `hybrid_blstm_sarima` on both folds, with finite MAPE.
6. **Without torch:** with `TORCH_AVAILABLE` monkeypatched to false and the
   candidate removed, `backtest` still runs. This test does not need torch.

The existing tests in `tests/test_forecast.py` and `tests/test_train.py` must
still pass.

## 6. Risks

- **The hybrid will probably not beat SARIMA.** Only 29–41 residual windows
  are available per fold. That is an accepted, reportable outcome, not a
  defect.
- **Training time:** 5 networks × 300 epochs on fewer than 60 samples takes
  seconds per fit, and the backtest adds 2 more fits. Acceptable.
- **Install size:** the PyTorch CPU wheel is about 200 MB, and only on the
  machine used for training.
