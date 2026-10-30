from __future__ import annotations

import pandas as pd

from tools.synth.config import SynthConfig


def daily_peaks(system: pd.DataFrame, cfg: SynthConfig) -> pd.DataFrame:
    """Daily peak MW, share of that year's peak day, and High/Medium/Low label."""
    s = system.assign(date=pd.to_datetime(system.ts).dt.normalize())
    d = s.groupby("date", as_index=False).agg(year=("year", "first"), peak_mw=("load_mw", "max"))
    d["pct_of_annual_peak"] = d.peak_mw / d.groupby("year").peak_mw.transform("max")
    high = cfg.demand_thresholds["high"]
    medium = cfg.demand_thresholds["medium"]
    d["demand_level"] = "Low"
    d.loc[d.pct_of_annual_peak >= medium, "demand_level"] = "Medium"
    d.loc[d.pct_of_annual_peak >= high, "demand_level"] = "High"
    d["dataset_version"] = cfg.dataset_version
    return d[["date", "year", "peak_mw", "pct_of_annual_peak", "demand_level", "dataset_version"]]
