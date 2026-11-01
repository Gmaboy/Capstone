"""Households may delete pending and rejected submissions, never approved ones."""
import sqlite3
import sys

import pytest

from tests.test_validated_data import HOUSEHOLD_LOGIN, _client


@pytest.fixture
def household(tmp_path, monkeypatch):
    db = tmp_path / "h.db"
    try:
        yield _client(monkeypatch, db, HOUSEHOLD_LOGIN), db
    finally:
        sys.modules.pop("app", None)


def _ids(db, table, key, status):
    with sqlite3.connect(db) as con:
        return [r[0] for r in con.execute(
            f"SELECT {key} FROM {table} t JOIN households h ON h.household_id=t.household_id "
            f"JOIN users u ON u.user_id=h.user_id WHERE u.email=? AND t.verification_status=?",
            (HOUSEHOLD_LOGIN["email"], status))]


def test_appliance_delete_by_status(household):
    c, db = household
    approved = _ids(db, "appliances", "appliance_id", "approved")
    pending = _ids(db, "appliances", "appliance_id", "pending")
    rejected = _ids(db, "appliances", "appliance_id", "rejected")
    assert approved and pending and rejected  # demo seed covers all three
    assert c.delete(f"/api/appliances/{approved[0]}").status_code == 409
    assert c.delete(f"/api/appliances/{pending[0]}").status_code == 200
    assert c.delete(f"/api/appliances/{rejected[0]}").status_code == 200


def test_approved_bill_cannot_be_deleted(household):
    c, db = household
    approved = _ids(db, "monthly_consumption", "consumption_id", "approved")
    r = c.delete(f"/api/consumption/{approved[0]}")
    assert r.status_code == 409 and "Approved" in r.json["error"]
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT deleted_at FROM monthly_consumption WHERE consumption_id=?",
                           (approved[0],)).fetchone()[0] is None


def test_pending_and_rejected_bills_can_be_deleted(household):
    c, db = household
    pending = _ids(db, "monthly_consumption", "consumption_id", "pending")
    assert c.delete(f"/api/consumption/{pending[0]}").status_code == 200
    r = c.delete("/api/consumption/permanent", json={"consumption_ids": [pending[0]]})
    assert r.status_code == 200 and r.json["deleted_count"] == 1

    approved = _ids(db, "monthly_consumption", "consumption_id", "approved")
    with sqlite3.connect(db) as con:
        con.execute("UPDATE monthly_consumption SET verification_status='rejected' WHERE consumption_id=?", (approved[0],))
    assert c.delete(f"/api/consumption/{approved[0]}").status_code == 200


def test_approved_bill_in_recently_deleted_cannot_be_purged(household):
    c, db = household
    approved = _ids(db, "monthly_consumption", "consumption_id", "approved")
    # Bills soft-deleted before this rule existed may already sit in Recently Deleted.
    with sqlite3.connect(db) as con:
        con.execute("UPDATE monthly_consumption SET deleted_at=CURRENT_TIMESTAMP WHERE consumption_id=?", (approved[0],))
    r = c.delete("/api/consumption/permanent", json={"consumption_ids": [approved[0]]})
    assert r.status_code == 409
    assert c.post(f"/api/consumption/{approved[0]}/restore").status_code == 200
