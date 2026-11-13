"""Approved submissions are final: admins edit or remove approved appliances (updating every
household that uses them) and delete approved bills, always with a reason the owners are told."""
import sqlite3
import sys

import pytest

from tests.conftest import _import_app
from tests.test_validated_data import ADMIN_LOGIN, HOUSEHOLD_LOGIN


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    db = tmp_path / "a.db"
    mod = _import_app(monkeypatch, db)
    try:
        yield mod, db
    finally:
        sys.modules.pop("app", None)


def _login(mod, creds):
    client = mod.app.test_client()
    assert client.post("/api/auth/login", json=creds).status_code == 200
    return client


def _other_approved_appliance(db):
    """An approved appliance submitted by a household other than the demo household."""
    with sqlite3.connect(db) as con:
        return con.execute(
            "SELECT a.appliance_id FROM appliances a JOIN households h ON h.household_id=a.household_id "
            "JOIN users u ON u.user_id=h.user_id WHERE u.email<>? AND a.verification_status='approved' "
            "ORDER BY a.appliance_id LIMIT 1",
            (HOUSEHOLD_LOGIN["email"],)).fetchone()[0]


def _own(db, table, key, status):
    with sqlite3.connect(db) as con:
        return con.execute(
            f"SELECT t.{key} FROM {table} t JOIN households h ON h.household_id=t.household_id "
            f"JOIN users u ON u.user_id=h.user_id WHERE u.email=? AND t.verification_status=?"
            + (" AND t.deleted_at IS NULL" if table == "monthly_consumption" else "")
            + " ORDER BY 1 LIMIT 1",
            (HOUSEHOLD_LOGIN["email"], status)).fetchone()[0]


def _add_to_inventory(household, appliance_id):
    r = household.post(f"/api/appliances/from-crowdsource/{appliance_id}",
                       json={"quantity": 2, "avg_daily_usage_hours": 5})
    assert r.status_code == 201, r.json
    return r.json["appliance"]["inventory_id"]


def _latest_note(client):
    return client.get("/api/notifications").json["notifications"][0]


def _note_reason(client, note):
    """The reason reaches households as the administrator's note on the notification detail."""
    return client.get(f"/api/notifications/{note['notification_id']}").json["notification"]["submission"]["reviewer_notes"]


def test_old_messages_stop_repeating_the_reason(app_db):
    mod, db = app_db
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        user_id = con.execute("SELECT user_id FROM users WHERE email=?", (HOUSEHOLD_LOGIN["email"],)).fetchone()[0]
        con.executemany("INSERT INTO notifications(user_id, title, message, type) VALUES (?, ?, ?, 'submission_update')", [
            (user_id, "Appliance removed", "An admin removed Fan from the approved appliances, so it was taken out of "
             "My Appliances. Reason: Not accurate. You can add a replacement from the approved list."),
            (user_id, "Bill deleted by admin", "An admin deleted your May 2026 bill. Reason: Wrong account."),
        ])
        mod.drop_repeated_reasons(con)
        messages = [r[0] for r in con.execute("SELECT message FROM notifications ORDER BY notification_id DESC LIMIT 2")]
    assert messages == [
        "An admin deleted your May 2026 bill.",
        "An admin removed Fan from the approved appliances, so it was taken out of My Appliances. "
        "You can add a replacement from the approved list.",
    ]


def test_approved_submissions_cannot_be_re_reviewed(app_db):
    mod, db = app_db
    admin = _login(mod, ADMIN_LOGIN)
    appliance_id = _other_approved_appliance(db)
    bill_id = _own(db, "monthly_consumption", "consumption_id", "approved")
    r = admin.patch(f"/api/admin/submissions/appliance/{appliance_id}",
                    json={"status": "rejected", "reviewer_notes": "wrong"})
    assert r.status_code == 409
    r = admin.patch(f"/api/admin/submissions/consumption/{bill_id}",
                    json={"status": "rejected", "reviewer_notes": "wrong"})
    assert r.status_code == 409


def test_edit_updates_every_inventory_and_notifies(app_db):
    mod, db = app_db
    appliance_id = _other_approved_appliance(db)
    household = _login(mod, HOUSEHOLD_LOGIN)
    inventory_id = _add_to_inventory(household, appliance_id)
    admin = _login(mod, ADMIN_LOGIN)

    assert admin.patch(f"/api/admin/appliances/{appliance_id}", json={"power_rating_watts": 55}).status_code == 400
    r = admin.patch(f"/api/admin/appliances/{appliance_id}",
                    json={"power_rating_watts": 55, "reason": "Nameplate says 55 W."})
    assert r.status_code == 200, r.json
    assert r.json["households_notified"] >= 1

    item = next(a for a in household.get("/api/my-appliances").json["appliances"] if a["inventory_id"] == inventory_id)
    assert (item["power_rating_watts"], item["quantity"], item["avg_daily_usage_hours"]) == (55, 2, 5)
    note = _latest_note(household)
    assert note["title"] == "Appliance updated" and "Nameplate says 55 W." in note["message"]
    assert "55 W" in note["message"]


