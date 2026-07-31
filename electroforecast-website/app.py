from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Iterator

from flask import Flask, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = ROOT / "database" / "electroforecast.db"
SCHEMA_PATH = ROOT / "database" / "schema.sqlite.sql"

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=os.environ.get("ELECTROFORECAST_SECRET", "electroforecast-local-development-key"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

CATALOG_APPROVAL_NOTE = (
    "Automatically accepted from an administrator-approved appliance rating."
)


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
        db.execute(
            """
            UPDATE appliances
            SET verification_status='approved',
                reviewer_notes=?,
                reviewed_at=COALESCE(reviewed_at, ?)
            WHERE copied_from_appliance_id IS NOT NULL
            """,
            (CATALOG_APPROVAL_NOTE, now()),
        )

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


def text_value(data: dict[str, Any], key: str, required: bool = False) -> str | None:
    value = str(data.get(key, "")).strip()
    if required and not value:
        raise ValueError(f"{key.replace('_', ' ').title()} is required")
    return value or None


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
    destination = (
        "admin-dashboard.html"
        if payload["role"] in ("admin", "guimelco", "researcher")
        else "user-portal.html"
    )
    return jsonify(user=payload, redirect=destination)


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/auth/me")
@require_auth()
def me():
    return jsonify(user=request.current_user)


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
            FROM household_appliances WHERE household_id = ?
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
            FROM monthly_consumption WHERE household_id = ?
            """,
            (household_id,),
        ).fetchone()
        latest = db.execute(
            """
            SELECT billing_month, consumption_kwh, verification_status
            FROM monthly_consumption WHERE household_id = ?
            ORDER BY billing_month DESC LIMIT 1
            """,
            (household_id,),
        ).fetchone()
        approved_points = db.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM appliances WHERE household_id=? AND verification_status='approved') +
              (SELECT COUNT(*) FROM monthly_consumption WHERE household_id=? AND verification_status='approved')
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
       a.copied_from_appliance_id, a.created_at, a.updated_at,
       c.category_id, c.category_name,
       EXISTS(
         SELECT 1 FROM household_appliances ha
         WHERE ha.household_id=a.household_id
           AND ha.source_appliance_id=a.appliance_id
       ) AS in_inventory,
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


HOUSEHOLD_APPLIANCE_SELECT = """
SELECT ha.inventory_id, ha.source_appliance_id, ha.appliance_name,
       ha.brand, ha.model, ha.power_rating_watts, ha.quantity,
       ha.avg_daily_usage_hours, ha.source_of_info,
       ha.created_at, ha.updated_at, c.category_id, c.category_name,
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
            + " WHERE ha.household_id=? ORDER BY ha.updated_at DESC",
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
            SELECT inventory_id FROM household_appliances
            WHERE household_id=? AND source_appliance_id=?
            """,
            (household_id, source["appliance_id"]),
        ).fetchone()
        if existing:
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
            WHERE inventory_id=? AND household_id=?
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
            WHERE inventory_id=? AND household_id=?
            """,
            (inventory_id, household_id),
        ).fetchone()
        if not row:
            return jsonify(error="Household appliance not found"), 404
        db.execute(
            """
            DELETE FROM household_appliances
            WHERE inventory_id=? AND household_id=?
            """,
            (inventory_id, household_id),
        )
        audit(
            db,
            request.current_user["user_id"],
            "removed",
            "household_appliance",
            inventory_id,
            {"appliance_name": row["appliance_name"]},
        )
    return jsonify(ok=True)


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
            SELECT appliance_name, copied_from_appliance_id
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
                    updated_at=?
                WHERE appliance_id=? AND household_id=?
                """,
                (
                    quantity,
                    avg_hours,
                    CATALOG_APPROVAL_NOTE,
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
                reviewer_notes=NULL, reviewed_by=NULL, reviewed_at=NULL, updated_at=?
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
            "SELECT appliance_name FROM appliances WHERE appliance_id=? AND household_id=?",
            (appliance_id, household_id),
        ).fetchone()
        if not row:
            return jsonify(error="Appliance not found"), 404
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
            {"appliance_name": row["appliance_name"]},
        )
    return jsonify(ok=True)


CONSUMPTION_SELECT = """
SELECT consumption_id, billing_month, consumption_kwh, bill_amount_php,
       meter_reading, source_of_info, verification_status, reviewer_notes,
       created_at, updated_at
