"""Notification detail, read/unread, and household feedback to admins."""
import sqlite3
import sys

import pytest

from tests.conftest import _import_app
from tests.test_validated_data import ADMIN_LOGIN, HOUSEHOLD_LOGIN


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    db = tmp_path / "n.db"
    mod = _import_app(monkeypatch, db)
    try:
        yield mod, db
    finally:
        sys.modules.pop("app", None)


def _login(mod, creds):
    client = mod.app.test_client()
    assert client.post("/api/auth/login", json=creds).status_code == 200
    return client


def _pending_appliance(db):
    with sqlite3.connect(db) as con:
        return con.execute(
            "SELECT a.appliance_id FROM appliances a JOIN households h ON h.household_id=a.household_id "
            "JOIN users u ON u.user_id=h.user_id WHERE u.email=? AND a.verification_status='pending'",
            (HOUSEHOLD_LOGIN["email"],)).fetchone()[0]


def _review(mod, db, status="rejected", notes="Rating looks too high for this model."):
    admin = _login(mod, ADMIN_LOGIN)
    appliance_id = _pending_appliance(db)
    r = admin.patch(f"/api/admin/submissions/appliance/{appliance_id}", json={"status": status, "reviewer_notes": notes})
    assert r.status_code == 200
    return admin, appliance_id


def test_review_notification_links_to_submission_and_shows_status(app_db):
    mod, db = app_db
    _, appliance_id = _review(mod, db)
    household = _login(mod, HOUSEHOLD_LOGIN)
    notes = household.get("/api/notifications").json["notifications"]
    latest = notes[0]
    assert (latest["entity_type"], latest["entity_id"], latest["is_read"]) == ("appliance", appliance_id, 0)
    detail = household.get(f"/api/notifications/{latest['notification_id']}").json["notification"]
    assert detail["submission"]["verification_status"] == "rejected"
    assert detail["submission"]["reviewer_notes"] == "Rating looks too high for this model."
    assert detail["can_send_feedback"] is True


def test_mark_read_and_unread(app_db):
    mod, db = app_db
    _review(mod, db, status="approved", notes=None)
    household = _login(mod, HOUSEHOLD_LOGIN)
    nid = household.get("/api/notifications").json["notifications"][0]["notification_id"]
    assert household.patch(f"/api/notifications/{nid}", json={"is_read": True}).status_code == 200
    assert household.get(f"/api/notifications/{nid}").json["notification"]["is_read"] == 1
    assert household.patch(f"/api/notifications/{nid}", json={"is_read": False}).status_code == 200
    assert household.get(f"/api/notifications/{nid}").json["notification"]["is_read"] == 0
    assert household.patch(f"/api/notifications/{nid}", json={"is_read": "yes"}).status_code == 400
    assert household.post("/api/notifications/read-all").json["updated"] >= 1
    assert all(n["is_read"] for n in household.get("/api/notifications").json["notifications"])


def test_cannot_read_someone_elses_notification(app_db):
    mod, db = app_db
    admin, _ = _review(mod, db)
    household = _login(mod, HOUSEHOLD_LOGIN)
    nid = household.get("/api/notifications").json["notifications"][0]["notification_id"]
    assert admin.get(f"/api/notifications/{nid}").status_code == 404
    assert admin.patch(f"/api/notifications/{nid}", json={"is_read": True}).status_code == 404
    assert admin.post(f"/api/notifications/{nid}/feedback", json={"message": "hi"}).status_code == 404


def test_feedback_reaches_admins(app_db):
    mod, db = app_db
    admin, appliance_id = _review(mod, db)
    household = _login(mod, HOUSEHOLD_LOGIN)
    nid = household.get("/api/notifications").json["notifications"][0]["notification_id"]
    assert household.post(f"/api/notifications/{nid}/feedback", json={"message": "  "}).status_code == 400
    assert household.post(f"/api/notifications/{nid}/feedback", json={"message": "x" * 1001}).status_code == 400
    r = household.post(f"/api/notifications/{nid}/feedback", json={"message": "The nameplate says 450 W, photo attached."})
    assert r.status_code == 201
    assert [f["message"] for f in household.get(f"/api/notifications/{nid}").json["notification"]["feedback"]] == [
        "The nameplate says 450 W, photo attached."]

    admin_note = admin.get("/api/notifications").json["notifications"][0]
    assert admin_note["entity_type"] == "feedback" and admin_note["title"].startswith("Feedback from ")
    detail = admin.get(f"/api/notifications/{admin_note['notification_id']}").json["notification"]
    assert detail["feedback_received"]["message"] == "The nameplate says 450 W, photo attached."
    assert detail["submission"]["id"] == appliance_id and detail["can_send_feedback"] is False
    # Admins cannot reply through their feedback notification.
    assert admin.post(f"/api/notifications/{admin_note['notification_id']}/feedback", json={"message": "ok"}).status_code == 400


def test_old_notifications_are_linked_from_the_audit_log(app_db):
    mod, db = app_db
    _, appliance_id = _review(mod, db)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE notifications SET entity_type=NULL, entity_id=NULL")
        con.row_factory = sqlite3.Row
        mod.link_review_notifications(con)
        row = con.execute(
            "SELECT entity_type, entity_id FROM notifications WHERE title='Submission reviewed' ORDER BY notification_id DESC"
        ).fetchone()
    assert (row["entity_type"], row["entity_id"]) == ("appliance", appliance_id)
