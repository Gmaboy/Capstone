from __future__ import annotations

import calendar

import numpy as np
import pandas as pd

from tools.common.locations import BARANGAYS
from tools.synth.config import SynthConfig
from tools.synth.customers import largest_remainder


def _cuts(weights: np.ndarray, k: int) -> list[int]:
    """Split an ordered sequence into k contiguous non-empty groups, balanced by weight.

    Returns the k+1 boundary indices.
    """
    n = len(weights)
    if k > n:
        raise ValueError(f"Cannot split {n} items into {k} non-empty groups")
    cum = np.cumsum(weights)
    bounds = [0]
    for j in range(1, k):
        b = int(np.searchsorted(cum, cum[-1] * j / k))
        b = max(b, bounds[-1] + 1)
        b = min(b, n - (k - j))
        bounds.append(b)
    bounds.append(n)
    return bounds


def build_network(
    cfg: SynthConfig,
    households: pd.DataFrame,
    counts: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    last = counts[counts.year == counts.year.max()]
    last = last[last.month == last.month.max()]
    cust = {(r.municipality, r.barangay): int(r.customers) for r in last.itertuples()}

    # Feeders: contiguous barangays per municipality, balanced by customers.
    feeder_rows = []
    feeder_of: dict[tuple[str, str], int] = {}
    fid = 0
    for muni, nf in cfg.feeders.items():
        brgys = list(BARANGAYS[muni])
        b = _cuts(np.array([cust[(muni, x)] for x in brgys], dtype=float), nf)
        for i in range(nf):
            fid += 1
            names = brgys[b[i]:b[i + 1]]
            for x in names:
                feeder_of[(muni, x)] = fid
            feeder_rows.append(
                {
                    "feeder_id": fid,
                    "feeder_code": f"SYN-{muni[:3].upper()}-F{i + 1}",
                    "substation_zone": muni,
                    "barangays": ";".join(names),
                    "dataset_version": cfg.dataset_version,
                }
            )
    feeders = pd.DataFrame(feeder_rows)

    # Households: attach feeder; weight = final-year customers per sampled household.
    hh = households.copy()
    keys = list(zip(hh.municipality, hh.barangay))
    hh["feeder_id"] = [feeder_of[k] for k in keys]
    n_sampled = hh.groupby(["municipality", "barangay"]).synth_household_id.transform("size")
    hh["_w"] = np.array([cust[k] for k in keys], dtype=float) / n_sampled.to_numpy()
    order = {(m, b): i for m, bs in BARANGAYS.items() for i, b in enumerate(bs)}
    hh["_ord"] = [order[k] for k in keys]

    # Transformers per feeder: by customer share, >= 1 each, <= sampled households.
    f_cust = hh.groupby("feeder_id")._w.sum().reindex(feeders.feeder_id).to_numpy()
    f_hh = hh.groupby("feeder_id").size().reindex(feeders.feeder_id).to_numpy()
    if cfg.transformers_total < len(feeders) or cfg.transformers_total > f_hh.sum():
        raise ValueError("transformers_total must be between feeder count and sampled households")
    alloc = np.array(largest_remainder(cfg.transformers_total, list(f_cust)))
    while (alloc < 1).any() or (alloc > f_hh).any():
        if (alloc < 1).any():
            i = int(np.argmax(alloc < 1))
            alloc[i] += 1
            alloc[int(np.argmax(alloc))] -= 1
        else:
            i = int(np.argmax(alloc > f_hh))
            alloc[i] -= 1
            spare = np.where(alloc < f_hh)[0]
            alloc[spare[np.argmax(f_cust[spare])]] += 1

    # Cluster each feeder's households (registry order) into its transformers.
    hh["transformer_id"] = 0
    trows = []
    tid = 0
    for fi, f in enumerate(feeders.itertuples()):
        sub = hh[hh.feeder_id == f.feeder_id].sort_values(["_ord", "synth_household_id"])
        b = _cuts(sub._w.to_numpy(), int(alloc[fi]))
        for j in range(int(alloc[fi])):
            tid += 1
            part = sub.iloc[b[j]:b[j + 1]]
            hh.loc[part.index, "transformer_id"] = tid
            names = list(dict.fromkeys(part.barangay))
            trows.append(
                {
                    "transformer_id": tid,
                    "transformer_code": f"SYN-T{tid:03d}",
                    "feeder_id": f.feeder_id,
                    "barangays": ";".join(names),
                    "rating_kva": np.nan,
                    "dataset_version": cfg.dataset_version,
                }
            )
    transformers = pd.DataFrame(trows)
    hh = hh.drop(columns=["_w", "_ord"])
    return feeders, transformers, hh


def feeder_hourly(
    feeders: pd.DataFrame,
    households: pd.DataFrame,
    household_monthly: pd.DataFrame,
    profiles: pd.DataFrame,
    system: pd.DataFrame,
) -> pd.DataFrame:
    names = sorted(households.household_type.unique())
    tidx = {n: i for i, n in enumerate(names)}
    arr = np.zeros((len(names), 12, 2, 24))
    pt = profiles[profiles.household_type.isin(tidx)]
    arr[
        pt.household_type.map(tidx).to_numpy(),
        pt.month.to_numpy() - 1,
        (pt.daytype == "weekend").astype(int).to_numpy(),
        pt.hour.to_numpy(),
    ] = pt.share.to_numpy()

    fids = list(feeders.feeder_id)
    fpos = {f: i for i, f in enumerate(fids)}
    hm = household_monthly.merge(
        households[["synth_household_id", "feeder_id", "household_type"]], on="synth_household_id"
    )
    hm["e"] = hm.weight * hm.kwh
    energy = hm.groupby(["year", "month", "feeder_id", "household_type"]).e.sum()

    ts = pd.DatetimeIndex(system.ts)
    out = np.zeros((len(fids), len(system)))
    for (y, m), pos in system.groupby(["year", "month"]).indices.items():
        days = calendar.monthrange(int(y), int(m))[1]
        e = np.zeros((len(fids), len(names)))
        for (f, t), v in energy.loc[(y, m)].items():
            e[fpos[f], tidx[t]] = v
        dt = (((ts[pos].values.astype("datetime64[D]").astype(int) + 3) % 7) >= 5).astype(int)
        shares = arr[:, m - 1, dt, ts[pos].hour]  # (types, n)
        out[:, pos] = (e / days) @ shares
    out = system.load_mw.to_numpy() * out / out.sum(axis=0)
    return pd.DataFrame(
        {
            "ts": np.tile(system.ts.to_numpy(), len(fids)),
            "feeder_id": np.repeat(fids, len(system)),
            "load_mw": out.reshape(-1),
            "dataset_version": system.dataset_version.iloc[0],
        }
    )


def transformer_monthly_peak(
    transformers: pd.DataFrame,
    households: pd.DataFrame,
    household_monthly: pd.DataFrame,
    feeder_hourly: pd.DataFrame,
    cfg: SynthConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    hm = household_monthly.merge(
        households[["synth_household_id", "feeder_id", "transformer_id"]], on="synth_household_id"
    )
    hm["e"] = hm.weight * hm.kwh
    t_e = hm.groupby(["transformer_id", "year", "month"]).e.sum().rename("t_e").reset_index()
    f_e = hm.groupby(["feeder_id", "year", "month"]).e.sum().rename("f_e").reset_index()
    tm = t_e.merge(transformers[["transformer_id", "feeder_id"]], on="transformer_id")
    tm = tm.merge(f_e, on=["feeder_id", "year", "month"])
    tm["share"] = tm.t_e / tm.f_e

    fh = feeder_hourly.assign(
        year=feeder_hourly.ts.dt.year, month=feeder_hourly.ts.dt.month
    )
    fpeak = fh.groupby(["feeder_id", "year", "month"], as_index=False).load_mw.max()
    tm = tm.merge(fpeak, on=["feeder_id", "year", "month"])
    tm["peak_kva"] = tm.load_mw * tm.share * 1000.0 / cfg.power_factor

    sizes = np.array(sorted(cfg.transformer_sizes_kva), dtype=float)
    final = tm[tm.year == tm.year.max()].groupby("transformer_id").peak_kva.max()
    hi_cap = max(cfg.transformer_util_stressed)
    lo_cap = min(cfg.transformer_util_normal)
    ratings = {}
    for t in transformers.transformer_id:
        stressed = rng.random() < cfg.transformer_stressed_share
        lo, hi = cfg.transformer_util_stressed if stressed else cfg.transformer_util_normal
        target = rng.uniform(lo, hi)
        peak = float(final[t])
        # closest standard size to peak / target; a tie goes to the larger size
        i = len(sizes) - 1 - int(np.argmin(np.abs(sizes[::-1] - peak / target)))
        while peak / sizes[i] > hi_cap and i < len(sizes) - 1:
            i += 1
        while peak / sizes[i] < lo_cap and i > 0:
            i -= 1
        ratings[t] = float(sizes[i])
    transformers["rating_kva"] = transformers.transformer_id.map(ratings)
    tm["utilization"] = tm.peak_kva / tm.transformer_id.map(ratings)
    tm["dataset_version"] = cfg.dataset_version
    return tm.sort_values(["transformer_id", "year", "month"])[
        ["transformer_id", "year", "month", "peak_kva", "utilization", "dataset_version"]
    ].reset_index(drop=True)
