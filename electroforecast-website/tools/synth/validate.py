from __future__ import annotations

import calendar
from dataclasses import dataclass

import numpy as np
import pandas as pd

from tools.common.anchors import Anchors
from tools.synth.config import SynthConfig
from tools.synth.customers import monthly_customers

SCALE_WARN_RANGE = (0.7, 1.3)


class ValidationError(Exception):
    pass


@dataclass(frozen=True)
class Check:
    name: str
    actual: float
    tolerance: float
    passed: bool


def _years(anchors: Anchors, cfg: SynthConfig) -> list[int]:
    return list(cfg.years) if cfg.years else list(anchors.years)


def validate(anchors: Anchors, cfg: SynthConfig, tables: dict[str, pd.DataFrame]) -> list[Check]:
    """Spec 4.8 checks against the real sheet."""
    checks: list[Check] = []
    years = _years(anchors, cfg)

    hm = tables["synth_household_monthly"]
    e = (hm.weight * hm.kwh).groupby([hm.year, hm.month]).sum() / 1000.0
    worst = max(
        abs(mwh - anchors.monthly_mwh[k]) / anchors.monthly_mwh[k] for k, mwh in e.items()
    )
    checks.append(Check("household energy vs sheet MWh, max relative error", worst, 1e-4, worst <= 1e-4))

    sy = tables["synth_system_hourly"]
    s = sy.groupby(["year", "month"]).load_mw.sum()
    worst = max(abs(v - anchors.monthly_mwh[k]) / anchors.monthly_mwh[k] for k, v in s.items())
    checks.append(Check("system hourly MWh vs sheet MWh, max relative error", worst, 1e-4, worst <= 1e-4))

    amax = sy.groupby("year").load_mw.max()
    for y in years:
        d = abs(float(amax[y]) - anchors.peak_mw[y])
        checks.append(Check(f"annual peak vs sheet {y} (MW)", d, 0.01, d <= 0.01))

    cc = tables["synth_customer_counts"].groupby(["year", "month"]).customers.sum()
    expected = monthly_customers(anchors, cfg)
    bad = sum(1 for k, v in expected.items() if int(cc.get(k, -1)) != v)
    bad += len(set(cc.index) - set(expected))
    checks.append(
        Check("customer counts vs monthly_customers, mismatched months", float(bad), 0.0, bad == 0)
    )

    fh = tables["synth_feeder_hourly"].groupby("ts").load_mw.sum()
    ref = sy.set_index("ts").load_mw
    diff = float((fh.reindex(ref.index) - ref).abs().max())
    if np.isnan(diff):
        diff = float("inf")
    checks.append(Check("feeder sum vs system, max hourly diff (MW)", diff, 1e-3, diff <= 1e-3))

    bad_cells = 0
    for df in tables.values():
        num = df.select_dtypes(include="number")
        bad_cells += int((num.isna() | (num < 0)).to_numpy().sum())
    checks.append(
        Check("negative or NaN numeric values, all tables", float(bad_cells), 0.0, bad_cells == 0)
    )
    return checks


def build_report(
    anchors: Anchors, cfg: SynthConfig, tables: dict[str, pd.DataFrame], checks: list[Check]
) -> str:
    years = _years(anchors, cfg)
    lines = [
        "# Synthetic data validation report",
        "",
        f"Dataset version: `{cfg.dataset_version}`  ",
        f"Years: {years[0]}-{years[-1]}",
        "",
        "## Checks",
        "",
        "| Status | Check | Actual | Tolerance |",
        "|---|---|---|---|",
    ]
    for c in checks:
        status = "PASS" if c.passed else "FAIL"
        lines.append(f"| {status} | {c.name} | {c.actual:.6g} | {c.tolerance:.6g} |")

    sy = tables["synth_system_hourly"]
    mc = monthly_customers(anchors, cfg)
    sf = tables["synth_household_monthly"].attrs.get("scale_factors", {})
    lines += [
        "",
        "## Per-year summary",
        "",
        "| Year | Synthetic MWh | Peak MW | Load factor | kWh/customer/month | Min scale | Max scale |",
        "|---|---|---|---|---|---|---|",
    ]
    for y in years:
        sub = sy[sy.year == y]
        mwh = float(sub.load_mw.sum())
        peak = float(sub.load_mw.max())
        hours = 8784 if calendar.isleap(y) else 8760
        lf = mwh / (peak * hours)
        kpc = mwh * 1000.0 / sum(mc[(y, m)] for m in range(1, 13))
        f = [v for (yy, _), v in sf.items() if yy == y]
        lo = f"{min(f):.3f}" if f else "n/a"
        hi = f"{max(f):.3f}" if f else "n/a"
        lines.append(f"| {y} | {mwh:.1f} | {peak:.2f} | {lf:.3f} | {kpc:.1f} | {lo} | {hi} |")

    warns = [
        (k, v) for k, v in sorted(sf.items()) if not SCALE_WARN_RANGE[0] <= v <= SCALE_WARN_RANGE[1]
    ]
    lines += ["", "## Scale-factor warnings", ""]
    if warns:
        for (y, m), v in warns:
            lines.append(
                f"- WARN {y}-{m:02d}: scale factor {v:.3f} outside "
                f"[{SCALE_WARN_RANGE[0]}, {SCALE_WARN_RANGE[1]}]"
            )
    else:
        lines.append("None.")

    lines += [
        "",
        "## Limitations",
        "",
        "- Household type mix: the sampled households' types are drawn from the final config year's "
        "mix and stay fixed for all years. Year-to-year growth in kWh/customer comes from the monthly "
        "scale factor, not from a changing mix of household types.",
        "- Only monthly energy and the annual peak are real (the utility sheet); hourly, daily, "
        "feeder, transformer and household values are synthetic reconstructions.",
    ]
    notes = [anchors.notes[y] for y in years if y in anchors.notes]
    if notes:
        lines += ["", "## Notes", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"
