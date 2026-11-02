"""Monthly residential energy forecast (MWh) and annual coincident-peak model.

Trained and evaluated on the real 72 monthly values (2020-2025) only.
"""
from __future__ import annotations

import calendar
import warnings
from contextlib import contextmanager
from dataclasses import replace
from typing import Callable, Protocol

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

from tools.common.anchors import Anchors
from tools.synth.config import SynthConfig
from tools.synth.customers import monthly_customers

try:  # optional: only training needs torch; the hybrid candidate is skipped without it
    import torch
    from torch import nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

Z80, Z95 = 1.2815515655446004, 1.959963984540054
SIM_REPS = 1000
SIM_SEED = 42


class FittedModel(Protocol):
    def predict(self, steps: int, exog_future: pd.Series | None = None) -> pd.DataFrame: ...


def real_series(anchors: Anchors, cfg: SynthConfig) -> tuple[pd.Series, pd.Series]:
    """The 72 real monthly MWh values and aligned monthly customer counts."""
    cust = monthly_customers(anchors, replace(cfg, years=list(anchors.years)))
    keys = sorted(anchors.monthly_mwh)
    idx = pd.PeriodIndex([pd.Period(year=y, month=m, freq="M") for y, m in keys])
    series = pd.Series([anchors.monthly_mwh[k] for k in keys], index=idx, name="mwh")
    customers = pd.Series([float(cust[k]) for k in keys], index=idx, name="customers")
    return series, customers


def _ts(s: pd.Series) -> pd.Series:
    """Period-indexed series -> month-start DatetimeIndex series."""
    out = s.copy()
    if isinstance(out.index, pd.PeriodIndex):
        out.index = out.index.to_timestamp(how="start")
    out.index = pd.DatetimeIndex(out.index, freq="MS")
    return out


def _future_index(last: pd.Timestamp, steps: int) -> pd.DatetimeIndex:
    return pd.date_range(last + pd.offsets.MonthBegin(1), periods=steps, freq="MS")


def _frame(index, point, lo80, hi80, lo95, hi95) -> pd.DataFrame:
    """Build the output frame and enforce lo95 <= lo80 <= point <= hi80 <= hi95."""
    point = np.asarray(point, dtype=float)
    lo80 = np.minimum(np.asarray(lo80, dtype=float), point)
    hi80 = np.maximum(np.asarray(hi80, dtype=float), point)
    lo95 = np.minimum(np.asarray(lo95, dtype=float), lo80)
    hi95 = np.maximum(np.asarray(hi95, dtype=float), hi80)
    return pd.DataFrame(
        {"forecast_mwh": point, "lo80": lo80, "hi80": hi80, "lo95": lo95, "hi95": hi95},
        index=index,
    )


def _extrapolate_customers(cust: pd.Series, steps: int) -> pd.Series:
    """Linear extension using the last 12 months' growth (last training year)."""
    per_month = (cust.iloc[-1] - cust.iloc[-13]) / 12.0
    idx = _future_index(cust.index[-1], steps)
    return pd.Series(cust.iloc[-1] + per_month * np.arange(1, steps + 1), index=idx)


# ---------------------------------------------------------------- models
class SeasonalNaive:
    def __init__(self, y: pd.Series, customers: pd.Series):
        y = _ts(y)
        self.y = y
        diffs = (y - y.shift(12)).dropna()
        self.sigma = float(diffs.std(ddof=1))

    def predict(self, steps: int, exog_future: pd.Series | None = None) -> pd.DataFrame:
        last12 = self.y.iloc[-12:].to_numpy()
        point = np.array([last12[i % 12] for i in range(steps)])
        idx = _future_index(self.y.index[-1], steps)
        s = self.sigma
        return _frame(idx, point, point - Z80 * s, point + Z80 * s, point - Z95 * s, point + Z95 * s)


class HoltWinters:
    def __init__(self, y: pd.Series, customers: pd.Series, seasonal: str):
        self.seasonal = seasonal
        y = _ts(y)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.res = ExponentialSmoothing(
                y, trend="add", seasonal=seasonal, seasonal_periods=12
            ).fit()
        self.index = y.index

    def predict(self, steps: int, exog_future: pd.Series | None = None) -> pd.DataFrame:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            point = np.asarray(self.res.forecast(steps))
            sims = self.res.simulate(
                steps,
                repetitions=SIM_REPS,
                error="add" if self.seasonal == "add" else "mul",
                random_state=SIM_SEED,
            )
        q = np.percentile(np.asarray(sims), [2.5, 10, 90, 97.5], axis=1)
        idx = _future_index(self.index[-1], steps)
        return _frame(idx, point, q[1], q[2], q[0], q[3])


