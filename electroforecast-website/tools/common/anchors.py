"""Loader for the real GUIMELCO residential electricity sheet (2020-2025)."""
import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REAL_CSV = (
    Path(__file__).resolve().parents[2] / "data/real/guimelco_residential_2020_2025.csv"
)

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
           "jul", "aug", "sep", "oct", "nov", "dec"]


@dataclass(frozen=True)
class Anchors:
    monthly_mwh: dict
    annual_reported_mwh: dict
    customers: dict
    peak_mw: dict
    notes: dict

    @property
    def years(self):
        return sorted(self.annual_reported_mwh)


def load_anchors(path: Path = DEFAULT_REAL_CSV) -> Anchors:
    monthly, reported, customers, peaks, notes = {}, {}, {}, {}, {}
    with open(path, newline="", encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        for row in rows:
            year = int(row["year"])
            for i, m in enumerate(_MONTHS, start=1):
                monthly[(year, i)] = float(row[m])
            reported[year] = float(row["total_mwh_reported"])
            customers[year] = int(row["customers"])
            peaks[year] = float(row["coincident_peak_mw"])
            total = sum(monthly[(year, i)] for i in range(1, 13))
            if abs(total - reported[year]) > 2:
                notes[year] = (
                    f"Monthly sum {total:.0f} differs from printed total "
                    f"{reported[year]:.0f}; monthly values used."
                )
    return Anchors(monthly, reported, customers, peaks, notes)
