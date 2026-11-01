import sqlite3
import sys

import pytest

from tests.conftest import _import_app

ADMIN_LOGIN = {"email": "admin@electroforecast.local", "password": "Admin123!"}
HOUSEHOLD_LOGIN = {"email": "household@electroforecast.local", "password": "Household123!"}


def _client(monkeypatch, db_path, login):
    mod = _import_app(monkeypatch, db_path)
    client = mod.app.test_client()
    assert client.post("/api/auth/login", json=login).status_code == 200
    return client


@pytest.fixture
def admin_empty(tmp_path, monkeypatch):
    db = tmp_path / "empty.db"
    try:
        yield _client(monkeypatch, db, ADMIN_LOGIN), db
    finally:
        sys.modules.pop("app", None)


@pytest.fixture
def admin_loaded(loaded_small_db, monkeypatch):
    try:
        yield _client(monkeypatch, loaded_small_db, ADMIN_LOGIN)
    finally:
        sys.modules.pop("app", None)


def test_validated_requires_login(client):
    assert client.get("/api/validated-data").status_code == 401


def test_validated_forbidden_for_household(tmp_path, monkeypatch):
    try:
        c = _client(monkeypatch, tmp_path / "h.db", HOUSEHOLD_LOGIN)
        assert c.get("/api/validated-data").status_code == 403
    finally:
        sys.modules.pop("app", None)


def test_validated_empty_utility_and_seeded_approved_bills(admin_empty):
    c, _ = admin_empty
    j = c.get("/api/validated-data").json
    assert j["utility"]["data_source"] == "real"
    assert j["utility"]["monthly"] == [] and j["utility"]["annual"] == []
    crowd = j["crowdsourced"]
    assert crowd["data_source"] == "crowdsourced"
    # The demo seed has 3 approved bills and 1 pending; only approved count.
    assert [m["billing_month"] for m in crowd["monthly"]] == ["2026-01", "2026-02", "2026-03"]
    assert crowd["totals"]["approved_bills"] == 3
    assert crowd["monthly"][0] == {"billing_month": "2026-01", "households": 1, "bills": 1,
                                   "total_kwh": 384.2, "avg_kwh": 384.2}


def test_validated_excludes_deleted_and_unapproved(admin_empty):
    c, db = admin_empty
    with sqlite3.connect(db) as con:
        con.execute("UPDATE monthly_consumption SET deleted_at = CURRENT_TIMESTAMP WHERE billing_month = '2026-01'")
        con.execute("UPDATE monthly_consumption SET verification_status = 'rejected' WHERE billing_month = '2026-02'")
    crowd = c.get("/api/validated-data").json["crowdsourced"]
    assert [m["billing_month"] for m in crowd["monthly"]] == ["2026-03"]
    assert crowd["totals"]["approved_bills"] == 1


def test_validated_real_utility_records(admin_loaded):
    u = admin_loaded.get("/api/validated-data").json["utility"]
    assert len(u["monthly"]) == 72 and set(u["monthly"][0]) == {"year", "month", "energy_mwh"}
    assert [a["year"] for a in u["annual"]] == [2020, 2021, 2022, 2023, 2024, 2025]
    y2023 = next(a for a in u["annual"] if a["year"] == 2023)
    assert round(y2023["monthly_sum_mwh"]) == 38689 and round(y2023["total_mwh_reported"]) == 38369
    assert u["source"] == "GUIMELCO Residential.pdf"