class Sarima:
    ORDERS = [(1, 1, 0), (0, 1, 1)]

    def __init__(self, y: pd.Series, customers: pd.Series):
        y = _ts(y)
        best = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for order in self.ORDERS:
                res = SARIMAX(y, order=order, seasonal_order=(0, 1, 1, 12)).fit(disp=False)
                if best is None or res.aic < best.aic:
                    best = res
        self.res = best
        self.index = y.index

    def predict(self, steps: int, exog_future: pd.Series | None = None) -> pd.DataFrame:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fc = self.res.get_forecast(steps)
            point = np.asarray(fc.predicted_mean)
            c80 = np.asarray(fc.conf_int(alpha=0.2))
            c95 = np.asarray(fc.conf_int(alpha=0.05))
        idx = _future_index(self.index[-1], steps)
        return _frame(idx, point, c80[:, 0], c80[:, 1], c95[:, 0], c95[:, 1])


LOOKBACK = 6
HIDDEN = 8
EPOCHS = 300
LR = 0.01
SEEDS = (42, 43, 44, 45, 46)
MIN_WINDOWS = 8
BURN_IN = 13  # residuals distorted by d=1, D=1, s=12 differencing

@contextmanager
def _single_thread():
    """Tiny networks run faster on one thread, and results are repeatable."""
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(threads)


if TORCH_AVAILABLE:
    class _Blstm(nn.Module):
        """One-layer bidirectional LSTM -> next scaled residual."""

        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(1, HIDDEN, batch_first=True, bidirectional=True)
            self.head = nn.Linear(2 * HIDDEN, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])


class HybridBlstmSarima:
    """Residual hybrid (Zhang 2003): SARIMA forecast + BLSTM forecast of SARIMA's residuals.

    Intervals are SARIMA's, shifted by the correction; they omit the BLSTM's own uncertainty.
    """

    def __init__(self, y: pd.Series, customers: pd.Series):
        self.sarima = Sarima(y, customers)
        resid = np.asarray(self.sarima.res.resid, dtype=float)[BURN_IN:]
        self.scale = max(float(np.std(resid, ddof=1)), 1e-9) if len(resid) >= 2 else 1.0
        z = resid / self.scale
        self.nets = []
        n_windows = len(z) - LOOKBACK
        if n_windows >= MIN_WINDOWS:
            X = np.stack([z[i:i + LOOKBACK] for i in range(n_windows)])
            self.nets = self._train(X, z[LOOKBACK:])
        window = z[-LOOKBACK:]
        self.last_window = np.concatenate([np.zeros(LOOKBACK - len(window)), window])

    @staticmethod
    def _train(X: np.ndarray, target: np.ndarray) -> list:
        xt = torch.tensor(X, dtype=torch.float32).unsqueeze(-1)
        yt = torch.tensor(target, dtype=torch.float32).unsqueeze(-1)
        nets = []
        with _single_thread():
            for seed in SEEDS:
                torch.manual_seed(seed)
                net = _Blstm()
                opt = torch.optim.Adam(net.parameters(), lr=LR)
                for _ in range(EPOCHS):
                    opt.zero_grad()
                    loss = nn.functional.mse_loss(net(xt), yt)
                    loss.backward()
                    opt.step()
                nets.append(net.eval())
        return nets

    def _correction(self, steps: int) -> np.ndarray:
        """Recursive residual forecast in MWh; zero when no networks were trained."""
        if not self.nets:
            return np.zeros(steps)
        window = list(self.last_window)
        out = []
        with torch.no_grad(), _single_thread():
            for _ in range(steps):
                x = torch.tensor(window[-LOOKBACK:], dtype=torch.float32).view(1, LOOKBACK, 1)
                step = float(np.mean([float(net(x)) for net in self.nets]))
                if not np.isfinite(step):
                    step = 0.0
                out.append(step)
                window.append(step)
        return np.asarray(out) * self.scale

    def predict(self, steps: int, exog_future: pd.Series | None = None) -> pd.DataFrame:
        base = self.sarima.predict(steps)
        c = self._correction(steps)
        return _frame(
            base.index, base.forecast_mwh + c,
            base.lo80 + c, base.hi80 + c, base.lo95 + c, base.hi95 + c,
        )


class Regression:
    """OLS: linear trend + month dummies + customers."""

    def __init__(self, y: pd.Series, customers: pd.Series):
        y = _ts(y)
        cust = _ts(customers).loc[y.index]
        self.cust = cust
        self.n = len(y)
        self.last = y.index[-1]
        X = self._design(y.index, np.arange(self.n), cust.to_numpy())
        self.res = sm.OLS(y.to_numpy(), X).fit()

    @staticmethod
    def _design(index: pd.DatetimeIndex, t: np.ndarray, cust: np.ndarray) -> np.ndarray:
        months = np.asarray(index.month)
        dummies = np.column_stack([(months == m).astype(float) for m in range(2, 13)])
        return np.column_stack([np.ones(len(t)), t.astype(float), cust.astype(float), dummies])

    def predict(self, steps: int, exog_future: pd.Series | None = None) -> pd.DataFrame:
        idx = _future_index(self.last, steps)
        if exog_future is None:
            exog_future = _extrapolate_customers(self.cust, steps)
        cust_f = np.asarray(exog_future, dtype=float)[:steps]
        X = self._design(idx, np.arange(self.n, self.n + steps), cust_f)
        pred = self.res.get_prediction(X)
        point = np.asarray(pred.predicted_mean)
        f80 = pred.summary_frame(alpha=0.2)
        f95 = pred.summary_frame(alpha=0.05)
        return _frame(
            idx, point,
            f80["obs_ci_lower"], f80["obs_ci_upper"],
            f95["obs_ci_lower"], f95["obs_ci_upper"],
        )


