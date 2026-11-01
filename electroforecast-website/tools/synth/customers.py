from __future__ import annotations

from typing import Sequence

import pandas as pd

from tools.common.anchors import Anchors
from tools.common.locations import BARANGAYS
from tools.synth.config import SynthConfig


def largest_remainder(total: int, weights: Sequence[float]) -> list[int]:
    """Split an integer total proportionally to weights so the parts sum exactly."""
    wsum = float(sum(weights))
    quotas = [total * w / wsum for w in weights]
    parts = [int(q // 1) for q in quotas]
    order = sorted(range(len(weights)), key=lambda i: (-(quotas[i] - parts[i]), i))
    for i in order[: total - sum(parts)]:
        parts[i] += 1
    return parts


def _years(anchors: Anchors, cfg: SynthConfig) -> list[int]:
    return list(cfg.years) if cfg.years else list(anchors.years)


def monthly_customers(anchors: Anchors, cfg: SynthConfig) -> dict[tuple[int, int], int]:
    """Year-end convention: month m of year y = C[y-1] + (C[y]-C[y-1]) * m/12."""
    c = dict(anchors.customers)
    first = min(c)
    c[first - 1] = c[first] - (c[first + 1] - c[first])
    out: dict[tuple[int, int], int] = {}
    for y in _years(anchors, cfg):
        for m in range(1, 13):
            out[(y, m)] = int(round(c[y - 1] + (c[y] - c[y - 1]) * m / 12))
    return out


def customer_counts(anchors: Anchors, cfg: SynthConfig) -> pd.DataFrame:
    muni_names = list(BARANGAYS)
    shares = [cfg.municipality_shares[k] for k in muni_names]
    rows = []
    for (y, m), total in monthly_customers(anchors, cfg).items():
        for muni, n_muni in zip(muni_names, largest_remainder(total, shares)):
            bgys = BARANGAYS[muni]
            if cfg.barangay_weighting == "population":
                pops = cfg.barangay_populations[muni]
                w = [pops[b] for b in bgys]
            else:
                w = [1.0] * len(bgys)
            for b, n in zip(bgys, largest_remainder(n_muni, w)):
                rows.append((y, m, muni, b, n, cfg.dataset_version))
    return pd.DataFrame(
        rows,
        columns=["year", "month", "municipality", "barangay", "customers", "dataset_version"],
    )
