from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from tools.common.anchors import load_anchors
from tools.synth.config import load_config
from tools.synth.customers import customer_counts
from tools.synth.daily import daily_peaks
from tools.synth.households import household_monthly, load_household_types, sample_households
from tools.synth.network import build_network, feeder_hourly, transformer_monthly_peak
from tools.synth.profiles import load_profiles
from tools.synth.system_load import system_hourly
from tools.synth.validate import ValidationError, build_report, validate

HOUSEHOLD_TYPES = Path(__file__).resolve().parent / "household_types.json"

SORT_KEYS = {
    "synth_feeders": ["feeder_id"],
    "synth_transformers": ["transformer_id"],
    "synth_households": ["synth_household_id"],
    "synth_household_monthly": ["synth_household_id", "year", "month"],
    "synth_customer_counts": ["year", "month", "municipality", "barangay"],
    "synth_load_profiles": ["household_type", "month", "daytype", "hour"],
    "synth_system_hourly": ["ts"],
    "synth_feeder_hourly": ["feeder_id", "ts"],
    "synth_transformer_monthly_peak": ["transformer_id", "year", "month"],
    "synth_daily_peaks": ["date"],
}


def generate(config_path: Path, out_dir: Path) -> dict[str, pd.DataFrame]:
    cfg = load_config(config_path)
    anchors = load_anchors()
    types = load_household_types(HOUSEHOLD_TYPES)
    rng = np.random.default_rng(cfg.seed)

    counts = customer_counts(anchors, cfg)
    hh = sample_households(anchors, cfg, types, rng, counts)
    hm = household_monthly(anchors, cfg, types, hh, counts, rng)
    scale = dict(hm.attrs.get("scale_factors", {}))
    profiles = load_profiles(types, cfg)
    system = system_hourly(anchors, cfg, types, profiles, rng)
    feeders, transformers, hh_net = build_network(cfg, hh, counts, rng)
    fh = feeder_hourly(feeders, hh_net, hm, profiles, system)
    tm = transformer_monthly_peak(transformers, hh_net, hm, fh, cfg, rng)
    daily = daily_peaks(system, cfg)

    raw = {
        "synth_feeders": feeders,
        "synth_transformers": transformers,
        "synth_households": hh_net,
        "synth_household_monthly": hm,
        "synth_customer_counts": counts,
        "synth_load_profiles": profiles,
        "synth_system_hourly": system,
        "synth_feeder_hourly": fh,
        "synth_transformer_monthly_peak": tm,
        "synth_daily_peaks": daily,
    }
    tables: dict[str, pd.DataFrame] = {}
    for name, df in raw.items():
        df = df.copy()
        if "ts" in df:
            df["ts"] = pd.to_datetime(df["ts"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        if "date" in df:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        tables[name] = df.sort_values(SORT_KEYS[name], kind="stable").reset_index(drop=True)
    tables["synth_household_monthly"].attrs["scale_factors"] = scale

    checks = validate(anchors, cfg, tables)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False, float_format="%.6f", lineterminator="\n")
    (out_dir / "validation_report.md").write_text(
        build_report(anchors, cfg, tables, checks), encoding="utf-8", newline="\n"
    )
    failed = [c for c in checks if not c.passed]
    if failed:
        raise ValidationError(
            "; ".join(f"{c.name}: {c.actual:.6g} (tolerance {c.tolerance:.6g})" for c in failed)
        )
    return tables


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic GUIMELCO data.")
    ap.add_argument("--config", type=Path, default=Path("tools/synth/config.json"))
    ap.add_argument("--out", type=Path, default=Path("data/synthetic"))
    a = ap.parse_args()
    t = generate(a.config, a.out)
    print(f"Wrote {len(t)} tables and validation_report.md to {a.out}")


if __name__ == "__main__":
    main()