def test_edit_only_for_approved_appliances(app_db):
    mod, db = app_db
    admin = _login(mod, ADMIN_LOGIN)
    pending = _own(db, "appliances", "appliance_id", "pending")
    r = admin.patch(f"/api/admin/appliances/{pending}", json={"power_rating_watts": 55, "reason": "x"})
    assert r.status_code == 409


def test_remove_takes_it_out_of_every_inventory_and_notifies(app_db):
    mod, db = app_db
    appliance_id = _other_approved_appliance(db)
    household = _login(mod, HOUSEHOLD_LOGIN)
    inventory_id = _add_to_inventory(household, appliance_id)
    admin = _login(mod, ADMIN_LOGIN)

    assert admin.post(f"/api/admin/appliances/{appliance_id}/remove", json={"reason": " "}).status_code == 400
    r = admin.post(f"/api/admin/appliances/{appliance_id}/remove", json={"reason": "Duplicate of another entry."})
    assert r.status_code == 200, r.json
    assert r.json["households_notified"] >= 1

    assert inventory_id not in [a["inventory_id"] for a in household.get("/api/my-appliances").json["appliances"]]
    assert household.post(f"/api/my-appliances/{inventory_id}/restore").status_code == 409
    catalog = household.get("/api/crowdsource/appliances").json
    assert appliance_id not in [a["catalog_id"] for a in catalog["appliances"]]
    note = _latest_note(household)
    assert note["title"] == "Appliance removed" and "Reason" not in note["message"]
    assert _note_reason(household, note) == "Duplicate of another entry."

    row = next(s for s in admin.get("/api/admin/submissions?status=all").json["submissions"]
               if s["submission_type"] == "appliance" and s["submission_id"] == appliance_id)
    assert row["verification_status"] == "rejected" and row["removed"] == 1
    # Already removed: a second removal is refused.
    assert admin.post(f"/api/admin/appliances/{appliance_id}/remove", json={"reason": "again"}).status_code == 409


def test_admin_deletes_approved_bill_with_reason(app_db):
    mod, db = app_db
    bill_id = _own(db, "monthly_consumption", "consumption_id", "approved")
    admin = _login(mod, ADMIN_LOGIN)
    assert admin.post(f"/api/admin/consumption/{bill_id}/delete", json={}).status_code == 400
    r = admin.post(f"/api/admin/consumption/{bill_id}/delete", json={"reason": "Bill photo is from another account."})
    assert r.status_code == 200, r.json
    assert bill_id not in [s["submission_id"] for s in admin.get("/api/admin/submissions?status=all").json["submissions"]
                           if s["submission_type"] == "consumption"]

    household = _login(mod, HOUSEHOLD_LOGIN)
    note = _latest_note(household)
    assert note["title"] == "Bill deleted by admin" and "Reason" not in note["message"]
    assert _note_reason(household, note) == "Bill photo is from another account."
    # Restoring it from Recently Deleted cannot bring back an approved bill.
    assert household.post(f"/api/consumption/{bill_id}/restore").status_code == 200
    restored = next(b for b in household.get("/api/consumption").json["records"] if b["consumption_id"] == bill_id)
    assert restored["verification_status"] == "rejected"


def test_household_cannot_change_specs_of_own_approved_submission(app_db):
    mod, db = app_db
    household = _login(mod, HOUSEHOLD_LOGIN)
    with sqlite3.connect(db) as con:
        appliance_id = con.execute(
            "SELECT a.appliance_id FROM appliances a JOIN households h ON h.household_id=a.household_id "
            "JOIN users u ON u.user_id=h.user_id WHERE u.email=? AND a.verification_status='approved' "
            "AND a.copied_from_appliance_id IS NULL LIMIT 1", (HOUSEHOLD_LOGIN["email"],)).fetchone()[0]
    r = household.patch(f"/api/appliances/{appliance_id}", json={
        "appliance_name": "Changed", "category_id": 1, "power_rating_watts": 10, "quantity": 1,
        "avg_daily_usage_hours": 1, "source_of_info": "user_manual"})
    assert r.status_code == 409


def test_startup_cleans_copies_of_no_longer_approved_appliances(app_db):
    mod, db = app_db
    appliance_id = _other_approved_appliance(db)
    household = _login(mod, HOUSEHOLD_LOGIN)
    inventory_id = _add_to_inventory(household, appliance_id)
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        con.execute("UPDATE appliances SET verification_status='rejected', reviewer_notes='Wrong rating.' "
                    "WHERE appliance_id=?", (appliance_id,))
        assert mod.remove_unapproved_inventory(con) == 1
        assert mod.remove_unapproved_inventory(con) == 0
    assert inventory_id not in [a["inventory_id"] for a in household.get("/api/my-appliances").json["appliances"]]
    note = _latest_note(household)
    assert note["title"] == "Appliance removed" and _note_reason(household, note) == "Wrong rating."


def test_deleted_sample_appliances_stay_deleted_after_restart(app_db, monkeypatch):
    mod, db = app_db
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM appliances").fetchone()[0] > 0  # a new database gets samples
        con.execute("DELETE FROM household_appliances WHERE source_appliance_id IS NOT NULL")
        con.execute("DELETE FROM appliances")
    sys.modules.pop("app", None)
    _import_app(monkeypatch, db)  # restart on the existing database
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM appliances").fetchone()[0] == 0
