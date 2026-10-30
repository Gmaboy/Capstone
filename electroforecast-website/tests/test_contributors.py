import sqlite3
import sys

import pytest

from tests.test_validated_data import ADMIN_LOGIN, HOUSEHOLD_LOGIN, _client


@pytest.fixture
def admin_db(tmp_path, monkeypatch):
    db = tmp_path / "c.db"
    try:
        yield _client(monkeypatch, db, ADMIN_LOGIN), db
    finally:
        sys.modules.pop("app", None)


def test_contributors_requires_staff_role(client, tmp_path, monkeypatch):
    assert client.get("/api/contributors").status_code == 401
    try:
        c = _client(monkeypatch, tmp_path / "h.db", HOUSEHOLD_LOGIN)
        assert c.get("/api/contributors").status_code == 403
    finally:
        sys.modules.pop("app", None)


def test_contributors_ranked_by_approved_with_short_names(admin_db):
    c, _ = admin_db
    rows = c.get("/api/contributors").json["contributors"]
    # Seed: Juan has 8 submissions (5 approved), Maria 3 (2 approved); the admin has none.
    assert [r["name"] for r in rows] == ["Juan D.", "Maria S."]
    assert [(r["rank"], r["submissions"], r["approved"]) for r in rows] == [(1, 8, 5), (2, 3, 2)]
    assert set(rows[0]) == {"rank", "name", "initials", "submissions", "approved", "approval_rate", "joined"}
    assert rows[0]["approval_rate"] == 62.5


def test_contributors_skip_deleted_bills_and_inactive_users(admin_db):
    c, db = admin_db
    with sqlite3.connect(db) as con:
        con.execute("UPDATE monthly_consumption SET deleted_at = CURRENT_TIMESTAMP")
        con.execute("UPDATE users SET status = 'inactive' WHERE email = 'maria@electroforecast.local'")
    rows = c.get("/api/contributors").json["contributors"]
    assert [(r["name"], r["submissions"], r["approved"]) for r in rows] == [("Juan D.", 4, 2)]
