from __future__ import annotations

import numpy as np
import pandas as pd

from tools.synth.households import HouseholdType

BASE = 0.025
HOT_MONTHS = (4, 5, 6)
HOT_BOOST = 1.4
MIDDAY_HOURS = range(10, 16)
WEEKEND_MIDDAY = 1.10


def _bump(center: float, sigma: float, amp: float) -> np.ndarray:
    h = np.arange(24)
    return amp * np.exp(-((h - center) ** 2) / (2 * sigma**2))


def _shape(peak_window: str, month: int, weekend: bool) -> np.ndarray:
    s = np.full(24, BASE)
    if peak_window == "evening":
        morning = 7 if weekend else 6
        s += _bump(19, 1.5, 0.08) + _bump(morning, 1.5, 0.02)
    elif peak_window == "afternoon_evening":
        boost = HOT_BOOST if month in HOT_MONTHS else 1.0
        s += _bump(14, 2.0, 0.04 * boost) + _bump(20, 1.8, 0.06 * boost)
    elif peak_window == "flat":
        s += _bump(12, 4.0, 0.03)
    else:
        raise ValueError(f"Unknown peak_window: {peak_window}")
    if weekend:
        for h in MIDDAY_HOURS:
            s[h] *= WEEKEND_MIDDAY
    return s / s.sum()


def load_profiles(types: list[HouseholdType], cfg) -> pd.DataFrame:
    rows = []
    for t in types:
        for month in range(1, 13):
            for daytype in ("weekday", "weekend"):
                s = _shape(t.peak_window, month, daytype == "weekend")
                for hour in range(24):
                    rows.append((t.name, month, daytype, hour, float(s[hour])))
    df = pd.DataFrame(rows, columns=["household_type", "month", "daytype", "hour", "share"])
    df["dataset_version"] = cfg.dataset_version
    return df
