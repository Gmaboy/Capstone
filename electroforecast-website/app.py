from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Iterator

from flask import Flask, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("ELECTROFORECAST_DB", ROOT / "database" / "electroforecast.db"))
SCHEMA_PATH = ROOT / "database" / "schema.sqlite.sql"
BILL_IMAGE_DIR = Path(os.environ.get("ELECTROFORECAST_UPLOADS", ROOT / "database" / "uploads" / "bills"))
BILL_IMAGE_MAX_BYTES = 5 * 1024 * 1024

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("ELECTROFORECAST_SECRET", "electroforecast-local-development-key"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,
)

CATALOG_APPROVAL_NOTE = (
    "Automatically accepted from an administrator-approved appliance rating."
)

from tools.common.locations import BARANGAYS as GUIMARAS_BARANGAYS


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def link_review_notifications(db: sqlite3.Connection) -> None:
    """Link older 'Submission reviewed' notifications to their submission.

    Each review wrote an audit row in the same transaction, so the decision, submission type
    and timestamp identify the submission; only notifications whose owner matches are linked.
    """
    pending = db.execute(
        """
        SELECT notification_id, user_id, message, created_at FROM notifications
        WHERE type='submission_update' AND entity_id IS NULL AND title='Submission reviewed'
        """
    ).fetchall()
    owners = {
        "appliance": "SELECT h.user_id FROM appliances s JOIN households h ON h.household_id=s.household_id WHERE s.appliance_id=?",
        "consumption": "SELECT h.user_id FROM monthly_consumption s JOIN households h ON h.household_id=s.household_id WHERE s.consumption_id=?",
    }
    for note in pending:
        match = re.fullmatch(r"Your (appliance|consumption) submission was (approved|rejected)\.", note["message"])
        if not match:
            continue
        kind, decision = match.groups()
        candidates = db.execute(
            """
            SELECT entity_id FROM audit_logs
            WHERE action=? AND entity_type=? AND entity_id IS NOT NULL
              AND ABS(strftime('%s', created_at) - strftime('%s', ?)) <= 2
            ORDER BY audit_id
            """,
            (decision, kind, note["created_at"]),
        ).fetchall()
        for candidate in candidates:
            owner = db.execute(owners[kind], (candidate["entity_id"],)).fetchone()
            if not owner:
                # Submission since deleted: its creator is recorded in the 'created' audit row.
                owner = db.execute(
                    """
                    SELECT actor_user_id AS user_id FROM audit_logs
                    WHERE action='created' AND entity_type=? AND entity_id=?
                    ORDER BY audit_id LIMIT 1
                    """,
                    ("appliance" if kind == "appliance" else "monthly_consumption", candidate["entity_id"]),
                ).fetchone()
            if owner and owner["user_id"] == note["user_id"]:
                db.execute(
                    "UPDATE notifications SET entity_type=?, entity_id=? WHERE notification_id=?",
                    (kind, candidate["entity_id"], note["notification_id"]),
                )
                break


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        appliance_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(appliances)")
        }
        if "copied_from_appliance_id" not in appliance_columns:
            db.execute(
                "ALTER TABLE appliances ADD COLUMN copied_from_appliance_id INTEGER"
            )
        if "reviewer_notes_read_at" not in appliance_columns:
            db.execute(
                "ALTER TABLE appliances ADD COLUMN reviewer_notes_read_at TEXT"
            )
        if "removed_at" not in appliance_columns:
            db.execute("ALTER TABLE appliances ADD COLUMN removed_at TEXT")
        household_appliance_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(household_appliances)")
        }
        if "deleted_at" not in household_appliance_columns:
            db.execute(
                "ALTER TABLE household_appliances ADD COLUMN deleted_at TEXT"
            )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_household_appliances_deleted
            ON household_appliances(household_id, deleted_at)
            """
        )
        consumption_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(monthly_consumption)")
        }
        if "deleted_at" not in consumption_columns:
            db.execute("ALTER TABLE monthly_consumption ADD COLUMN deleted_at TEXT")
        for column_name, column_type in (
            ("reviewer_notes_read_at", "TEXT"),
            ("bill_image_filename", "TEXT"),
            ("bill_image_original_name", "TEXT"),
            ("bill_image_mime", "TEXT"),
            ("bill_image_size_bytes", "INTEGER"),
        ):
            if column_name not in consumption_columns:
                db.execute(
                    f"ALTER TABLE monthly_consumption ADD COLUMN {column_name} {column_type}"
                )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_consumption_deleted
            ON monthly_consumption(household_id, deleted_at)
            """
        )
        notification_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(notifications)")
        }
        for column_name, column_type in (("entity_type", "TEXT"), ("entity_id", "INTEGER")):
            if column_name not in notification_columns:
                db.execute(f"ALTER TABLE notifications ADD COLUMN {column_name} {column_type}")
        link_review_notifications(db)
        db.execute(
            """
            UPDATE appliances
            SET verification_status='approved',
                reviewer_notes=?,
                reviewer_notes_read_at=COALESCE(reviewer_notes_read_at, ?),
                reviewed_at=COALESCE(reviewed_at, ?)
            WHERE copied_from_appliance_id IN (
              SELECT appliance_id FROM appliances WHERE verification_status='approved'
            )
            """,
            (CATALOG_APPROVAL_NOTE, now(), now()),
        )
        remove_unapproved_inventory(db)
        drop_repeated_reasons(db)

        roles = {
            "admin": "Full system and validation access",
            "guimelco": "Utility stakeholder access to validated data and reports",
            "researcher": "Research access to approved analytical datasets",
            "household": "Crowdsourcing participant access",
        }
        for role_name, description in roles.items():
            db.execute(
                "INSERT OR IGNORE INTO roles(role_name, description) VALUES (?, ?)",
                (role_name, description),
            )

        for category in (
            "Cooling",
            "Kitchen Appliances",
            "Laundry",
            "Entertainment",
            "Lighting",
            "Other",
        ):
            db.execute(
                "INSERT OR IGNORE INTO appliance_categories(category_name) VALUES (?)",
                (category,),
            )

        role_ids = {
            row["role_name"]: row["role_id"]
            for row in db.execute("SELECT role_id, role_name FROM roles")
        }
        seed_users = (
            (
                role_ids["admin"],
                "Greence Mark",
                "admin@electroforecast.local",
                "Admin123!",
                "+63 917 000 0001",
            ),
            (
                role_ids["household"],
                "Juan Dela Cruz",
                "household@electroforecast.local",
                "Household123!",
                "+63 917 000 0002",
            ),
            (
                role_ids["household"],
                "Maria Santos",
                "maria@electroforecast.local",
                "Household123!",
                "+63 917 000 0003",
            ),
        )
        for role_id, full_name, email, password, contact in seed_users:
            if not db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                db.execute(
                    """
                    INSERT INTO users(role_id, full_name, email, password_hash, contact_no)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (role_id, full_name, email, generate_password_hash(password), contact),
                )

        household_users = db.execute(
            """
            SELECT u.user_id, u.email
            FROM users u JOIN roles r ON r.role_id = u.role_id
            WHERE r.role_name = 'household'
            """
        ).fetchall()
        for user in household_users:
            db.execute(
                """
                INSERT OR IGNORE INTO households
                    (user_id, barangay, municipality, province, household_size, meter_number)
                VALUES (?, ?, 'Jordan', 'Guimaras', ?, ?)
                """,
                (
                    user["user_id"],
                    "San Miguel" if user["email"].startswith("household") else "Poblacion",
                    5 if user["email"].startswith("household") else 4,
                    f"GMR-{user['user_id']:05d}",
                ),
            )

        primary_household = db.execute(
            """
            SELECT h.household_id
            FROM households h JOIN users u ON u.user_id = h.user_id
            WHERE u.email = 'household@electroforecast.local'
            """
        ).fetchone()
        secondary_household = db.execute(
            """
            SELECT h.household_id
            FROM households h JOIN users u ON u.user_id = h.user_id
            WHERE u.email = 'maria@electroforecast.local'
            """
        ).fetchone()
        category_ids = {
            row["category_name"]: row["category_id"]
            for row in db.execute("SELECT category_id, category_name FROM appliance_categories")
        }
        if primary_household and not db.execute(
            "SELECT 1 FROM appliances WHERE household_id = ?",
            (primary_household["household_id"],),
        ).fetchone():
            appliances = (
                ("Air Conditioner (1.5 HP)", "Carrier", "Aura", "Cooling", 1120, 1, 8, "nameplate_label", "approved"),
                ("Refrigerator (2 Door)", "LG", "Smart Inverter", "Kitchen Appliances", 150, 1, 24, "user_manual", "approved"),
                ("Washing Machine (7 kg)", "Samsung", "WA70", "Laundry", 450, 1, 1, "nameplate_label", "pending"),
                ('LED Television (43")', "TCL", "P635", "Entertainment", 100, 1, 6, "retailer_specs", "rejected"),
            )
            for item in appliances:
                db.execute(
                    """
                    INSERT INTO appliances
                      (household_id, appliance_name, brand, model, category_id,
                       power_rating_watts, quantity, avg_daily_usage_hours,
                       source_of_info, verification_status, reviewer_notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        primary_household["household_id"],
                        item[0],
                        item[1],
                        item[2],
                        category_ids[item[3]],
                        item[4],
                        item[5],
                        item[6],
                        item[7],
                        item[8],
                        "Please attach the exact model specification." if item[8] == "rejected" else None,
                    ),
                )
        if secondary_household:
            if not db.execute(
                """
                SELECT 1 FROM appliances
                WHERE household_id = ? AND appliance_name = 'Induction Cooker'
                """,
                (secondary_household["household_id"],),
            ).fetchone():
                db.execute(
                    """
                    INSERT INTO appliances
                      (household_id, appliance_name, category_id, power_rating_watts,
                       quantity, avg_daily_usage_hours, source_of_info, verification_status)
                    VALUES (?, 'Induction Cooker', ?, 2000, 1, 1.5, 'nameplate_label', 'pending')
                    """,
                    (secondary_household["household_id"], category_ids["Kitchen Appliances"]),
                )
            if not db.execute(
                """
                SELECT 1 FROM appliances
                WHERE household_id = ? AND appliance_name = 'Air Conditioner (1.5 HP)'
                """,
                (secondary_household["household_id"],),
            ).fetchone():
                db.execute(
                    """
                    INSERT INTO appliances
                      (household_id, appliance_name, brand, model, category_id,
                       power_rating_watts, quantity, avg_daily_usage_hours,
                       source_of_info, verification_status, reviewer_notes)
                    VALUES (?, 'Air Conditioner (1.5 HP)', 'Carrier', 'Aura', ?,
                            1120, 1, 6, 'user_manual', 'approved',
                            'Approved catalog reference record.')
                    """,
                    (secondary_household["household_id"], category_ids["Cooling"]),
                )
            if not db.execute(
                """
                SELECT 1 FROM appliances
                WHERE household_id = ? AND appliance_name = 'Electric Fan (16 inch)'
                """,
                (secondary_household["household_id"],),
            ).fetchone():
                db.execute(
                    """
                    INSERT INTO appliances
                      (household_id, appliance_name, brand, model, category_id,
                       power_rating_watts, quantity, avg_daily_usage_hours,
                       source_of_info, verification_status, reviewer_notes)
                    VALUES (?, 'Electric Fan (16 inch)', 'Hanabishi', 'Windmill', ?,
                            65, 1, 8, 'nameplate_label', 'approved',
                            'Approved catalog reference record.')
                    """,
                    (secondary_household["household_id"], category_ids["Cooling"]),
                )

        if primary_household and not db.execute(
            "SELECT 1 FROM household_appliances WHERE household_id = ?",
            (primary_household["household_id"],),
        ).fetchone():
            db.execute(
                """
                INSERT OR IGNORE INTO household_appliances
                  (household_id, source_appliance_id, category_id,
                   appliance_name, brand, model, power_rating_watts,
                   quantity, avg_daily_usage_hours, source_of_info)
                SELECT household_id, appliance_id, category_id,
                       appliance_name, brand, model, power_rating_watts,
                       quantity, avg_daily_usage_hours, source_of_info
                FROM appliances
                WHERE household_id=? AND verification_status='approved'
                """,
                (primary_household["household_id"],),
            )

        if primary_household and not db.execute(
            "SELECT 1 FROM monthly_consumption WHERE household_id = ?",
            (primary_household["household_id"],),
        ).fetchone():
            consumption_rows = (
                ("2026-01", 384.2, 4302.15, 8384.2, "approved"),
                ("2026-02", 365.8, 4110.40, 8750.0, "approved"),
                ("2026-03", 402.5, 4519.20, 9152.5, "approved"),
                ("2026-04", 426.7, 4791.55, 9579.2, "pending"),
            )
            for billing_month, kwh, amount, reading, status in consumption_rows:
                db.execute(
                    """
                    INSERT INTO monthly_consumption
                      (household_id, billing_month, consumption_kwh, bill_amount_php,
                       meter_reading, source_of_info, verification_status)
                    VALUES (?, ?, ?, ?, ?, 'electric_bill', ?)
                    """,
                    (
                        primary_household["household_id"],
                        billing_month,
                        kwh,
                        amount,
                        reading,
                        status,
                    ),
                )


