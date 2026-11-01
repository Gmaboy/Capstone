from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from tools.common.anchors import Anchors
from tools.synth.calendar import holidays
from tools.synth.households import HouseholdType, type_mix


def calibrate_peak(day_energy, day_shapes, target_mw):
    def hourly(k):
        s = day_shapes ** k
        return day_energy[:, None] * s / s.sum(1, keepdims=True)
    lo, hi = 0.2, 8.0
    if not (hourly(lo).max() <= target_mw <= hourly(hi).max()):
        raise ValueError(f"Peak {target_mw} MW unreachable for this energy/shape")
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if hourly(mid).max() < target_mw else (lo, mid)
    return hourly((lo + hi) / 2)


def system_hourly(
    anchors: Anchors,
    cfg,
    types: list[HouseholdType],
    profiles: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    years = list(cfg.years) if cfg.years else list(anchors.years)

    # shares stacked as arr[type, month-1, daytype(0 weekday/1 weekend), hour]
    names = [t.name for t in types]
    arr = np.zeros((len(names), 12, 2, 24))
    ti = profiles.household_type.map({n: i for i, n in enumerate(names)}).to_numpy()
    di = (profiles.daytype == "weekend").astype(int).to_numpy()
    arr[ti, profiles.month.to_numpy() - 1, di, profiles.hour.to_numpy()] = profiles.share.to_numpy()

    frames = []
    for y in years:
        mix = type_mix(types, y)
        w = np.array([mix[n] for n in names])
        w = w / w.sum()
        blend = np.tensordot(w, arr, axes=(0, 0))  # (12, 2, 24)
        hol = holidays(y, cfg)

        energies, shapes, stamps, months = [], [], [], []
        for m in range(1, 13):
            ndays = calendar.monthrange(y, m)[1]
            days = [date(y, m, d) for d in range(1, ndays + 1)]
            weekend = np.array([d.weekday() >= 5 for d in days])
            wt = np.ones(ndays)
            wt[weekend] *= cfg.weekend_factor
            for i, d in enumerate(days):
                if d in hol:
                    wt[i] *= cfg.holiday_factor
            noise = np.clip(
                rng.normal(0.0, cfg.daily_noise_sigma, size=ndays),
                -cfg.daily_noise_clip,
                cfg.daily_noise_clip,
            )
            wt *= 1.0 + noise
            wt /= wt.sum()
            energies.append(anchors.monthly_mwh[(y, m)] * wt)
            shapes.append(blend[m - 1, weekend.astype(int)])
            stamps.extend(datetime(y, m, d.day) for d in days)
            months.extend([m] * ndays)

        day_energy = np.concatenate(energies)
        day_shapes = np.vstack(shapes)
        mw = calibrate_peak(day_energy, day_shapes, anchors.peak_mw[y])

        ts = [s + timedelta(hours=h) for s in stamps for h in range(24)]
        frames.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "year": y,
                    "month": np.repeat(months, 24),
                    "load_mw": mw.reshape(-1),
                    "dataset_version": cfg.dataset_version,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)
