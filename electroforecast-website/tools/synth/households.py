from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from tools.common.anchors import Anchors
from tools.synth.config import SynthConfig
from tools.synth.customers import largest_remainder

MIX_YEAR_START = 2020
MIX_YEAR_END = 2025
AIRCON_SEASON = {4: 1.35, 5: 1.35, 6: 1.35, 3: 1.1, 7: 1.1, 8: 1.1}
AIRCON_OFFSEASON = 0.85
SEASONAL_CLIP = 0.08


@dataclass(frozen=True)
class HouseholdType:
    name: str
    appliances: list[dict]
    mix_start: float
    mix_end: float
    peak_window: str

    @property
    def base_kwh_month(self) -> float:
        return sum(
            a["watts"] * a["quantity"] * a["hours_per_day"] * 30.4 / 1000
            for a in self.appliances
        )


def load_household_types(path: Path) -> list[HouseholdType]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        HouseholdType(
            name=t["name"],
            appliances=t["appliances"],
            mix_start=t["mix_start"],
            mix_end=t["mix_end"],
            peak_window=t["peak_window"],
        )
        for t in data["types"]
    ]


def type_mix(types: list[HouseholdType], year: int) -> dict[str, float]:
    """Household-type shares for a year, linear from the 2020 to the 2025 mix."""
    f = (year - MIX_YEAR_START) / (MIX_YEAR_END - MIX_YEAR_START)
    return {t.name: t.mix_start + (t.mix_end - t.mix_start) * f for t in types}


def _years(anchors: Anchors, cfg: SynthConfig) -> list[int]:
    return list(cfg.years) if cfg.years else list(anchors.years)


def sample_households(
    anchors: Anchors,
    cfg: SynthConfig,
    types: list[HouseholdType],
    rng: np.random.Generator,
    counts: pd.DataFrame,
) -> pd.DataFrame:
    """Sample stratified on (municipality, barangay), at least one per barangay."""
    last = _years(anchors, cfg)[-1]
    final = counts[(counts.year == last) & (counts.month == 12)]
    keys = list(zip(final.municipality, final.barangay))
    cust = [int(c) for c in final.customers]
    n = cfg.household_sample_size
    if n < len(keys):
        raise ValueError("household_sample_size is smaller than the number of barangays")
    alloc = largest_remainder(n, cust)
    for i, a in enumerate(alloc):  # guarantee >= 1 per barangay, taking from the largest
        if a == 0:
            alloc[i] = 1
            alloc[max(range(len(alloc)), key=lambda j: alloc[j])] -= 1

    mix = type_mix(types, last)
    names = [t.name for t in types]
    p = np.array([mix[nm] for nm in names])
    p = p / p.sum()
    sizes = np.arange(1, 9)
    sp = np.exp(-((sizes - 4) ** 2) / (2 * 1.5**2))
    sp = sp / sp.sum()

    rows = [key for key, k in zip(keys, alloc) for _ in range(k)]
    total = len(rows)
    htypes = rng.choice(names, size=total, p=p)
    hsizes = rng.choice(sizes, size=total, p=sp)
    df = pd.DataFrame(rows, columns=["municipality", "barangay"])
    df.insert(0, "synth_household_id", [f"H{i + 1:05d}" for i in range(total)])
    df["household_type"] = htypes
    df["household_size"] = hsizes.astype(int)
    df["dataset_version"] = cfg.dataset_version
    return df


def _seasonal(t: HouseholdType, month: int, month_mwh: float, year_mean_mwh: float) -> float:
    if t.name == "aircon":
        return AIRCON_SEASON.get(month, AIRCON_OFFSEASON)
    dev = month_mwh / year_mean_mwh - 1.0
    return 1.0 + float(np.clip(dev, -SEASONAL_CLIP, SEASONAL_CLIP))


def household_monthly(
    anchors: Anchors,
    cfg: SynthConfig,
    types: list[HouseholdType],
    households: pd.DataFrame,
    counts: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    by_name = {t.name: t for t in types}
    base = households.household_type.map(lambda n: by_name[n].base_kwh_month).to_numpy()
    size_f = 0.7 + 0.075 * households.household_size.to_numpy()
    n_hh = len(households)

    hh_index = pd.MultiIndex.from_frame(households[["municipality", "barangay"]])
    n_sampled = households.groupby(["municipality", "barangay"]).size()
    ns = n_sampled.reindex(hh_index).to_numpy(dtype=float)
    cust_lookup = counts.set_index(["year", "month", "municipality", "barangay"]).customers

    frames = []
    scale_factors: dict[tuple[int, int], float] = {}
    for y in _years(anchors, cfg):
        year_mean = float(np.mean([anchors.monthly_mwh[(y, m)] for m in range(1, 13)]))
        for m in range(1, 13):
            mwh = anchors.monthly_mwh[(y, m)]
            seas = np.array(
                [_seasonal(by_name[n], m, mwh, year_mean) for n in households.household_type]
            )
            noise = rng.lognormal(0.0, cfg.household_noise_sigma, size=n_hh)
            raw = base * seas * size_f * noise

            cust = cust_lookup.loc[(y, m)].reindex(hh_index).to_numpy(dtype=float)
            weight = cust / ns

            factor = mwh * 1000.0 / float((weight * raw).sum())
            scale_factors[(y, m)] = factor
            frames.append(
                pd.DataFrame(
                    {
                        "synth_household_id": households.synth_household_id.to_numpy(),
                        "year": y,
                        "month": m,
                        "kwh": np.round(raw * factor, 1),
                        "weight": weight,
                        "dataset_version": cfg.dataset_version,
                    }
                )
            )
    out = pd.concat(frames, ignore_index=True)
    out.attrs["scale_factors"] = scale_factors
    return out