FROM monthly_consumption
"""


@app.get("/api/consumption")
@require_auth("household")
def list_consumption():
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        rows = db.execute(
            CONSUMPTION_SELECT + " WHERE household_id=? ORDER BY billing_month DESC",
            (household_id,),
        ).fetchall()
    return jsonify(records=[dict(row) for row in rows])


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
        fields = consumption_fields(json_body())
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        cursor = db.execute(
            """
            INSERT INTO monthly_consumption
              (household_id, billing_month, consumption_kwh, bill_amount_php,
               meter_reading, source_of_info)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (household_id, *fields.values()),
        )
        consumption_id = int(cursor.lastrowid)
        audit(db, request.current_user["user_id"], "created", "monthly_consumption", consumption_id, fields)
        row = db.execute(
            CONSUMPTION_SELECT + " WHERE consumption_id=?", (consumption_id,)
        ).fetchone()
    return jsonify(record=dict(row)), 201


@app.patch("/api/consumption/<int:consumption_id>")
@require_auth("household")
def update_consumption(consumption_id: int):
    try:
        fields = consumption_fields(json_body())
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        existing = db.execute(
            "SELECT 1 FROM monthly_consumption WHERE consumption_id=? AND household_id=?",
            (consumption_id, household_id),
        ).fetchone()
        if not existing:
            return jsonify(error="Consumption record not found"), 404
        db.execute(
            """
            UPDATE monthly_consumption
            SET billing_month=?, consumption_kwh=?, bill_amount_php=?, meter_reading=?,
                source_of_info=?, verification_status='pending', reviewer_notes=NULL,
                reviewed_by=NULL, reviewed_at=NULL, updated_at=?
            WHERE consumption_id=? AND household_id=?
            """,
            (*fields.values(), now(), consumption_id, household_id),
        )
        audit(db, request.current_user["user_id"], "updated", "monthly_consumption", consumption_id, fields)
        row = db.execute(
            CONSUMPTION_SELECT + " WHERE consumption_id=?", (consumption_id,)
        ).fetchone()
    return jsonify(record=dict(row))


@app.delete("/api/consumption/<int:consumption_id>")
@require_auth("household")
def delete_consumption(consumption_id: int):
    with get_db() as db:
        household_id = household_id_for(request.current_user["user_id"], db)
        row = db.execute(
            "SELECT billing_month FROM monthly_consumption WHERE consumption_id=? AND household_id=?",
            (consumption_id, household_id),
        ).fetchone()
        if not row:
            return jsonify(error="Consumption record not found"), 404
        db.execute(
            "DELETE FROM monthly_consumption WHERE consumption_id=? AND household_id=?",
            (consumption_id, household_id),
        )
        audit(
            db,
            request.current_user["user_id"],
            "deleted",
            "monthly_consumption",
            consumption_id,
            {"billing_month": row["billing_month"]},
        )
    return jsonify(ok=True)


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
               h.barangay, h.municipality, c.category_name
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
               h.barangay, h.municipality, 'Monthly Consumption' AS category_name
        FROM monthly_consumption m
        JOIN households h ON h.household_id=m.household_id
        JOIN users u ON u.user_id=h.user_id
        WHERE 1=1 {status_clause.format(alias='m')}
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
            for row in db.execute(
                f"SELECT verification_status, COUNT(*) AS count FROM {table} GROUP BY verification_status"
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
    with get_db() as db:
        row = db.execute(
            f"""
            SELECT h.user_id
            FROM {table} s JOIN households h ON h.household_id=s.{household_column}
            WHERE s.{id_column}=?
            """,
            (submission_id,),
        ).fetchone()
        if not row:
            return jsonify(error="Submission not found"), 404
        db.execute(
            f"""
            UPDATE {table}
            SET verification_status=?, reviewer_notes=?, reviewed_by=?, reviewed_at=?, updated_at=?
            WHERE {id_column}=?
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
            INSERT INTO notifications(user_id, title, message, type)
            VALUES (?, ?, ?, 'submission_update')
            """,
            (
                row["user_id"],
                "Submission reviewed",
                f"Your {submission_type} submission was {status}.",
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
            LEFT JOIN monthly_consumption m ON m.household_id=h.household_id
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
            SELECT notification_id, title, message, type, is_read, created_at
            FROM notifications WHERE user_id=?
            ORDER BY created_at DESC LIMIT 30
            """,
            (request.current_user["user_id"],),
        ).fetchall()
    return jsonify(notifications=[dict(row) for row in rows])


@app.get("/")
def root():
    return redirect("/login.html")


@app.get("/<path:asset_path>")
def static_files(asset_path: str):
    safe_suffixes = {".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico"}
    path = ROOT / asset_path
    if path.suffix.lower() not in safe_suffixes or not path.is_file():
        return jsonify(error="Not found"), 404
    return send_from_directory(ROOT, asset_path)


initialize_database()

if __name__ == "__main__":
    print("ElectroForecast running at http://127.0.0.1:4173")
    app.run(host="127.0.0.1", port=4173, debug=False)