def user_payload(user_id: int) -> dict[str, Any] | None:
    with get_db() as db:
        user = db.execute(
            """
            SELECT u.user_id, u.full_name, u.email, u.contact_no, u.status,
                   r.role_name AS role
            FROM users u JOIN roles r ON r.role_id = u.role_id
            WHERE u.user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if not user:
            return None
        payload = dict(user)
        household = db.execute(
            """
            SELECT household_id, barangay, municipality, province, household_size, meter_number
            FROM households WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        payload["household"] = row_dict(household)
        return payload


def require_auth(*roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                return jsonify(error="Authentication required"), 401
            user = user_payload(int(user_id))
            if not user or user["status"] != "active":
                session.clear()
                return jsonify(error="Account is unavailable"), 401
            if roles and user["role"] not in roles:
                return jsonify(error="You do not have permission for this action"), 403
            request.current_user = user
            return view(*args, **kwargs)

        return wrapped

    return decorator


def household_id_for(user_id: int, db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT household_id FROM households WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row:
        raise ValueError("Household profile not found")
    return int(row["household_id"])


def json_body() -> dict[str, Any]:
    return request.get_json(silent=True) or {}


def form_or_json_body() -> dict[str, Any]:
    return request.form.to_dict() if request.form else json_body()


def text_value(data: dict[str, Any], key: str, required: bool = False) -> str | None:
    value = str(data.get(key, "")).strip()
    if required and not value:
        raise ValueError(f"{key.replace('_', ' ').title()} is required")
    return value or None


def boolean_value(data: dict[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key.replace('_', ' ').title()} must be true or false")
    return value


def load_user_settings(db: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    db.execute("INSERT OR IGNORE INTO user_settings(user_id) VALUES (?)", (user_id,))
    row = db.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone()
    settings = dict(row)
    for key in (
        "notify_high_demand",
        "notify_rating_updates",
        "notify_weekly_summary",
        "show_confidence_intervals",
        "show_demand_gauge",
        "compact_table_view",
    ):
        settings[key] = bool(settings[key])
    return settings


def login_destination(user_id: int, role: str) -> str:
    default_page = (
        "admin-dashboard.html"
        if role in ("admin", "guimelco", "researcher")
        else "user-portal.html"
    )
    with get_db() as db:
        landing_page = load_user_settings(db, user_id)["landing_page"]
    return {
        "forecasting": "forecasting.html",
        "demand_classification": "demand-classification.html",
    }.get(landing_page, default_page)


def number_value(
    data: dict[str, Any],
    key: str,
    *,
    minimum: float,
    maximum: float,
    required: bool = True,
) -> float | None:
    raw = data.get(key)
    if raw in (None, "") and not required:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key.replace('_', ' ').title()} must be a number")
    if value < minimum or value > maximum:
        raise ValueError(
            f"{key.replace('_', ' ').title()} must be between {minimum:g} and {maximum:g}"
        )
    return value


def id_list(data: dict[str, Any], key: str, maximum: int = 100) -> list[int]:
    raw_ids = data.get(key)
    if not isinstance(raw_ids, list) or not raw_ids:
        raise ValueError("Select at least one item")
    if len(raw_ids) > maximum:
        raise ValueError(f"You can permanently delete up to {maximum} items at once")
    try:
        values = list(dict.fromkeys(int(value) for value in raw_ids))
    except (TypeError, ValueError):
        raise ValueError("Selected items are invalid")
    if any(value <= 0 for value in values):
        raise ValueError("Selected items are invalid")
    return values


def bill_image_upload(required: bool = True) -> dict[str, Any] | None:
    uploaded = request.files.get("bill_image")
    if not uploaded or not uploaded.filename:
        if required:
            raise ValueError("A clear picture of the electricity bill is required")
        return None
    contents = uploaded.read(BILL_IMAGE_MAX_BYTES + 1)
    if len(contents) > BILL_IMAGE_MAX_BYTES:
        raise ValueError("Bill picture must be 5 MB or smaller")
    if contents.startswith(b"\xff\xd8\xff"):
        extension, mime_type = "jpg", "image/jpeg"
    elif contents.startswith(b"\x89PNG\r\n\x1a\n"):
        extension, mime_type = "png", "image/png"
    elif len(contents) >= 12 and contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        extension, mime_type = "webp", "image/webp"
    else:
        raise ValueError("Bill picture must be a valid JPG, PNG, or WebP image")
    original_name = secure_filename(uploaded.filename)[:255] or f"bill.{extension}"
    return {
        "filename": f"{secrets.token_hex(20)}.{extension}",
        "original_name": original_name,
        "mime_type": mime_type,
        "size_bytes": len(contents),
        "contents": contents,
    }


def save_bill_image(image: dict[str, Any]) -> None:
    BILL_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    (BILL_IMAGE_DIR / image["filename"]).write_bytes(image["contents"])


def delete_bill_image(filename: str | None) -> None:
    if not filename or Path(filename).name != filename:
        return
    (BILL_IMAGE_DIR / filename).unlink(missing_ok=True)


def audit(
    db: sqlite3.Connection,
    actor_user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    details: dict[str, Any] | str | None = None,
) -> None:
    detail_text = json.dumps(details, ensure_ascii=False) if isinstance(details, dict) else details
    db.execute(
        """
        INSERT INTO audit_logs(actor_user_id, action, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (actor_user_id, action, entity_type, entity_id, detail_text),
    )


@app.errorhandler(sqlite3.IntegrityError)
def handle_integrity_error(error):
    if "monthly_consumption.household_id, monthly_consumption.billing_month" in str(error):
        return jsonify(error="A consumption record for that billing month already exists"), 409
    return jsonify(error="The submitted record conflicts with existing data"), 409


@app.errorhandler(413)
def handle_too_large(_error):
    return jsonify(error="Request is too large"), 413


@app.get("/api/health")
def health():
    return jsonify(status="ok", database=str(DATABASE_PATH.name))


@app.get("/api/locations/guimaras")
def guimaras_locations():
    return jsonify(
        province="Guimaras",
        municipality_count=len(GUIMARAS_BARANGAYS),
        barangay_count=sum(len(items) for items in GUIMARAS_BARANGAYS.values()),
        psgc_reference_date="2025-07-31",
        municipalities=[
            {"name": municipality, "barangays": list(barangays)}
            for municipality, barangays in GUIMARAS_BARANGAYS.items()
        ],
    )


@app.post("/api/auth/register")
def register():
    data = json_body()
    try:
        full_name = text_value(data, "full_name", True)
        email = text_value(data, "email", True).lower()
        barangay = text_value(data, "barangay", True)
        municipality = text_value(data, "municipality", True)
        contact_no = text_value(data, "contact_no")
        password = str(data.get("password", ""))
        password_confirmation = str(data.get("password_confirmation", ""))

        if not 2 <= len(full_name) <= 100:
            raise ValueError("Full name must be between 2 and 100 characters")
        if len(email) > 150 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Enter a valid email address")
        if len(barangay) > 100:
            raise ValueError("Barangay must be 100 characters or fewer")
        if municipality not in GUIMARAS_BARANGAYS:
            raise ValueError("Select a valid Guimaras municipality")
        if barangay not in GUIMARAS_BARANGAYS[municipality]:
            raise ValueError(f"Select a valid barangay in {municipality}")
        if contact_no and len(contact_no) > 30:
            raise ValueError("Contact number must be 30 characters or fewer")
        if (
            len(password) < 8
            or not re.search(r"[a-z]", password)
            or not re.search(r"[A-Z]", password)
            or not re.search(r"\d", password)
        ):
            raise ValueError(
                "Password must be at least 8 characters and include uppercase, lowercase, and a number"
            )
        if password != password_confirmation:
            raise ValueError("Passwords do not match")
        if data.get("terms_accepted") is not True:
            raise ValueError("You must confirm the data contribution agreement")

    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400

    with get_db() as db:
        if db.execute(
            "SELECT 1 FROM users WHERE email=? COLLATE NOCASE", (email,)
        ).fetchone():
            return jsonify(error="An account with this email already exists"), 409
        household_role = db.execute(
            "SELECT role_id FROM roles WHERE role_name='household'"
        ).fetchone()
        if not household_role:
            return jsonify(error="Household registration is temporarily unavailable"), 503
        cursor = db.execute(
            """
            INSERT INTO users
              (role_id, full_name, email, password_hash, contact_no)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                household_role["role_id"],
                full_name,
                email,
                generate_password_hash(password),
                contact_no,
            ),
        )
        user_id = int(cursor.lastrowid)
        household_cursor = db.execute(
            """
            INSERT INTO households
              (user_id, barangay, municipality, province)
            VALUES (?, ?, ?, 'Guimaras')
            """,
            (user_id, barangay, municipality),
        )
        audit(
            db,
            user_id,
            "registered",
            "user",
            user_id,
            {
                "household_id": int(household_cursor.lastrowid),
                "municipality": municipality,
                "province": "Guimaras",
            },
        )

    session.clear()
    session["user_id"] = user_id
    return jsonify(user=user_payload(user_id), redirect="user-portal.html"), 201


@app.post("/api/auth/login")
def login():
    data = json_body()
    email = text_value(data, "email", True)
    password = text_value(data, "password", True)
    with get_db() as db:
        user = db.execute(
            """
            SELECT u.user_id, u.password_hash, u.status
            FROM users u WHERE u.email = ? COLLATE NOCASE
            """,
            (email,),
        ).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify(error="Invalid email or password"), 401
    if user["status"] != "active":
        return jsonify(error="This account is inactive"), 403
    session.clear()
    session["user_id"] = int(user["user_id"])
    payload = user_payload(int(user["user_id"]))
    destination = login_destination(int(user["user_id"]), payload["role"])
    return jsonify(user=payload, redirect=destination)


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/auth/me")
@require_auth()
def me():
    return jsonify(user=request.current_user)


@app.get("/api/settings")
@require_auth()
def get_settings():
    user = request.current_user
    with get_db() as db:
        stored = load_user_settings(db, user["user_id"])
    return jsonify(
        profile={
            "full_name": user["full_name"],
            "email": user["email"],
            "contact_no": user["contact_no"] or "",
            "role": user["role"],
        },
        preferences={
            key: stored[key]
            for key in (
                "notify_high_demand",
                "notify_rating_updates",
                "notify_weekly_summary",
                "forecast_horizon",
                "forecast_granularity",
                "measurement_unit",
                "landing_page",
                "show_confidence_intervals",
                "show_demand_gauge",
                "compact_table_view",
            )
        },
        data_source={
            "data_refresh_frequency": stored["data_refresh_frequency"],
            "default_file_format": stored["default_file_format"],
        },
    )


@app.patch("/api/settings")
@require_auth()
def update_settings():
    data = json_body()
    section = text_value(data, "section", True)
    user_id = request.current_user["user_id"]

    try:
        if section == "profile":
            full_name = text_value(data, "full_name", True)
            email = text_value(data, "email", True).lower()
            contact_no = text_value(data, "contact_no")
            if not 2 <= len(full_name) <= 100:
                raise ValueError("Full name must be between 2 and 100 characters")
            if len(email) > 150 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
                raise ValueError("Enter a valid email address")
            if contact_no and len(contact_no) > 30:
                raise ValueError("Contact number must be 30 characters or fewer")
            with get_db() as db:
                duplicate = db.execute(
                    "SELECT 1 FROM users WHERE email=? COLLATE NOCASE AND user_id<>?",
                    (email, user_id),
                ).fetchone()
                if duplicate:
                    return jsonify(error="An account with this email already exists"), 409
                db.execute(
                    """
                    UPDATE users
                    SET full_name=?, email=?, contact_no=?, updated_at=?
                    WHERE user_id=?
                    """,
                    (full_name, email, contact_no, now(), user_id),
                )
                audit(
                    db,
                    user_id,
                    "updated",
                    "user_profile",
                    user_id,
                    {"full_name": full_name, "email": email, "contact_no": contact_no},
                )
            return jsonify(ok=True, user=user_payload(user_id))

        if section == "preferences":
            values = {
                "notify_high_demand": boolean_value(data, "notify_high_demand"),
                "notify_rating_updates": boolean_value(data, "notify_rating_updates"),
                "notify_weekly_summary": boolean_value(data, "notify_weekly_summary"),
                "forecast_horizon": text_value(data, "forecast_horizon", True),
                "forecast_granularity": text_value(data, "forecast_granularity", True),
                "measurement_unit": text_value(data, "measurement_unit", True),
                "landing_page": text_value(data, "landing_page", True),
                "show_confidence_intervals": boolean_value(data, "show_confidence_intervals"),
                "show_demand_gauge": boolean_value(data, "show_demand_gauge"),
                "compact_table_view": boolean_value(data, "compact_table_view"),
            }
            allowed = {
                "forecast_horizon": {"7_days", "14_days", "30_days"},
                "forecast_granularity": {"daily", "weekly", "monthly"},
                "measurement_unit": {"kwh", "mwh"},
                "landing_page": {"role_default", "forecasting", "demand_classification"},
            }
            for key, choices in allowed.items():
                if values[key] not in choices:
                    raise ValueError(f"Select a valid {key.replace('_', ' ')}")
            with get_db() as db:
                load_user_settings(db, user_id)
                db.execute(
                    """
                    UPDATE user_settings SET
                      notify_high_demand=?, notify_rating_updates=?, notify_weekly_summary=?,
                      forecast_horizon=?, forecast_granularity=?, measurement_unit=?, landing_page=?,
                      show_confidence_intervals=?, show_demand_gauge=?, compact_table_view=?, updated_at=?
                    WHERE user_id=?
                    """,
                    (
                        int(values["notify_high_demand"]),
                        int(values["notify_rating_updates"]),
                        int(values["notify_weekly_summary"]),
                        values["forecast_horizon"],
                        values["forecast_granularity"],
                        values["measurement_unit"],
                        values["landing_page"],
                        int(values["show_confidence_intervals"]),
                        int(values["show_demand_gauge"]),
                        int(values["compact_table_view"]),
                        now(),
                        user_id,
                    ),
                )
                audit(db, user_id, "updated", "user_settings", user_id, values)
            return jsonify(ok=True)

        if section == "data_source":
            refresh = text_value(data, "data_refresh_frequency", True)
            file_format = text_value(data, "default_file_format", True)
            if refresh not in {"daily", "weekly", "manual"}:
                raise ValueError("Select a valid data refresh frequency")
            if file_format not in {"csv", "xlsx", "json"}:
                raise ValueError("Select a valid default file format")
            with get_db() as db:
                load_user_settings(db, user_id)
                db.execute(
                    """
                    UPDATE user_settings
                    SET data_refresh_frequency=?, default_file_format=?, updated_at=?
                    WHERE user_id=?
                    """,
                    (refresh, file_format, now(), user_id),
                )
                audit(
                    db,
                    user_id,
                    "updated",
                    "user_settings",
                    user_id,
                    {"data_refresh_frequency": refresh, "default_file_format": file_format},
                )
            return jsonify(ok=True)

        raise ValueError("Select a valid settings section")
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400


@app.patch("/api/settings/password")
@require_auth()
def update_settings_password():
    data = json_body()
    current_password = str(data.get("current_password", ""))
    new_password = str(data.get("new_password", ""))
    confirmation = str(data.get("password_confirmation", ""))
    try:
        if not current_password:
            raise ValueError("Current password is required")
        if (
            len(new_password) < 8
            or not re.search(r"[a-z]", new_password)
            or not re.search(r"[A-Z]", new_password)
            or not re.search(r"\d", new_password)
        ):
            raise ValueError(
                "New password must be at least 8 characters and include uppercase, lowercase, and a number"
            )
        if new_password != confirmation:
            raise ValueError("Passwords do not match")
    except ValueError as error:
        return jsonify(error=str(error)), 400

    user_id = request.current_user["user_id"]
    with get_db() as db:
        account = db.execute(
            "SELECT password_hash FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if not account or not check_password_hash(account["password_hash"], current_password):
            return jsonify(error="Current password is incorrect"), 400
        db.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE user_id=?",
            (generate_password_hash(new_password), now(), user_id),
        )
        audit(db, user_id, "changed_password", "user", user_id)
    return jsonify(ok=True)


@app.get("/api/categories")
@require_auth()
def categories():
    with get_db() as db:
        rows = db.execute(
            "SELECT category_id, category_name FROM appliance_categories ORDER BY category_name"
        ).fetchall()
    return jsonify(categories=[dict(row) for row in rows])


@app.get("/api/portal/summary")
@require_auth("household")
def portal_summary():
    user = request.current_user
    with get_db() as db:
        household_id = household_id_for(user["user_id"], db)
        inventory = db.execute(
            """
            SELECT COUNT(*) AS count,
                   COALESCE(SUM(power_rating_watts * quantity * avg_daily_usage_hours / 1000.0), 0) AS daily_kwh
            FROM household_appliances
            WHERE household_id = ? AND deleted_at IS NULL
            """,
            (household_id,),
        ).fetchone()
        submissions = db.execute(
            """
            SELECT COUNT(*) AS count,
                   SUM(CASE WHEN verification_status='pending' THEN 1 ELSE 0 END) AS pending
            FROM appliances WHERE household_id = ?
            """,
            (household_id,),
        ).fetchone()
        consumption = db.execute(
            """
            SELECT COUNT(*) AS count,
                   SUM(CASE WHEN verification_status='pending' THEN 1 ELSE 0 END) AS pending
            FROM monthly_consumption WHERE household_id = ? AND deleted_at IS NULL
            """,
            (household_id,),
        ).fetchone()
        latest = db.execute(
            """
            SELECT billing_month, consumption_kwh, verification_status
            FROM monthly_consumption WHERE household_id = ? AND deleted_at IS NULL
            ORDER BY billing_month DESC LIMIT 1
            """,
            (household_id,),
        ).fetchone()
        approved_points = db.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM appliances WHERE household_id=? AND verification_status='approved') +
              (SELECT COUNT(*) FROM monthly_consumption WHERE household_id=? AND verification_status='approved' AND deleted_at IS NULL)
              AS approved_count
            """,
            (household_id, household_id),
        ).fetchone()["approved_count"]
        total_points = int(submissions["count"]) + int(consumption["count"])
    return jsonify(
        summary={
            "appliance_count": int(inventory["count"]),
            "estimated_daily_kwh": round(float(inventory["daily_kwh"]), 2),
            "estimated_monthly_kwh": round(float(inventory["daily_kwh"]) * 30, 2),
            "latest_consumption": row_dict(latest),
            "pending_count": int(submissions["pending"] or 0) + int(consumption["pending"] or 0),
            "approved_count": int(approved_points),
            "total_submissions": total_points,
            "data_readiness_pct": round((approved_points / total_points) * 100) if total_points else 0,
        }
    )


APPLIANCE_SELECT = """
SELECT a.appliance_id, a.appliance_name, a.brand, a.model,
       a.power_rating_watts, a.quantity, a.avg_daily_usage_hours,
       a.source_of_info, a.verification_status, a.reviewer_notes,
       a.reviewer_notes_read_at,
       CASE
         WHEN a.reviewer_notes IS NOT NULL
          AND TRIM(a.reviewer_notes) <> ''
          AND a.reviewer_notes_read_at IS NULL THEN 1 ELSE 0
       END AS reviewer_notes_unread,
       a.copied_from_appliance_id, a.created_at, a.updated_at,
       c.category_id, c.category_name,
       EXISTS(
         SELECT 1 FROM household_appliances ha
         WHERE ha.household_id=a.household_id
           AND ha.source_appliance_id=a.appliance_id
           AND ha.deleted_at IS NULL
       ) AS in_inventory,
       EXISTS(
         SELECT 1 FROM household_appliances ha
         WHERE ha.household_id=a.household_id
           AND ha.source_appliance_id=a.appliance_id
           AND ha.deleted_at IS NOT NULL
       ) AS recently_deleted,
       ROUND(a.power_rating_watts * a.quantity * a.avg_daily_usage_hours / 1000.0, 3)
         AS estimated_daily_kwh
FROM appliances a
JOIN appliance_categories c ON c.category_id = a.category_id
"""


@app.get("/api/appliances")
@require_auth("household")
def list_appliances():
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        rows = db.execute(
            APPLIANCE_SELECT + " WHERE a.household_id = ? ORDER BY a.updated_at DESC",
            (household_id,),
        ).fetchall()
    return jsonify(appliances=[dict(row) for row in rows])


@app.post("/api/appliances/<int:appliance_id>/reviewer-notes/read")
@require_auth("household")
def mark_appliance_reviewer_notes_read(appliance_id: int):
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        row = db.execute(
            """
            SELECT reviewer_notes, reviewer_notes_read_at
            FROM appliances
            WHERE appliance_id=? AND household_id=?
            """,
            (appliance_id, household_id),
        ).fetchone()
        if not row or not row["reviewer_notes"]:
            return jsonify(error="Reviewer Notes not found"), 404
        read_at = row["reviewer_notes_read_at"] or now()
        if not row["reviewer_notes_read_at"]:
            db.execute(
                """
                UPDATE appliances SET reviewer_notes_read_at=?
                WHERE appliance_id=? AND household_id=?
                """,
                (read_at, appliance_id, household_id),
            )
            audit(
                db,
                request.current_user["user_id"],
                "reviewer_notes_read",
                "appliance",
                appliance_id,
            )
    return jsonify(ok=True, reviewer_notes_read_at=read_at)


HOUSEHOLD_APPLIANCE_SELECT = """
SELECT ha.inventory_id, ha.source_appliance_id, ha.appliance_name,
       ha.brand, ha.model, ha.power_rating_watts, ha.quantity,
       ha.avg_daily_usage_hours, ha.source_of_info,
       ha.deleted_at, ha.created_at, ha.updated_at,
       c.category_id, c.category_name,
       ROUND(ha.power_rating_watts * ha.quantity * ha.avg_daily_usage_hours / 1000.0, 3)
         AS estimated_daily_kwh
FROM household_appliances ha
JOIN appliance_categories c ON c.category_id=ha.category_id
"""


@app.get("/api/my-appliances")
@require_auth("household")
def list_household_appliances():
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        rows = db.execute(
            HOUSEHOLD_APPLIANCE_SELECT
            + " WHERE ha.household_id=? AND ha.deleted_at IS NULL ORDER BY ha.updated_at DESC",
            (household_id,),
        ).fetchall()
    return jsonify(appliances=[dict(row) for row in rows])


@app.get("/api/my-appliances/recently-deleted")
@require_auth("household")
def list_recently_deleted_household_appliances():
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        rows = db.execute(
            HOUSEHOLD_APPLIANCE_SELECT
            + " WHERE ha.household_id=? AND ha.deleted_at IS NOT NULL ORDER BY ha.deleted_at DESC",
            (household_id,),
        ).fetchall()
    return jsonify(appliances=[dict(row) for row in rows])


@app.get("/api/crowdsource/appliances")
@require_auth("household", "admin", "guimelco", "researcher")
def crowdsourced_appliance_catalog():
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    filters = ["a.verification_status = 'approved'"]
    params: list[Any] = []
    if search:
        filters.append(
            "(a.appliance_name LIKE ? OR COALESCE(a.brand,'') LIKE ? "
            "OR COALESCE(a.model,'') LIKE ?)"
        )
        term = f"%{search}%"
        params.extend((term, term, term))
    if category:
        filters.append("c.category_name = ?")
        params.append(category)
    where_clause = " AND ".join(filters)
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT MIN(a.appliance_id) AS catalog_id,
                   a.appliance_name, a.brand, a.model, a.category_id,
                   c.category_name, a.power_rating_watts,
                   ROUND(AVG(a.quantity), 1) AS community_avg_quantity,
                   ROUND(AVG(a.avg_daily_usage_hours), 1) AS community_avg_hours,
                   COUNT(DISTINCT a.household_id) AS contributor_count,
                   GROUP_CONCAT(DISTINCT u.full_name) AS contributors,
                   CASE
                     WHEN SUM(CASE WHEN a.source_of_info='nameplate_label' THEN 1 ELSE 0 END) > 0
                       THEN 'nameplate_label'
                     WHEN SUM(CASE WHEN a.source_of_info='user_manual' THEN 1 ELSE 0 END) > 0
                       THEN 'user_manual'
                     ELSE MIN(a.source_of_info)
                   END AS strongest_source,
                   MAX(a.reviewed_at) AS last_verified_at
            FROM appliances a
            JOIN appliance_categories c ON c.category_id = a.category_id
            JOIN households h ON h.household_id = a.household_id
            JOIN users u ON u.user_id = h.user_id
            WHERE {where_clause}
            GROUP BY LOWER(TRIM(a.appliance_name)),
                     LOWER(COALESCE(a.brand,'')),
                     LOWER(COALESCE(a.model,'')),
                     a.category_id, a.power_rating_watts
            ORDER BY contributor_count DESC, a.appliance_name
            """,
            tuple(params),
        ).fetchall()
    return jsonify(appliances=[dict(row) for row in rows])


@app.post("/api/my-appliances/from-submission/<int:catalog_id>")
@app.post("/api/appliances/from-crowdsource/<int:catalog_id>")
@require_auth("household")
def create_household_appliance_from_submission(catalog_id: int):
    data = json_body()
    try:
        quantity = int(number_value(data, "quantity", minimum=1, maximum=50))
        avg_hours = number_value(
            data, "avg_daily_usage_hours", minimum=0, maximum=24
        )
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    with get_db() as db:
        source = db.execute(
            """
            SELECT appliance_id, category_id, appliance_name, brand, model,
                   power_rating_watts, source_of_info
            FROM appliances
            WHERE appliance_id=? AND verification_status='approved'
            """,
            (catalog_id,),
        ).fetchone()
        if not source:
            return jsonify(error="Approved crowdsourced appliance not found"), 404
        household_id = household_id_for(request.current_user["user_id"], db)
        existing = db.execute(
            """
            SELECT inventory_id, deleted_at FROM household_appliances
            WHERE household_id=? AND source_appliance_id=?
            """,
            (household_id, source["appliance_id"]),
        ).fetchone()
        if existing:
            if existing["deleted_at"]:
                return jsonify(error="This appliance is in Recently Deleted. Restore it there."), 409
            return jsonify(error="This appliance is already in My Appliances"), 409
        cursor = db.execute(
            """
            INSERT INTO household_appliances
              (household_id, source_appliance_id, category_id,
               appliance_name, brand, model,
               power_rating_watts, quantity, avg_daily_usage_hours,
               source_of_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                household_id,
                source["appliance_id"],
                source["category_id"],
                source["appliance_name"],
                source["brand"],
                source["model"],
                source["power_rating_watts"],
                quantity,
                avg_hours,
                source["source_of_info"],
            ),
        )
        inventory_id = int(cursor.lastrowid)
        audit(
            db,
            request.current_user["user_id"],
            "added_from_approved_submission",
            "household_appliance",
            inventory_id,
            {
                "catalog_id": source["appliance_id"],
                "appliance_name": source["appliance_name"],
                "quantity": quantity,
                "avg_daily_usage_hours": avg_hours,
            },
        )
        row = db.execute(
            HOUSEHOLD_APPLIANCE_SELECT + " WHERE ha.inventory_id=?",
            (inventory_id,),
        ).fetchone()
    return jsonify(appliance=dict(row)), 201


@app.patch("/api/my-appliances/<int:inventory_id>")
@require_auth("household")
def update_household_appliance(inventory_id: int):
    data = json_body()
    try:
        quantity = int(number_value(data, "quantity", minimum=1, maximum=50))
        avg_hours = number_value(
            data, "avg_daily_usage_hours", minimum=0, maximum=24
        )
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        existing = db.execute(
            """
            SELECT appliance_name FROM household_appliances
            WHERE inventory_id=? AND household_id=? AND deleted_at IS NULL
            """,
            (inventory_id, household_id),
        ).fetchone()
        if not existing:
            return jsonify(error="Household appliance not found"), 404
        db.execute(
            """
            UPDATE household_appliances
            SET quantity=?, avg_daily_usage_hours=?, updated_at=?
            WHERE inventory_id=? AND household_id=?
            """,
            (quantity, avg_hours, now(), inventory_id, household_id),
        )
        audit(
            db,
            request.current_user["user_id"],
            "updated_usage",
            "household_appliance",
            inventory_id,
            {"quantity": quantity, "avg_daily_usage_hours": avg_hours},
        )
        row = db.execute(
            HOUSEHOLD_APPLIANCE_SELECT + " WHERE ha.inventory_id=?",
            (inventory_id,),
        ).fetchone()
    return jsonify(appliance=dict(row))


@app.delete("/api/my-appliances/<int:inventory_id>")
@require_auth("household")
def delete_household_appliance(inventory_id: int):
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        row = db.execute(
            """
            SELECT appliance_name FROM household_appliances
            WHERE inventory_id=? AND household_id=? AND deleted_at IS NULL
            """,
            (inventory_id, household_id),
        ).fetchone()
        if not row:
            return jsonify(error="Household appliance not found"), 404
        db.execute(
            """
            UPDATE household_appliances
            SET deleted_at=?, updated_at=?
            WHERE inventory_id=? AND household_id=? AND deleted_at IS NULL
            """,
            (now(), now(), inventory_id, household_id),
        )
        audit(
            db,
            request.current_user["user_id"],
            "moved_to_recently_deleted",
            "household_appliance",
            inventory_id,
            {"appliance_name": row["appliance_name"]},
        )
    return jsonify(ok=True)


@app.post("/api/my-appliances/<int:inventory_id>/restore")
@require_auth("household")
def restore_household_appliance(inventory_id: int):
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        row = db.execute(
            """
            SELECT ha.appliance_name, ha.source_appliance_id, a.verification_status AS source_status
            FROM household_appliances ha LEFT JOIN appliances a ON a.appliance_id=ha.source_appliance_id
            WHERE ha.inventory_id=? AND ha.household_id=? AND ha.deleted_at IS NOT NULL
            """,
            (inventory_id, household_id),
        ).fetchone()
        if not row:
            return jsonify(error="Recently deleted appliance not found"), 404
        if row["source_appliance_id"] is not None and row["source_status"] != "approved":
            return jsonify(error="An admin removed this appliance from the approved list, so it can't be restored"), 409
        db.execute(
            """
            UPDATE household_appliances
            SET deleted_at=NULL, updated_at=?
            WHERE inventory_id=? AND household_id=?
            """,
            (now(), inventory_id, household_id),
        )
        audit(
            db,
            request.current_user["user_id"],
            "restored",
            "household_appliance",
            inventory_id,
            {"appliance_name": row["appliance_name"]},
        )
        restored = db.execute(
            HOUSEHOLD_APPLIANCE_SELECT + " WHERE ha.inventory_id=?",
            (inventory_id,),
        ).fetchone()
    return jsonify(appliance=dict(restored))


@app.delete("/api/my-appliances/permanent")
@require_auth("household")
def permanently_delete_household_appliances():
    try:
        inventory_ids = id_list(json_body(), "inventory_ids")
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    placeholders = ",".join("?" for _ in inventory_ids)
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        rows = db.execute(
            f"""
            SELECT inventory_id, appliance_name
            FROM household_appliances
            WHERE household_id=? AND deleted_at IS NOT NULL
              AND inventory_id IN ({placeholders})
            """,
            (household_id, *inventory_ids),
        ).fetchall()
        if not rows:
            return jsonify(error="No recently deleted appliances were selected"), 404
        eligible_ids = [int(row["inventory_id"]) for row in rows]
        eligible_placeholders = ",".join("?" for _ in eligible_ids)
        db.execute(
            f"""
            DELETE FROM household_appliances
            WHERE household_id=? AND deleted_at IS NOT NULL
              AND inventory_id IN ({eligible_placeholders})
            """,
            (household_id, *eligible_ids),
        )
        for row in rows:
            audit(
                db,
                request.current_user["user_id"],
                "permanently_deleted",
                "household_appliance",
                int(row["inventory_id"]),
                {"appliance_name": row["appliance_name"]},
            )
    return jsonify(ok=True, deleted_count=len(eligible_ids))


def appliance_fields(data: dict[str, Any]) -> dict[str, Any]:
    category_id = int(number_value(data, "category_id", minimum=1, maximum=9999))
    source = text_value(data, "source_of_info", True)
    if source not in ("nameplate_label", "user_manual", "manual_estimate", "retailer_specs"):
        raise ValueError("Select a valid source of information")
    return {
        "appliance_name": text_value(data, "appliance_name", True),
        "brand": text_value(data, "brand"),
        "model": text_value(data, "model"),
        "category_id": category_id,
        "power_rating_watts": number_value(data, "power_rating_watts", minimum=1, maximum=50000),
        "quantity": int(number_value(data, "quantity", minimum=1, maximum=50)),
        "avg_daily_usage_hours": number_value(data, "avg_daily_usage_hours", minimum=0, maximum=24),
        "source_of_info": source,
    }


@app.post("/api/appliances")
@require_auth("household")
def create_appliance():
    try:
        fields = appliance_fields(json_body())
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        category = db.execute(
            "SELECT 1 FROM appliance_categories WHERE category_id = ?",
            (fields["category_id"],),
        ).fetchone()
        if not category:
            return jsonify(error="Selected category does not exist"), 400
        cursor = db.execute(
            """
            INSERT INTO appliances
              (household_id, appliance_name, brand, model, category_id,
               power_rating_watts, quantity, avg_daily_usage_hours, source_of_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (household_id, *fields.values()),
        )
        appliance_id = int(cursor.lastrowid)
        audit(db, request.current_user["user_id"], "created", "appliance", appliance_id, fields)
        row = db.execute(
            APPLIANCE_SELECT + " WHERE a.appliance_id = ?", (appliance_id,)
        ).fetchone()
    return jsonify(appliance=dict(row)), 201


@app.patch("/api/appliances/<int:appliance_id>")
@require_auth("household")
def update_appliance(appliance_id: int):
    data = json_body()
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        existing = db.execute(
            """
            SELECT appliance_name, copied_from_appliance_id, verification_status
            FROM appliances WHERE appliance_id=? AND household_id=?
            """,
            (appliance_id, household_id),
        ).fetchone()
        if not existing:
            return jsonify(error="Appliance not found"), 404
        if existing["copied_from_appliance_id"] is not None:
            try:
                quantity = int(
                    number_value(data, "quantity", minimum=1, maximum=50)
                )
                avg_hours = number_value(
                    data, "avg_daily_usage_hours", minimum=0, maximum=24
                )
            except (ValueError, TypeError) as error:
                return jsonify(error=str(error)), 400
            db.execute(
                """
                UPDATE appliances
                SET quantity=?, avg_daily_usage_hours=?,
                    verification_status='approved', reviewer_notes=?,
                    reviewer_notes_read_at=?,
                    updated_at=?
                WHERE appliance_id=? AND household_id=?
                """,
                (
                    quantity,
                    avg_hours,
                    CATALOG_APPROVAL_NOTE,
                    now(),
                    now(),
                    appliance_id,
                    household_id,
                ),
            )
            audit(
                db,
                request.current_user["user_id"],
                "updated_household_usage",
                "appliance",
                appliance_id,
                {
                    "copied_from_appliance_id": existing[
                        "copied_from_appliance_id"
                    ],
                    "quantity": quantity,
                    "avg_daily_usage_hours": avg_hours,
                },
            )
            row = db.execute(
                APPLIANCE_SELECT + " WHERE a.appliance_id = ?", (appliance_id,)
            ).fetchone()
            return jsonify(appliance=dict(row))
        if existing["verification_status"] == "approved":
            return jsonify(error="Approved submissions can't be changed. Send feedback to an admin if something is wrong."), 409
        try:
            fields = appliance_fields(data)
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
        db.execute(
            """
            UPDATE appliances
            SET appliance_name=?, brand=?, model=?, category_id=?,
                power_rating_watts=?, quantity=?, avg_daily_usage_hours=?,
                source_of_info=?, verification_status='pending',
                reviewer_notes=NULL, reviewer_notes_read_at=NULL,
                reviewed_by=NULL, reviewed_at=NULL, updated_at=?
            WHERE appliance_id=? AND household_id=?
            """,
            (*fields.values(), now(), appliance_id, household_id),
        )
        audit(db, request.current_user["user_id"], "updated", "appliance", appliance_id, fields)
        row = db.execute(
            APPLIANCE_SELECT + " WHERE a.appliance_id = ?", (appliance_id,)
        ).fetchone()
    return jsonify(appliance=dict(row))


@app.delete("/api/appliances/<int:appliance_id>")
@require_auth("household")
def delete_appliance(appliance_id: int):
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        row = db.execute(
            """
            SELECT appliance_name, verification_status
            FROM appliances
            WHERE appliance_id=? AND household_id=?
            """,
            (appliance_id, household_id),
        ).fetchone()
        if not row:
            return jsonify(error="Appliance not found"), 404
        if row["verification_status"] == "approved":
            return jsonify(
                error="Approved appliance submissions cannot be deleted"
            ), 409
        db.execute(
            "DELETE FROM appliances WHERE appliance_id=? AND household_id=?",
            (appliance_id, household_id),
        )
        audit(
            db,
            request.current_user["user_id"],
            "deleted",
            "appliance",
            appliance_id,
            {
                "appliance_name": row["appliance_name"],
                "verification_status": row["verification_status"],
            },
        )
    return jsonify(ok=True)


CONSUMPTION_SELECT = """
SELECT consumption_id, billing_month, consumption_kwh, bill_amount_php,
       meter_reading, source_of_info, verification_status, reviewer_notes,
       reviewer_notes_read_at,
       CASE
         WHEN reviewer_notes IS NOT NULL
          AND TRIM(reviewer_notes) <> ''
          AND reviewer_notes_read_at IS NULL THEN 1 ELSE 0
       END AS reviewer_notes_unread,
       deleted_at, created_at, updated_at,
       CASE WHEN bill_image_filename IS NOT NULL THEN 1 ELSE 0 END AS has_bill_image
FROM monthly_consumption
"""


@app.get("/api/consumption")
@require_auth("household")
def list_consumption():
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        rows = db.execute(
            CONSUMPTION_SELECT
            + " WHERE household_id=? AND deleted_at IS NULL ORDER BY billing_month DESC",
            (household_id,),
        ).fetchall()
    return jsonify(records=[dict(row) for row in rows])


@app.get("/api/consumption/recently-deleted")
@require_auth("household")
def list_recently_deleted_consumption():
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        rows = db.execute(
            CONSUMPTION_SELECT
            + " WHERE household_id=? AND deleted_at IS NOT NULL ORDER BY deleted_at DESC",
            (household_id,),
        ).fetchall()
    return jsonify(records=[dict(row) for row in rows])


@app.post("/api/consumption/<int:consumption_id>/reviewer-notes/read")
@require_auth("household")
def mark_consumption_reviewer_notes_read(consumption_id: int):
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        row = db.execute(
            """
            SELECT reviewer_notes, reviewer_notes_read_at
            FROM monthly_consumption
            WHERE consumption_id=? AND household_id=? AND deleted_at IS NULL
            """,
            (consumption_id, household_id),
        ).fetchone()
        if not row or not row["reviewer_notes"]:
            return jsonify(error="Reviewer Notes not found"), 404
        read_at = row["reviewer_notes_read_at"] or now()
        if not row["reviewer_notes_read_at"]:
            db.execute(
                """
                UPDATE monthly_consumption SET reviewer_notes_read_at=?
                WHERE consumption_id=? AND household_id=? AND deleted_at IS NULL
                """,
                (read_at, consumption_id, household_id),
            )
            audit(
                db,
                request.current_user["user_id"],
                "reviewer_notes_read",
                "monthly_consumption",
                consumption_id,
            )
    return jsonify(ok=True, reviewer_notes_read_at=read_at)


@app.get("/api/consumption/<int:consumption_id>/bill-image")
@require_auth("household", "admin", "guimelco", "researcher")
def get_consumption_bill_image(consumption_id: int):
    with get_db() as db:
        row = db.execute(
            """
            SELECT household_id, bill_image_filename, bill_image_original_name,
                   bill_image_mime
            FROM monthly_consumption WHERE consumption_id=?
            """,
            (consumption_id,),
        ).fetchone()
        if not row or not row["bill_image_filename"]:
            return jsonify(error="Bill picture not found"), 404
        if request.current_user["role"] == "household":
            household_id = household_id_for(request.current_user["user_id"], db)
            if int(row["household_id"]) != household_id:
                return jsonify(error="Bill picture not found"), 404
        filename = row["bill_image_filename"]
        original_name = row["bill_image_original_name"] or filename
        mime_type = row["bill_image_mime"] or "application/octet-stream"
    return send_from_directory(
        BILL_IMAGE_DIR,
        filename,
        mimetype=mime_type,
        as_attachment=False,
        download_name=original_name,
        max_age=0,
    )


def consumption_fields(data: dict[str, Any]) -> dict[str, Any]:
    billing_month = text_value(data, "billing_month", True)
    try:
        datetime.strptime(billing_month, "%Y-%m")
    except ValueError:
        raise ValueError("Billing month must use YYYY-MM format")
    if billing_month > datetime.now().strftime("%Y-%m"):
        raise ValueError("Billing month cannot be in the future")
    source = text_value(data, "source_of_info", True)
    if source not in ("electric_bill", "meter_reading", "utility_portal", "manual_entry"):
        raise ValueError("Select a valid source of information")
    return {
        "billing_month": billing_month,
        "consumption_kwh": number_value(data, "consumption_kwh", minimum=0.01, maximum=100000),
        "bill_amount_php": number_value(data, "bill_amount_php", minimum=0, maximum=10000000, required=False),
        "meter_reading": number_value(data, "meter_reading", minimum=0, maximum=100000000, required=False),
        "source_of_info": source,
    }


@app.post("/api/consumption")
@require_auth("household")
def create_consumption():
    try:
        fields = consumption_fields(form_or_json_body())
        image = bill_image_upload(required=True)
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        deleted = db.execute(
            """
            SELECT 1 FROM monthly_consumption
            WHERE household_id=? AND billing_month=? AND deleted_at IS NOT NULL
            """,
            (household_id, fields["billing_month"]),
        ).fetchone()
        if deleted:
            return jsonify(
                error="That billing month is in Recently Deleted. Restore it there."
            ), 409
        existing = db.execute(
            """
            SELECT 1 FROM monthly_consumption
            WHERE household_id=? AND billing_month=?
            """,
            (household_id, fields["billing_month"]),
        ).fetchone()
        if existing:
            return jsonify(error="A consumption record for that billing month already exists"), 409
        save_bill_image(image)
        try:
            cursor = db.execute(
                """
                INSERT INTO monthly_consumption
                  (household_id, billing_month, consumption_kwh, bill_amount_php,
                   meter_reading, source_of_info, bill_image_filename,
                   bill_image_original_name, bill_image_mime, bill_image_size_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    household_id,
                    *fields.values(),
                    image["filename"],
                    image["original_name"],
                    image["mime_type"],
                    image["size_bytes"],
                ),
            )
        except Exception:
            delete_bill_image(image["filename"])
            raise
        consumption_id = int(cursor.lastrowid)
        audit(
            db,
            request.current_user["user_id"],
            "created",
            "monthly_consumption",
            consumption_id,
            {**fields, "bill_image_attached": True},
        )
        row = db.execute(
            CONSUMPTION_SELECT + " WHERE consumption_id=?", (consumption_id,)
        ).fetchone()
    return jsonify(record=dict(row)), 201


@app.patch("/api/consumption/<int:consumption_id>")
@require_auth("household")
def update_consumption(consumption_id: int):
    try:
        fields = consumption_fields(form_or_json_body())
        image = bill_image_upload(required=True)
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    old_filename = None
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        existing = db.execute(
            """
            SELECT bill_image_filename FROM monthly_consumption
            WHERE consumption_id=? AND household_id=? AND deleted_at IS NULL
            """,
            (consumption_id, household_id),
        ).fetchone()
        if not existing:
            return jsonify(error="Consumption record not found"), 404
        old_filename = existing["bill_image_filename"]
        save_bill_image(image)
        try:
            db.execute(
                """
                UPDATE monthly_consumption
                SET billing_month=?, consumption_kwh=?, bill_amount_php=?, meter_reading=?,
                    source_of_info=?, bill_image_filename=?, bill_image_original_name=?,
                    bill_image_mime=?, bill_image_size_bytes=?,
                    verification_status='pending', reviewer_notes=NULL,
                    reviewer_notes_read_at=NULL,
                    reviewed_by=NULL, reviewed_at=NULL, updated_at=?
                WHERE consumption_id=? AND household_id=?
                """,
                (
                    *fields.values(),
                    image["filename"],
                    image["original_name"],
                    image["mime_type"],
                    image["size_bytes"],
                    now(),
                    consumption_id,
                    household_id,
                ),
            )
        except Exception:
            delete_bill_image(image["filename"])
            raise
        audit(
            db,
            request.current_user["user_id"],
            "updated",
            "monthly_consumption",
            consumption_id,
            {**fields, "bill_image_replaced": True},
        )
        row = db.execute(
            CONSUMPTION_SELECT + " WHERE consumption_id=?", (consumption_id,)
        ).fetchone()
    delete_bill_image(old_filename)
    return jsonify(record=dict(row))


@app.delete("/api/consumption/<int:consumption_id>")
@require_auth("household")
def delete_consumption(consumption_id: int):
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        row = db.execute(
            """
            SELECT billing_month, verification_status FROM monthly_consumption
            WHERE consumption_id=? AND household_id=? AND deleted_at IS NULL
            """,
            (consumption_id, household_id),
        ).fetchone()
        if not row:
            return jsonify(error="Consumption record not found"), 404
        if row["verification_status"] == "approved":
            return jsonify(error="Approved bill submissions cannot be deleted"), 409
        db.execute(
            """
            UPDATE monthly_consumption SET deleted_at=?, updated_at=?
            WHERE consumption_id=? AND household_id=? AND deleted_at IS NULL
            """,
            (now(), now(), consumption_id, household_id),
        )
        audit(
            db,
            request.current_user["user_id"],
            "moved_to_recently_deleted",
            "monthly_consumption",
            consumption_id,
            {"billing_month": row["billing_month"]},
        )
    return jsonify(ok=True)


@app.post("/api/consumption/<int:consumption_id>/restore")
@require_auth("household")
def restore_consumption(consumption_id: int):
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        row = db.execute(
            """
            SELECT billing_month FROM monthly_consumption
            WHERE consumption_id=? AND household_id=? AND deleted_at IS NOT NULL
            """,
            (consumption_id, household_id),
        ).fetchone()
        if not row:
            return jsonify(error="Recently deleted consumption record not found"), 404
        db.execute(
            """
            UPDATE monthly_consumption SET deleted_at=NULL, updated_at=?
            WHERE consumption_id=? AND household_id=?
            """,
            (now(), consumption_id, household_id),
        )
        audit(
            db,
            request.current_user["user_id"],
            "restored",
            "monthly_consumption",
            consumption_id,
            {"billing_month": row["billing_month"]},
        )
        restored = db.execute(
            CONSUMPTION_SELECT + " WHERE consumption_id=?", (consumption_id,)
        ).fetchone()
    return jsonify(record=dict(restored))


@app.delete("/api/consumption/permanent")
@require_auth("household")
def permanently_delete_consumption():
    try:
        consumption_ids = id_list(json_body(), "consumption_ids")
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    placeholders = ",".join("?" for _ in consumption_ids)
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        rows = db.execute(
            f"""
            SELECT consumption_id, billing_month, bill_image_filename, verification_status
            FROM monthly_consumption
            WHERE household_id=? AND deleted_at IS NOT NULL
              AND consumption_id IN ({placeholders})
            """,
            (household_id, *consumption_ids),
        ).fetchall()
        if not rows:
            return jsonify(error="No recently deleted monthly records were selected"), 404
        if any(row["verification_status"] == "approved" for row in rows):
            return jsonify(error="Approved bill submissions cannot be deleted; restore them instead"), 409
        eligible_ids = [int(row["consumption_id"]) for row in rows]
        eligible_placeholders = ",".join("?" for _ in eligible_ids)
        db.execute(
            f"""
            DELETE FROM monthly_consumption
            WHERE household_id=? AND deleted_at IS NOT NULL
              AND consumption_id IN ({eligible_placeholders})
            """,
            (household_id, *eligible_ids),
        )
        for row in rows:
            audit(
                db,
                request.current_user["user_id"],
                "permanently_deleted",
                "monthly_consumption",
                int(row["consumption_id"]),
                {"billing_month": row["billing_month"]},
            )
    for row in rows:
        delete_bill_image(row["bill_image_filename"])
    return jsonify(ok=True, deleted_count=len(eligible_ids))


def admin_submissions(db: sqlite3.Connection, status: str | None) -> list[dict[str, Any]]:
    status_clause = "" if not status or status == "all" else " AND {alias}.verification_status = ?"
    params: tuple[Any, ...] = () if not status or status == "all" else (status,)
    appliances = db.execute(
        f"""
        SELECT 'appliance' AS submission_type, a.appliance_id AS submission_id,
               a.appliance_name AS title,
               printf('%.0f W · Qty %d · %.1f hr/day', a.power_rating_watts, a.quantity, a.avg_daily_usage_hours) AS details,
               a.source_of_info, a.verification_status, a.reviewer_notes,
               a.created_at, a.updated_at, u.full_name AS contributor,
               h.barangay, h.municipality, c.category_name,
               a.category_id, a.appliance_name, a.brand, a.model, a.power_rating_watts,
               CASE WHEN a.removed_at IS NOT NULL THEN 1 ELSE 0 END AS removed
        FROM appliances a
        JOIN households h ON h.household_id=a.household_id
        JOIN users u ON u.user_id=h.user_id
        JOIN appliance_categories c ON c.category_id=a.category_id
        WHERE 1=1 {status_clause.format(alias='a')}
        """,
        params,
    ).fetchall()
    consumption = db.execute(
        f"""
        SELECT 'consumption' AS submission_type, m.consumption_id AS submission_id,
               m.billing_month AS title,
               printf('%.2f kWh · ₱%.2f', m.consumption_kwh, COALESCE(m.bill_amount_php,0)) AS details,
               m.source_of_info, m.verification_status, m.reviewer_notes,
               m.created_at, m.updated_at, u.full_name AS contributor,
               h.barangay, h.municipality, 'Monthly Consumption' AS category_name, 0 AS removed,
               CASE WHEN m.bill_image_filename IS NOT NULL THEN 1 ELSE 0 END AS has_bill_image
        FROM monthly_consumption m
        JOIN households h ON h.household_id=m.household_id
        JOIN users u ON u.user_id=h.user_id
        WHERE m.deleted_at IS NULL {status_clause.format(alias='m')}
        """,
        params,
    ).fetchall()
    combined = [dict(row) for row in (*appliances, *consumption)]
    combined.sort(key=lambda item: item["updated_at"], reverse=True)
    return combined


@app.get("/api/admin/stats")
@require_auth("admin", "guimelco", "researcher")
def admin_stats():
    with get_db() as db:
        role = request.current_user["role"]
        counts = {"pending": 0, "approved": 0, "rejected": 0}
        for table in ("appliances", "monthly_consumption"):
            active_clause = " WHERE deleted_at IS NULL" if table == "monthly_consumption" else ""
            for row in db.execute(
                f"SELECT verification_status, COUNT(*) AS count FROM {table}{active_clause} GROUP BY verification_status"
            ):
                counts[row["verification_status"]] += int(row["count"])
        households = db.execute("SELECT COUNT(*) AS count FROM households").fetchone()["count"]
        total = sum(counts.values())
        approved = counts["approved"]
        recent = db.execute(
            """
            SELECT a.audit_id, a.action, a.entity_type, a.entity_id, a.details,
                   a.created_at, COALESCE(u.full_name, 'System') AS actor
            FROM audit_logs a LEFT JOIN users u ON u.user_id=a.actor_user_id
            ORDER BY a.created_at DESC LIMIT 8
            """
        ).fetchall()
    return jsonify(
        stats={
            **counts,
            "total_submissions": total,
            "households": int(households),
            "data_readiness_pct": round((approved / total) * 100) if total else 0,
            "role": role,
        },
        audit=[dict(row) for row in recent],
    )


@app.get("/api/admin/submissions")
@require_auth("admin", "guimelco", "researcher")
def list_admin_submissions():
    status = request.args.get("status", "pending").lower()
    if status not in ("all", "pending", "approved", "rejected"):
        return jsonify(error="Invalid submission status"), 400
    with get_db() as db:
        submissions = admin_submissions(db, status)
    return jsonify(submissions=submissions)


@app.patch("/api/admin/submissions/<submission_type>/<int:submission_id>")
@require_auth("admin")
def review_submission(submission_type: str, submission_id: int):
    data = json_body()
    status = text_value(data, "status", True)
    notes = text_value(data, "reviewer_notes")
    if status not in ("approved", "rejected"):
        return jsonify(error="Status must be approved or rejected"), 400
    if status == "rejected" and not notes:
        return jsonify(error="A rejection reason is required"), 400

    mapping = {
        "appliance": ("appliances", "appliance_id", "household_id"),
        "consumption": ("monthly_consumption", "consumption_id", "household_id"),
    }
    if submission_type not in mapping:
        return jsonify(error="Invalid submission type"), 400
    table, id_column, household_column = mapping[submission_type]
    active_clause = " AND s.deleted_at IS NULL" if submission_type == "consumption" else ""
    evidence_column = ", s.bill_image_filename" if submission_type == "consumption" else ", s.removed_at"
    notes_read_reset = ", reviewer_notes_read_at=NULL"
    with get_db() as db:
        row = db.execute(
            f"""
            SELECT h.user_id, s.verification_status{evidence_column}
            FROM {table} s JOIN households h ON h.household_id=s.{household_column}
            WHERE s.{id_column}=?{active_clause}
            """,
            (submission_id,),
        ).fetchone()
        if not row:
            return jsonify(error="Submission not found"), 404
        if row["verification_status"] == "approved":
            action = "Edit or Remove" if submission_type == "appliance" else "Delete"
            return jsonify(error=f"Approved submissions are final. Use {action} instead."), 409
        if submission_type == "appliance" and row["removed_at"]:
            return jsonify(error="This appliance was removed after approval and can't be reviewed again"), 409
        if (
            submission_type == "consumption"
            and status == "approved"
            and not row["bill_image_filename"]
        ):
            return jsonify(error="A bill picture is required before approval"), 400
        db.execute(
            f"""
            UPDATE {table}
            SET verification_status=?, reviewer_notes=?, reviewed_by=?, reviewed_at=?, updated_at=?{notes_read_reset}
            WHERE {id_column}=?{active_clause.replace('s.', '')}
            """,
            (
                status,
                notes,
                request.current_user["user_id"],
                now(),
                now(),
                submission_id,
            ),
        )
        db.execute(
            """
            INSERT INTO notifications(user_id, title, message, type, entity_type, entity_id)
            VALUES (?, ?, ?, 'submission_update', ?, ?)
            """,
            (
                row["user_id"],
                "Submission reviewed",
                f"Your {submission_type} submission was {status}.",
                submission_type,
                submission_id,
            ),
        )
        audit(
            db,
            request.current_user["user_id"],
            status,
            submission_type,
            submission_id,
            {"reviewer_notes": notes},
        )
    return jsonify(ok=True, status=status)


APPLIANCE_SPEC_FIELDS = ("appliance_name", "brand", "model", "category_id", "power_rating_watts", "source_of_info")
SOURCE_LABELS = {
    "nameplate_label": "Nameplate Label",
    "user_manual": "User Manual",
    "manual_estimate": "Manual Estimate",
    "retailer_specs": "Retailer Specs",
}


def notify_users(db: sqlite3.Connection, user_ids: set[int], title: str, message: str,
                 entity_type: str, entity_id: int) -> None:
    for user_id in sorted(user_ids):
        db.execute(
            """
            INSERT INTO notifications(user_id, title, message, type, entity_type, entity_id)
            VALUES (?, ?, ?, 'submission_update', ?, ?)
            """,
            (user_id, title, message, entity_type, entity_id),
        )


def appliance_users(db: sqlite3.Connection, appliance_id: int) -> set[int]:
    """The submitter plus every household that has this appliance in My Appliances."""
    rows = db.execute(
        """
        SELECT h.user_id FROM appliances a JOIN households h ON h.household_id=a.household_id
        WHERE a.appliance_id=? OR a.copied_from_appliance_id=?
        UNION
        SELECT h.user_id FROM household_appliances ha JOIN households h ON h.household_id=ha.household_id
        WHERE ha.source_appliance_id=? AND ha.deleted_at IS NULL
        """,
        (appliance_id, appliance_id, appliance_id),
    ).fetchall()
    return {row["user_id"] for row in rows}


def withdraw_inventory_copies(db: sqlite3.Connection, appliance_id: int) -> set[int]:
    """Move every active My Appliances copy of an appliance to Recently Deleted; returns the owners."""
    owners = {row["user_id"] for row in db.execute(
        """
        SELECT h.user_id FROM household_appliances ha JOIN households h ON h.household_id=ha.household_id
        WHERE ha.source_appliance_id=? AND ha.deleted_at IS NULL
        """,
        (appliance_id,),
    )}
    stamp = now()
    db.execute(
        "UPDATE household_appliances SET deleted_at=?, updated_at=? WHERE source_appliance_id=? AND deleted_at IS NULL",
        (stamp, stamp, appliance_id),
    )
    return owners


def removal_message(name: str) -> str:
    # The reason is the reviewer note, shown under the message as the administrator's note.
    return (f"An admin removed {name} from the approved appliances, so it was taken out of My Appliances. "
            "You can add a replacement from the approved list.")


def drop_repeated_reasons(db: sqlite3.Connection) -> None:
    """Older removal and bill-deletion messages repeated the reason that the administrator's note shows."""
    rows = db.execute(
        "SELECT notification_id, message FROM notifications "
        "WHERE title IN ('Appliance removed', 'Bill deleted by admin') AND message LIKE '% Reason: %'"
    ).fetchall()
    for row in rows:
        message = re.sub(r" Reason: .*?(?= You can add a replacement|$)", "", row["message"], flags=re.S)
        db.execute("UPDATE notifications SET message=? WHERE notification_id=?", (message, row["notification_id"]))


def remove_unapproved_inventory(db: sqlite3.Connection) -> int:
    """Withdraw My Appliances copies whose source is no longer approved (left over from older re-reviews)."""
    sources = db.execute(
        """
        SELECT DISTINCT a.appliance_id, a.appliance_name
        FROM appliances a JOIN household_appliances ha ON ha.source_appliance_id=a.appliance_id
        WHERE ha.deleted_at IS NULL AND a.verification_status<>'approved'
        """
    ).fetchall()
    withdrawn = 0
    for source in sources:
        owners = withdraw_inventory_copies(db, source["appliance_id"])
        withdrawn += len(owners)
        notify_users(db, owners, "Appliance removed",
                     removal_message(source["appliance_name"]),
                     "appliance", source["appliance_id"])
    return withdrawn


def approved_appliance(db: sqlite3.Connection, appliance_id: int):
    """(row, error response) for an appliance an admin may still edit or remove."""
    row = db.execute("SELECT * FROM appliances WHERE appliance_id=?", (appliance_id,)).fetchone()
    if not row:
        return None, (jsonify(error="Appliance not found"), 404)
    if row["verification_status"] != "approved" or row["removed_at"]:
        return None, (jsonify(error="Only approved appliances can be edited or removed"), 409)
    return row, None


def spec_changes(old: sqlite3.Row, new: dict[str, Any], categories: dict[int, str]) -> list[str]:
    def show(key: str, value: Any) -> str:
        if key == "power_rating_watts":
            return f"{float(value):g} W"
        if key == "category_id":
            return categories.get(int(value), str(value))
        if key == "source_of_info":
            return SOURCE_LABELS.get(value, value)
        return value or "none"
    labels = {"appliance_name": "name", "brand": "brand", "model": "model", "category_id": "category",
              "power_rating_watts": "power rating", "source_of_info": "source"}
    return [f"{labels[key]} {show(key, old[key])} \u2192 {show(key, new[key])}"
            for key in APPLIANCE_SPEC_FIELDS if old[key] != new[key]]


@app.patch("/api/admin/appliances/<int:appliance_id>")
@require_auth("admin")
def edit_approved_appliance(appliance_id: int):
    data = json_body()
    reason = text_value(data, "reason")
    if not reason:
        return jsonify(error="Explain the correction so households know why it changed"), 400
    with get_db() as db:
        row, error = approved_appliance(db, appliance_id)
        if error:
            return error
        merged = {key: data.get(key, row[key]) for key in APPLIANCE_SPEC_FIELDS}
        merged.update(quantity=row["quantity"], avg_daily_usage_hours=row["avg_daily_usage_hours"])
        try:
            fields = appliance_fields(merged)
        except (ValueError, TypeError) as err:
            return jsonify(error=str(err)), 400
        categories = {r["category_id"]: r["category_name"] for r in db.execute("SELECT * FROM appliance_categories")}
        if fields["category_id"] not in categories:
            return jsonify(error="Selected category does not exist"), 400
        changes = spec_changes(row, fields, categories)
        if not changes:
            return jsonify(error="Nothing was changed"), 400
        spec = [fields[key] for key in APPLIANCE_SPEC_FIELDS]
        assignments = ", ".join(f"{key}=?" for key in APPLIANCE_SPEC_FIELDS)
        stamp = now()
        db.execute(f"UPDATE appliances SET {assignments}, updated_at=? WHERE appliance_id=? OR copied_from_appliance_id=?",
                   (*spec, stamp, appliance_id, appliance_id))
        # Copies keep each household's own quantity and hours; only the shared specs change.
        db.execute(f"UPDATE household_appliances SET {assignments}, updated_at=? WHERE source_appliance_id=?",
                   (*spec, stamp, appliance_id))
        users = appliance_users(db, appliance_id)
        notify_users(db, users, "Appliance updated",
                     f"An admin corrected {fields['appliance_name']}: {'; '.join(changes)}. Reason: {reason}",
                     "appliance", appliance_id)
        audit(db, request.current_user["user_id"], "edited_approved", "appliance", appliance_id,
              {"changes": changes, "reason": reason, "households_notified": len(users)})
    return jsonify(ok=True, changes=changes, households_notified=len(users))


@app.post("/api/admin/appliances/<int:appliance_id>/remove")
@require_auth("admin")
def remove_approved_appliance(appliance_id: int):
    reason = text_value(json_body(), "reason")
    if not reason:
        return jsonify(error="A reason is required to remove an approved appliance"), 400
    with get_db() as db:
        row, error = approved_appliance(db, appliance_id)
        if error:
            return error
        users = appliance_users(db, appliance_id)
        stamp = now()
        # Kept as a rejected record (not deleted) so the audit trail and notifications still resolve.
        db.execute(
            """
            UPDATE appliances
            SET verification_status='rejected', reviewer_notes=?, reviewer_notes_read_at=NULL,
                reviewed_by=?, reviewed_at=?, removed_at=?, updated_at=?
            WHERE appliance_id=? OR copied_from_appliance_id=?
            """,
            (reason, request.current_user["user_id"], stamp, stamp, stamp, appliance_id, appliance_id),
        )
        withdraw_inventory_copies(db, appliance_id)
        notify_users(db, users, "Appliance removed", removal_message(row["appliance_name"]),
                     "appliance", appliance_id)
        audit(db, request.current_user["user_id"], "removed_approved", "appliance", appliance_id,
              {"reason": reason, "households_notified": len(users)})
    return jsonify(ok=True, households_notified=len(users))


@app.post("/api/admin/consumption/<int:consumption_id>/delete")
@require_auth("admin")
def delete_approved_consumption(consumption_id: int):
    reason = text_value(json_body(), "reason")
    if not reason:
        return jsonify(error="A reason is required to delete an approved bill"), 400
    with get_db() as db:
        row = db.execute(
            """
            SELECT m.billing_month, m.verification_status, h.user_id
            FROM monthly_consumption m JOIN households h ON h.household_id=m.household_id
            WHERE m.consumption_id=? AND m.deleted_at IS NULL
            """,
            (consumption_id,),
        ).fetchone()
        if not row:
            return jsonify(error="Bill not found"), 404
        if row["verification_status"] != "approved":
            return jsonify(error="Only approved bills are deleted here; reject pending ones instead"), 409
        stamp = now()
        # Also marked rejected, so restoring it from Recently Deleted can't bring back an approved bill.
        db.execute(
            """
            UPDATE monthly_consumption
            SET verification_status='rejected', reviewer_notes=?, reviewer_notes_read_at=NULL,
                reviewed_by=?, reviewed_at=?, deleted_at=?, updated_at=?
            WHERE consumption_id=?
            """,
            (reason, request.current_user["user_id"], stamp, stamp, stamp, consumption_id),
        )
        month = datetime.strptime(row["billing_month"], "%Y-%m").strftime("%B %Y")
        notify_users(db, {row["user_id"]}, "Bill deleted by admin",
                     f"An admin deleted your {month} bill.", "consumption", consumption_id)
        audit(db, request.current_user["user_id"], "deleted_approved", "consumption", consumption_id,
              {"reason": reason})
    return jsonify(ok=True)


@app.get("/api/admin/users")
@require_auth("admin", "guimelco", "researcher")
def list_users():
    with get_db() as db:
        rows = db.execute(
            """
            SELECT u.user_id, u.full_name, u.email, u.status, u.created_at,
                   r.role_name AS role, h.barangay, h.municipality,
                   COUNT(DISTINCT a.appliance_id) AS appliance_count,
                   COUNT(DISTINCT m.consumption_id) AS consumption_count
            FROM users u
            JOIN roles r ON r.role_id=u.role_id
            LEFT JOIN households h ON h.user_id=u.user_id
            LEFT JOIN appliances a ON a.household_id=h.household_id
            LEFT JOIN monthly_consumption m ON m.household_id=h.household_id AND m.deleted_at IS NULL
            GROUP BY u.user_id
            ORDER BY u.created_at DESC
            """
        ).fetchall()
    return jsonify(users=[dict(row) for row in rows])


@app.patch("/api/admin/users/<int:user_id>")
@require_auth("admin")
def update_user_status(user_id: int):
    status = text_value(json_body(), "status", True)
    if status not in ("active", "inactive"):
        return jsonify(error="Status must be active or inactive"), 400
    if user_id == request.current_user["user_id"]:
        return jsonify(error="You cannot deactivate your current account"), 400
    with get_db() as db:
        if not db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
            return jsonify(error="User not found"), 404
        db.execute(
            "UPDATE users SET status=?, updated_at=? WHERE user_id=?",
            (status, now(), user_id),
        )
        audit(db, request.current_user["user_id"], status, "user", user_id)
    return jsonify(ok=True, status=status)


@app.get("/api/notifications")
@require_auth()
def list_notifications():
    with get_db() as db:
        rows = db.execute(
            """
            SELECT notification_id, title, message, type, is_read, created_at, entity_type, entity_id
            FROM notifications WHERE user_id=?
            ORDER BY created_at DESC, notification_id DESC LIMIT 30
            """,
            (request.current_user["user_id"],),
        ).fetchall()
    return jsonify(notifications=[dict(row) for row in rows])


def submission_snapshot(db: sqlite3.Connection, kind: str | None, entity_id: int | None) -> dict[str, Any] | None:
    """Current state of the submission a notification refers to; None if unlinked, deleted=True if gone."""
    if kind == "appliance" and entity_id:
        row = db.execute(
            """
            SELECT a.appliance_name AS title, c.category_name, a.brand, a.power_rating_watts,
                   a.quantity, a.avg_daily_usage_hours, a.source_of_info,
                   a.verification_status, a.reviewer_notes, a.reviewed_at, NULL AS deleted_at
            FROM appliances a JOIN appliance_categories c ON c.category_id=a.category_id
            WHERE a.appliance_id=?
            """,
            (entity_id,),
        ).fetchone()
    elif kind == "consumption" and entity_id:
        row = db.execute(
            """
            SELECT billing_month AS title, consumption_kwh, bill_amount_php, source_of_info,
                   verification_status, reviewer_notes, reviewed_at, deleted_at
            FROM monthly_consumption WHERE consumption_id=?
            """,
            (entity_id,),
        ).fetchone()
    else:
        return None
    if not row:
        return {"type": kind, "id": entity_id, "deleted": True}
    return {"type": kind, "id": entity_id, **dict(row), "deleted": bool(row["deleted_at"])}


def owned_notification(db: sqlite3.Connection, notification_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM notifications WHERE notification_id=? AND user_id=?",
        (notification_id, request.current_user["user_id"]),
    ).fetchone()


@app.get("/api/notifications/<int:notification_id>")
@require_auth()
def notification_detail(notification_id: int):
    with get_db() as db:
        note = owned_notification(db, notification_id)
        if not note:
            return jsonify(error="Notification not found"), 404
        payload = dict(note)
        payload["feedback"] = []
        payload["can_send_feedback"] = False
        if note["entity_type"] == "feedback":
            # Admin view of feedback a household sent about a reviewed submission.
            feedback = db.execute(
                """
                SELECT f.feedback_id, f.message, f.created_at, u.full_name AS sender,
                       n.entity_type, n.entity_id
                FROM notification_feedback f
                JOIN users u ON u.user_id=f.user_id
                JOIN notifications n ON n.notification_id=f.notification_id
                WHERE f.feedback_id=?
                """,
                (note["entity_id"],),
            ).fetchone()
            payload["feedback_received"] = dict(feedback) if feedback else None
            payload["submission"] = (
                submission_snapshot(db, feedback["entity_type"], feedback["entity_id"]) if feedback else None
            )
        else:
            payload["submission"] = submission_snapshot(db, note["entity_type"], note["entity_id"])
            payload["feedback"] = [dict(r) for r in db.execute(
                """
                SELECT feedback_id, message, created_at FROM notification_feedback
                WHERE notification_id=? ORDER BY feedback_id
                """,
                (notification_id,),
            )]
            payload["can_send_feedback"] = note["type"] == "submission_update"
    return jsonify(notification=payload)


@app.patch("/api/notifications/<int:notification_id>")
@require_auth()
def update_notification(notification_id: int):
    is_read = json_body().get("is_read")
    if not isinstance(is_read, bool):
        return jsonify(error="is_read must be true or false"), 400
    with get_db() as db:
        if not owned_notification(db, notification_id):
            return jsonify(error="Notification not found"), 404
        db.execute(
            "UPDATE notifications SET is_read=? WHERE notification_id=?",
            (1 if is_read else 0, notification_id),
        )
    return jsonify(ok=True, is_read=is_read)


@app.post("/api/notifications/read-all")
@require_auth()
def read_all_notifications():
    with get_db() as db:
        updated = db.execute(
            "UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0",
            (request.current_user["user_id"],),
        ).rowcount
    return jsonify(ok=True, updated=updated)


@app.post("/api/notifications/<int:notification_id>/feedback")
@require_auth()
def send_notification_feedback(notification_id: int):
    message = text_value(json_body(), "message") or ""
    if not message:
        return jsonify(error="Feedback message is required"), 400
    if len(message) > 1000:
        return jsonify(error="Feedback must be 1000 characters or fewer"), 400
    sender = request.current_user
    with get_db() as db:
        note = owned_notification(db, notification_id)
        if not note:
            return jsonify(error="Notification not found"), 404
        if note["type"] != "submission_update" or note["entity_type"] == "feedback":
            return jsonify(error="Feedback can only be sent about a reviewed submission"), 400
        feedback_id = db.execute(
            "INSERT INTO notification_feedback(notification_id, user_id, message) VALUES (?, ?, ?)",
            (notification_id, sender["user_id"], message),
        ).lastrowid
        kind = note["entity_type"] or "submission"
        preview = message if len(message) <= 160 else message[:157] + "..."
        admins = db.execute(
            """
            SELECT u.user_id FROM users u JOIN roles r ON r.role_id=u.role_id
            WHERE r.role_name='admin' AND u.status='active'
            """
        ).fetchall()
        for admin in admins:
            db.execute(
                """
                INSERT INTO notifications(user_id, title, message, type, entity_type, entity_id)
                VALUES (?, ?, ?, 'submission_update', 'feedback', ?)
                """,
                (admin["user_id"], f"Feedback from {sender['full_name']}", f"About their {kind} review: {preview}", feedback_id),
            )
        audit(db, sender["user_id"], "feedback_sent", "notification", notification_id, {"feedback_id": feedback_id})
    return jsonify(ok=True, feedback_id=feedback_id), 201


NO_MODEL = "No trained model yet"
DATA_SOURCES = {"monthly_energy": "real", "annual_peak": "real", "demand_class": "synthetic"}
MAX_DAILY_RANGE_DAYS = 400


def active_run(db: sqlite3.Connection, task: str) -> dict[str, Any] | None:
    """Latest active model run for a task, with parsed metrics; None if absent."""
    try:
        row = db.execute(
            """
            SELECT run_id, task, model_name, dataset_version, trained_at, metrics
            FROM model_runs WHERE task = ? AND is_active = 1
            ORDER BY run_id DESC LIMIT 1
            """,
            (task,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    try:
        metrics = json.loads(row["metrics"]) if row["metrics"] else {}
    except (TypeError, ValueError):
        metrics = {}
    return {
        "task": row["task"],
        "run_id": row["run_id"],
        "model_name": row["model_name"],
        "dataset_version": row["dataset_version"],
        "trained_at": row["trained_at"],
        "metrics": metrics if isinstance(metrics, dict) else {},
        "data_source": DATA_SOURCES.get(row["task"], "real"),
    }


def no_model_response():
    return jsonify(error=NO_MODEL), 404


@app.get("/api/models/active")
@require_auth()
def api_models_active():
    with get_db() as db:
        runs = [r for r in (active_run(db, t) for t in DATA_SOURCES) if r]
    return jsonify(runs=runs)


@app.get("/api/forecast/monthly")
@require_auth()
def api_forecast_monthly():
    try:
        with get_db() as db:
            run = active_run(db, "monthly_energy")
            if not run:
                return no_model_response()
            history = db.execute(
                "SELECT year, month, energy_mwh FROM utility_monthly_energy ORDER BY year, month"
            ).fetchall()
            forecast = db.execute(
                """
                SELECT year, month, forecast_mwh, lo80, hi80, lo95, hi95
                FROM forecast_monthly WHERE run_id = ? ORDER BY year, month
                """,
                (run["run_id"],),
            ).fetchall()
    except sqlite3.OperationalError:
        return no_model_response()
    return jsonify(
        data_source="real",
        dataset_version=run["dataset_version"],
        model=run,
        history=[dict(r) for r in history],
        forecast=[dict(r) for r in forecast],
    )


@app.get("/api/forecast/peak")
@require_auth()
def api_forecast_peak():
    try:
        with get_db() as db:
            run = active_run(db, "annual_peak")
            if not run:
                return no_model_response()
            history = db.execute(
                """
                SELECT year, coincident_peak_mw AS peak_mw FROM utility_annual_stats
                WHERE coincident_peak_mw IS NOT NULL ORDER BY year
                """
            ).fetchall()
            forecast = db.execute(
                "SELECT year, peak_mw, lo, hi FROM forecast_annual_peak WHERE run_id = ? ORDER BY year",
                (run["run_id"],),
            ).fetchall()
    except sqlite3.OperationalError:
        return no_model_response()
    return jsonify(
        data_source="real",
        dataset_version=run["dataset_version"],
        model=run,
        history=[dict(r) for r in history],
        forecast=[dict(r) for r in forecast],
    )


def parse_iso_date(value: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@app.get("/api/demand/daily")
@require_auth()
def api_demand_daily():
    raw_from = request.args.get("from")
    raw_to = request.args.get("to")
    start = end = None
    if raw_from is not None:
        start = parse_iso_date(raw_from)
        if start is None:
            return jsonify(error="'from' must be a date in YYYY-MM-DD format"), 400
    if raw_to is not None:
        end = parse_iso_date(raw_to)
        if end is None:
            return jsonify(error="'to' must be a date in YYYY-MM-DD format"), 400
    if start and end and start > end:
        return jsonify(error="'from' must not be after 'to'"), 400
    try:
        with get_db() as db:
            run = active_run(db, "demand_class")
            if not run:
                return no_model_response()
            version = run["dataset_version"]
            bounds = db.execute(
                "SELECT MIN(date) AS lo, MAX(date) AS hi FROM synth_daily_peaks WHERE dataset_version = ?",
                (version,),
            ).fetchone()
            if not bounds["lo"]:
                return no_model_response()
            data_min = date.fromisoformat(bounds["lo"])
            data_max = date.fromisoformat(bounds["hi"])
            if start is None and end is None:
                end = data_max
                start = max(data_min, end - timedelta(days=29))
            else:
                start = start or data_min
                end = end or data_max
            if start > end:
                return jsonify(error="'from' must not be after 'to'"), 400
            if (end - start).days + 1 > MAX_DAILY_RANGE_DAYS:
                return jsonify(error=f"Date range is limited to {MAX_DAILY_RANGE_DAYS} days"), 400
            rows = db.execute(
                """
                SELECT s.date AS date, s.peak_mw AS peak_mw, s.demand_level AS actual_level,
                       p.predicted_level AS predicted_level,
                       p.p_high AS p_high, p.p_medium AS p_medium, p.p_low AS p_low
                FROM synth_daily_peaks s
                LEFT JOIN demand_predictions p ON p.date = s.date AND p.run_id = ?
                WHERE s.dataset_version = ? AND s.date >= ? AND s.date <= ?
                ORDER BY s.date
                """,
                (run["run_id"], version, start.isoformat(), end.isoformat()),
            ).fetchall()
    except sqlite3.OperationalError:
        return no_model_response()
    return jsonify(
        data_source="synthetic",
        dataset_version=version,
        model=run,
        days=[dict(r) for r in rows],
    )


@app.get("/api/explain")
@require_auth()
def api_explain():
    try:
        with get_db() as db:
            clf = active_run(db, "demand_class")
            fc = active_run(db, "monthly_energy")
            if not clf or not fc:
                return no_model_response()
            importance = db.execute(
                """
                SELECT feature, importance FROM feature_importance
                WHERE run_id = ? AND kind = 'permutation'
                ORDER BY importance DESC, feature
                """,
                (clf["run_id"],),
            ).fetchall()
            parts = db.execute(
                """
                SELECT year, month, feature, importance FROM feature_importance
                WHERE run_id = ? AND kind = 'breakdown' ORDER BY year, month
                """,
                (fc["run_id"],),
            ).fetchall()
    except sqlite3.OperationalError:
        return no_model_response()
    pivot: dict[tuple[int, int], dict[str, Any]] = {}
    for r in parts:
        if r["year"] is None or r["month"] is None:
            continue
        row = pivot.setdefault(
            (r["year"], r["month"]),
            {"year": r["year"], "month": r["month"], "trend": None, "seasonality": None, "customer_growth": None},
        )
        if r["feature"] in ("trend", "seasonality", "customer_growth"):
            row[r["feature"]] = r["importance"]
    return jsonify(
        classifier={
            "data_source": "synthetic",
            "dataset_version": clf["dataset_version"],
            "model": clf,
            "importance": [dict(r) for r in importance],
        },
        forecast={
            "data_source": "real",
            "dataset_version": fc["dataset_version"],
            "model": fc,
            "breakdown": [pivot[k] for k in sorted(pivot)],
        },
    )


@app.get("/api/validated-data")
@require_auth("admin", "guimelco", "researcher")
def api_validated_data():
    """Real GUIMELCO records plus aggregated, admin-approved crowdsourced submissions."""
    with get_db() as db:
        try:
            monthly = db.execute(
                "SELECT year, month, energy_mwh, source FROM utility_monthly_energy ORDER BY year, month"
            ).fetchall()
            annual = db.execute(
                """
                SELECT a.year, a.total_mwh_reported, a.customers, a.coincident_peak_mw, a.notes,
                       (SELECT ROUND(SUM(m.energy_mwh), 3) FROM utility_monthly_energy m
                        WHERE m.year = a.year) AS monthly_sum_mwh
                FROM utility_annual_stats a ORDER BY a.year
                """
            ).fetchall()
        except sqlite3.OperationalError:
            monthly, annual = [], []
        bills = db.execute(
            """
            SELECT billing_month, COUNT(DISTINCT household_id) AS households, COUNT(*) AS bills,
                   ROUND(SUM(consumption_kwh), 1) AS total_kwh, ROUND(AVG(consumption_kwh), 1) AS avg_kwh
            FROM monthly_consumption
            WHERE verification_status = 'approved' AND deleted_at IS NULL
            GROUP BY billing_month ORDER BY billing_month
            """
        ).fetchall()
        categories = db.execute(
            """
            SELECT c.category_name, COUNT(*) AS appliances, ROUND(AVG(a.power_rating_watts), 1) AS avg_watts
            FROM appliances a JOIN appliance_categories c ON c.category_id = a.category_id
            WHERE a.verification_status = 'approved'
            GROUP BY c.category_name ORDER BY appliances DESC, c.category_name
            """
        ).fetchall()
        households = db.execute(
            """
            SELECT COUNT(DISTINCT household_id) AS n FROM (
              SELECT household_id FROM monthly_consumption WHERE verification_status = 'approved' AND deleted_at IS NULL
              UNION
              SELECT household_id FROM appliances WHERE verification_status = 'approved'
            )
            """
        ).fetchone()["n"]
    return jsonify(
        utility={
            "data_source": "real",
            "source": monthly[0]["source"] if monthly else None,
            "monthly": [{"year": r["year"], "month": r["month"], "energy_mwh": r["energy_mwh"]} for r in monthly],
            "annual": [dict(r) for r in annual],
        },
        crowdsourced={
            "data_source": "crowdsourced",
            "monthly": [dict(r) for r in bills],
            "categories": [dict(r) for r in categories],
            "totals": {
                "households": int(households),
                "approved_bills": sum(int(r["bills"]) for r in bills),
                "approved_appliances": sum(int(r["appliances"]) for r in categories),
            },
        },
    )


def short_name(full_name: str) -> str:
    """'Juan Dela Cruz' -> 'Juan D.' so staff views don't expose full household names."""
    parts = str(full_name or "").split()
    if not parts:
        return "Household"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[1][0]}."


@app.get("/api/contributors")
@require_auth("admin", "guimelco", "researcher")
def api_contributors():
    with get_db() as db:
        rows = db.execute(
            """
            WITH subs AS (
              SELECT household_id, verification_status FROM appliances
              UNION ALL
              SELECT household_id, verification_status FROM monthly_consumption WHERE deleted_at IS NULL
            )
            SELECT u.full_name, u.created_at, COUNT(*) AS submissions,
                   SUM(s.verification_status = 'approved') AS approved
            FROM subs s
            JOIN households h ON h.household_id = s.household_id
            JOIN users u ON u.user_id = h.user_id
            WHERE u.status = 'active'
            GROUP BY h.household_id
            ORDER BY approved DESC, submissions DESC, u.created_at
            """
        ).fetchall()
    contributors = []
    for rank, r in enumerate(rows, start=1):
        name = short_name(r["full_name"])
        contributors.append({
            "rank": rank,
            "name": name,
            "initials": "".join(p[0] for p in name.replace(".", "").split()[:2]).upper(),
            "submissions": int(r["submissions"]),
            "approved": int(r["approved"]),
            "approval_rate": round(int(r["approved"]) / int(r["submissions"]) * 100, 1),
            "joined": str(r["created_at"])[:7],
        })
    return jsonify(contributors=contributors)


@app.get("/")
def root():
    return redirect("/index.html")


@app.get("/<path:asset_path>")
def static_files(asset_path: str):
    safe_suffixes = {".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico"}
    path = ROOT / asset_path
    if path.suffix.lower() not in safe_suffixes or not path.is_file():
        return jsonify(error="Not found"), 404
    return send_from_directory(ROOT, asset_path)


initialize_database()

if __name__ == "__main__":
    print("GUIMPOWERCORE running at http://127.0.0.1:4173")
    app.run(host="127.0.0.1", port=4173, debug=False)
