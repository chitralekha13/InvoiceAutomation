import logging
import json
import os
import azure.functions as func
import psycopg2
import psycopg2.extras
from datetime import date, datetime

# ── Connection ────────────────────────────────────────────────────────────────
CONNECTION_STRING = os.environ.get("SQL_CONNECTION_STRING", "")

def get_conn():
    return psycopg2.connect(CONNECTION_STRING, cursor_factory=psycopg2.extras.RealDictCursor)

def cors_headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

def json_serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serialisable")

def resp(data, status=200):
    return func.HttpResponse(
        json.dumps(data, default=json_serial),
        status_code=status,
        headers=cors_headers(),
    )

# ── Main entry point ──────────────────────────────────────────────────────────
def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info(f"[UserMgmt] {req.method} {req.url}")

    # CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=200, headers=cors_headers())

    if req.method != "POST":
        return resp({"error": "Method not allowed"}, 405)

    try:
        body = req.get_json()
    except ValueError:
        return resp({"error": "Invalid JSON body"}, 400)

    action = body.get("action", "").strip()

    try:
        if action == "list":
            return list_users()

        elif action == "adduser":
            return add_user(body)

        elif action == "updateuser":
            return update_user(body)

        else:
            return resp({"error": f"Unknown action: '{action}'. Use list, adduser, or updateuser."}, 400)

    except Exception as e:
        logging.exception("Unhandled error")
        return resp({"error": str(e)}, 500)


# Handlers 

def list_users():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT firstname, lastname, email, org, last_access_date, status, role
                FROM users
                ORDER BY firstname ASC;
            """)
            rows = cur.fetchall()
    return resp({"users": [dict(r) for r in rows]})


def add_user(body):
    required = ["firstname", "lastname", "email", "org", "status", "role"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return resp({"error": f"Missing fields: {', '.join(missing)}"}, 400)

    VALID_STATUSES = {"active", "inactive", "suspended"}
    VALID_ROLES    = {"admin", "user"}

    if body["status"] not in VALID_STATUSES:
        return resp({"error": "Invalid status. Use: active, inactive, suspended"}, 400)
    if body["role"] not in VALID_ROLES:
        return resp({"error": "Invalid role. Use: admin, user"}, 400)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (firstname, lastname, email, org, last_access_date, status, role)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s)
                RETURNING firstname, lastname, email, org, last_access_date, status, role;
            """, (body["firstname"], body["lastname"], body["email"], body["org"], body["status"], body["role"]))
            new_row = dict(cur.fetchone())
        conn.commit()

    return resp({"message": "User created", "user": new_row}, 201)


def update_user(body):
    email = body.get("email")
    if not email:
        return resp({"error": "email is required"}, 400)

    VALID_STATUSES = {"active", "inactive", "suspended"}
    VALID_ROLES    = {"admin", "user"}

    updates, params = [], []

    if "status" in body:
        if body["status"] not in VALID_STATUSES:
            return resp({"error": "Invalid status. Use: active, inactive, suspended"}, 400)
        updates.append("status = %s")
        params.append(body["status"])

    if "role" in body:
        if body["role"] not in VALID_ROLES:
            return resp({"error": "Invalid role. Use: admin, user"}, 400)
        updates.append("role = %s")
        params.append(body["role"])

    if not updates:
        return resp({"error": "Provide at least one of: status, role"}, 400)

    params.append(email)
    sql = f"UPDATE users SET {', '.join(updates)} WHERE email = %s RETURNING firstname, lastname, email, org, status, role;"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            updated = cur.fetchone()
            if not updated:
                return resp({"error": "User not found"}, 404)
        conn.commit()

    return resp({"message": "User updated", "user": dict(updated)})
