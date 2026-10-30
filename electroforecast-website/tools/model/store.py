"""SQLite access for the trainer: input checks and transactional run storage."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from tools.common.anchors import Anchors

LOAD_CMD = "python -m tools.synth.load --db <db> --real <real.csv> --synthetic <synthetic_dir>"
MONTHLY_ROWS = 72
SCHEMA = Path(__file__).resolve().parents[2] / "database" / "schema.sqlite.sql"


class MissingDataError(Exception):
    """Training inputs are absent from the database."""


@contextmanager
def connect(db_path: Path):
    """Open an existing DB (never creates a file); autocommit mode, always closed."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise MissingDataError(
            f"Database {db_path} does not exist, so table utility_monthly_energy is missing. "
            f"Fill it with: {LOAD_CMD}"
        )
    with closing(sqlite3.connect(db_path, isolation_level=None)) as con:
        yield con


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def check_inputs(con: sqlite3.Connection, dataset_version: str) -> None:
    for table in ("utility_monthly_energy", "utility_annual_stats", "synth_daily_peaks"):
        if not _has_table(con, table):
            raise MissingDataError(f"Table {table} is missing. Fill it with: {LOAD_CMD}")
    n = con.execute("SELECT COUNT(*) FROM utility_monthly_energy").fetchone()[0]
    if n != MONTHLY_ROWS:
        raise MissingDataError(
            f"Table utility_monthly_energy has {n} rows, expected {MONTHLY_ROWS}. Fill it with: {LOAD_CMD}"
        )
    if not con.execute("SELECT 1 FROM synth_daily_peaks WHERE dataset_version=? LIMIT 1", (dataset_version,)).fetchone():
        raise MissingDataError(
            f"Table synth_daily_peaks has no rows for dataset_version {dataset_version!r}. Fill it with: {LOAD_CMD}"
        )


def ensure_schema(con: sqlite3.Connection) -> None:
    """Create the model tables if absent (schema file is idempotent)."""
    con.executescript(SCHEMA.read_text(encoding="utf-8"))


def read_anchors(con: sqlite3.Connection) -> Anchors:
    monthly = {(y, m): float(v) for y, m, v in con.execute("SELECT year, month, energy_mwh FROM utility_monthly_energy")}
    reported, customers, peaks, notes = {}, {}, {}, {}
    for y, tot, cust, peak, note in con.execute(
        "SELECT year, total_mwh_reported, customers, coincident_peak_mw, notes FROM utility_annual_stats"
    ):
        reported[y], customers[y], peaks[y] = float(tot), int(cust), float(peak)
        if note:
            notes[y] = note
    return Anchors(monthly, reported, customers, peaks, notes)


def read_daily(con: sqlite3.Connection, dataset_version: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT date, year, peak_mw, demand_level FROM synth_daily_peaks WHERE dataset_version=? ORDER BY date",
        con, params=(dataset_version,),
    )


def _rows(df: pd.DataFrame, cols: list[str]) -> list[tuple]:
    out = df[cols].astype(object)
    return [tuple(v.item() if hasattr(v, "item") else v for v in row) for row in out.itertuples(index=False, name=None)]


def save_run(
    con: sqlite3.Connection,
    task: str,
    model_name: str,
    dataset_version: str,
    metrics: dict,
    children: list[tuple[str, list[str], pd.DataFrame, dict]],
) -> int:
    """Insert a run, its child rows and flip activation in one transaction.

    children: (table, columns, frame, constants). Constants are extra column
    values (e.g. kind) added to every row; `run_id` is always the first column.
    """
    con.execute("BEGIN")
    try:
        cur = con.execute(
            "INSERT INTO model_runs (task, model_name, dataset_version, trained_at, metrics, is_active) VALUES (?,?,?,?,?,0)",
            (task, model_name, dataset_version, datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(metrics)),
        )
        run_id = int(cur.lastrowid)
        for table, cols, frame, const in children:
            all_cols = ["run_id", *const, *cols]
            marks = ",".join("?" * len(all_cols))
            prefix = (run_id, *const.values())
            con.executemany(
                f"INSERT INTO {table} ({','.join(all_cols)}) VALUES ({marks})",
                [prefix + r for r in _rows(frame, cols)],
            )
        con.execute("UPDATE model_runs SET is_active=0 WHERE task=?", (task,))
        con.execute("UPDATE model_runs SET is_active=1 WHERE run_id=?", (run_id,))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return run_id
