"""Build deploy/demo.db, the small database the Vercel demo starts from.

Run from electroforecast-website after training:  python -m deploy.build_demo_db
It copies database/electroforecast.db, then:
- drops the synthetic tables only used for training (the site reads synth_daily_peaks only),
- keeps just the seeded demo accounts, so test sign-ups and their emails aren't published,
- clears bill-picture references, because uploaded bills are not deployed.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "database" / "electroforecast.db"
TARGET = ROOT / "deploy" / "demo.db"
KEEP_SYNTH = {"synth_daily_peaks"}
DEMO_EMAILS = (
    "admin@electroforecast.local",
    "household@electroforecast.local",
    "maria@electroforecast.local",
)


def build(source: Path = SOURCE, target: Path = TARGET) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    with sqlite3.connect(target) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for (table,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'synth\\_%' ESCAPE '\\'"
        ).fetchall():
            if table not in KEEP_SYNTH:
                db.execute(f'DROP TABLE "{table}"')
        db.execute("PRAGMA foreign_keys=ON")
        placeholders = ",".join("?" for _ in DEMO_EMAILS)
        others = f"(SELECT user_id FROM users WHERE email NOT IN ({placeholders}))"
        # These two references don't cascade, so clear them before deleting the test accounts.
        db.execute(f"DELETE FROM audit_logs WHERE actor_user_id IN {others}", DEMO_EMAILS)
        for table in ("appliances", "monthly_consumption"):
            db.execute(f"UPDATE {table} SET reviewed_by=NULL WHERE reviewed_by IN {others}", DEMO_EMAILS)
        db.execute(f"DELETE FROM users WHERE email NOT IN ({placeholders})", DEMO_EMAILS)
        db.execute(
            """
            UPDATE monthly_consumption
            SET bill_image_filename=NULL, bill_image_original_name=NULL,
                bill_image_mime=NULL, bill_image_size_bytes=NULL
            """
        )
        db.commit()
    with sqlite3.connect(target) as db:
        db.execute("VACUUM")
    return target


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path} ({path.stat().st_size / 1_048_576:.1f} MB)")