CANDIDATES: dict[str, Callable[[pd.Series, pd.Series], FittedModel]] = {
    "seasonal_naive": SeasonalNaive,
    "holt_winters_add": lambda y, c: HoltWinters(y, c, "add"),
    "holt_winters_mul": lambda y, c: HoltWinters(y, c, "mul"),
    "sarima": Sarima,
    "regression": Regression,
}
if TORCH_AVAILABLE:
    CANDIDATES["hybrid_blstm_sarima"] = HybridBlstmSarima


# ---------------------------------------------------------------- evaluation
def backtest(series: pd.Series, customers: pd.Series) -> pd.DataFrame:
    """Rolling-origin folds: train through 2023 -> test 2024; through 2024 -> test 2025.

    Each model sees training-period data only; regression extrapolates test-year
    customers from the last training year's growth, exactly as production does.
    """
    rows = []
    years = np.asarray(series.index.year)
    for test_year in (2024, 2025):
        train = series[years < test_year]
        test = series[years == test_year]
        cust_train = customers.loc[train.index]
        for name, make in CANDIDATES.items():
            fc = make(train, cust_train).predict(len(test), None)
            err = test.to_numpy() - fc["forecast_mwh"].to_numpy()
            mape = float(np.mean(np.abs(err) / test.to_numpy()) * 100.0)
            rmse = float(np.sqrt(np.mean(err**2)))
            rows.append((name, str(test_year), mape, rmse))
    return pd.DataFrame(rows, columns=["model_name", "fold", "mape", "rmse"])


def select_model(bt: pd.DataFrame) -> tuple[str, bool]:
    """Lowest mean MAPE; fall back to seasonal_naive unless the winner beats it."""
    means = bt.groupby("model_name")["mape"].mean()
    best = str(means.idxmin())
    if best == "seasonal_naive":
        return "seasonal_naive", False
    if "seasonal_naive" not in means.index:
        raise ValueError("backtest results must include seasonal_naive")
    baseline = means["seasonal_naive"]
    if means[best] < baseline:
        return best, True
    return "seasonal_naive", False


def forecast_monthly(
    series: pd.Series,
    customers: pd.Series,
    model_name: str,
    start: tuple[int, int] = (2026, 1),
    months: int = 24,
) -> pd.DataFrame:
    """Refit on all supplied months, then forecast `months` months from `start`."""
    model = CANDIDATES[model_name](series, customers)
    last = series.index[-1]
    last_ts = last.to_timestamp() if isinstance(last, pd.Period) else pd.Timestamp(last)
    gap = (start[0] - last_ts.year) * 12 + start[1] - last_ts.month - 1
    if gap < 0:
        raise ValueError("start must be after the last observed month")
    fc = model.predict(gap + months, None).iloc[gap:]
    out = fc.reset_index(drop=True)
    out.insert(0, "month", fc.index.month)
    out.insert(0, "year", fc.index.year)
    return out


def _hours(year: int) -> int:
    return 8784 if calendar.isleap(int(year)) else 8760


def forecast_peak(anchors: Anchors, monthly_fc: pd.DataFrame) -> pd.DataFrame:
    """peak_MW = annual_MWh / (LF * hours_in_year).

    LF_y = historical annual MWh / (coincident peak MW * hours in year y), using
    8784 h for leap years. Central value uses mean LF; lo uses max LF, hi uses min
    LF. The forecast year's own hours are used for the forecast peak.
    """
    lfs = np.array([
        sum(anchors.monthly_mwh[(y, m)] for m in range(1, 13)) / (anchors.peak_mw[y] * _hours(y))
        for y in anchors.years
    ])
    lf_mean, lf_max, lf_min = lfs.mean(), lfs.max(), lfs.min()
    rows = []
    for year, g in monthly_fc.groupby("year"):
        if len(g) != 12:
            raise ValueError(f"forecast year {year} has {len(g)} months, need 12")
        hours = _hours(year)
        mwh = float(g["forecast_mwh"].sum())
        rows.append((int(year), mwh / (lf_mean * hours), mwh / (lf_max * hours), mwh / (lf_min * hours)))
    return pd.DataFrame(rows, columns=["year", "peak_mw", "lo", "hi"])
