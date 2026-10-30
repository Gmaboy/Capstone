from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

from tools.common.anchors import load_anchors
from tools.synth.generate import SORT_KEYS

SCHEMA = Path(__file__).resolve().parents[2] / "database" / "schema.sqlite.sql"
SOURCE = "GUIMELCO Residential.pdf"


def _insert(con: sqlite3.Connection, table: str, df: pd.DataFrame, chunksize: int = 10000) -> None:
    """Chunked append inside the caller's transaction (pandas.to_sql commits per call)."""
    cols = ", ".join(df.columns)
    marks = ", ".join("?" * len(df.columns))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({marks})"
    rows = df.astype(object).where(df.notna(), None)
    for i in range(0, len(rows), chunksize):
        con.executemany(sql, rows.iloc[i : i + chunksize].itertuples(index=False, name=None))


def load(db_path: Path, real_csv: Path, synthetic_dir: Path) -> None:
    report = Path(synthetic_dir) / "validation_report.md"
    if not report.exists():
        raise RuntimeError(
            f"{report} is missing: refusing to load unvalidated synthetic data. "
            "Run python -m tools.synth.generate first."
        )
    if "FAIL" in report.read_text(encoding="utf-8"):
        raise RuntimeError(f"{report} contains FAIL: refusing to load synthetic data that failed validation.")
    anchors = load_anchors(real_csv)
    monthly = pd.DataFrame(
        [(y, m, v, SOURCE) for (y, m), v in sorted(anchors.monthly_mwh.items())],
        columns=["year", "month", "energy_mwh", "source"],
    )
    annual = pd.DataFrame(
        [
            (
                y,
                anchors.annual_reported_mwh[y],
                anchors.customers[y],
                anchors.peak_mw[y],
                anchors.notes.get(y),
            )
            for y in anchors.years
        ],
        columns=["year", "total_mwh_reported", "customers", "coincident_peak_mw", "notes"],
    )
    frames = {
        name: pd.read_csv(Path(synthetic_dir) / f"{name}.csv", keep_default_na=False)
        for name in SORT_KEYS
    }
    con = sqlite3.connect(db_path, isolation_level=None)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.execute("BEGIN")
        try:
            for name, df in frames.items():
                for version in df.dataset_version.unique():
                    con.execute(f"DELETE FROM {name} WHERE dataset_version=?", (version,))
                _insert(con, name, df)
            con.execute("DELETE FROM utility_monthly_energy")
            con.execute("DELETE FROM utility_annual_stats")
            _insert(con, "utility_monthly_energy", monthly)
            _insert(con, "utility_annual_stats", annual)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Load synthetic + real utility data into SQLite.")
    ap.add_argument("--db", type=Path, default=Path("database/electroforecast.db"))
    ap.add_argument("--real", type=Path, default=Path("data/real/guimelco_residential_2020_2025.csv"))
    ap.add_argument("--synthetic", type=Path, default=Path("data/synthetic"))
    a = ap.parse_args()
    load(a.db, a.real, a.synthetic)
    print(f"Loaded into {a.db}")


if __name__ == "__main__":
    main()
