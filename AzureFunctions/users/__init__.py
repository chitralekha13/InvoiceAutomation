import logging
import json
import os
import azure.functions as func
import psycopg2
import psycopg2.extras
from datetime import date

# ── Connection ───────────────────────────────────────────────────────────────
# Set POSTGRES_CONNECTION_STRING in your Function App → Configuration → App Settings
CONNECTION_STRING = os.environ.get("SQL_CONNECTION_STRING", "")

def get_conn():
    return psycopg2.connect(CONNECTION_STRING, cursor_factory=psycopg2.extras.RealDictCursor)

def cors_headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PATCH, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

def json_serial(obj):
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serialisable")

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info(f"[UserMgmt] {req.method} {req.url}")

    if req.method == "OPTIONS":
        return func.HttpResponse("", status_code=200, headers=cors_headers())

    method = req.method.upper()
    route  = req.route_params.get("action", "")

    try:
        if method == "GET" and route == "":
            return get_users()
        if method == "POST" and route == "add":
            return add_user(req)
        if method == "PATCH" and route == "update":
            return update_user(req)

        return func.HttpResponse(
            json.dumps({"error": "Route not found"}),
            status_code=404, headers=cors_headers(),
        )
    except Exception as e:
        logging.exception("Unhandled error")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500, headers=cors_headers(),
        )


# Handlers

def get_users() -> func.HttpResponse:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, name, organisation, last_access_date, status, role
                FROM users
                ORDER BY user_id;
            """)
            rows = cur.fetchall()
    data = json.dumps({"users": [dict(r) for r in rows]}, default=json_serial)
    return func.HttpResponse(data, status_code=200, headers=cors_headers())


def add_user(req: func.HttpRequest) -> func.HttpResponse:
    body     = req.get_json()
    required = ["name", "organisation", "status", "role"]
    missing  = [f for f in required if not body.get(f)]
    if missing:
        return func.HttpResponse(
            json.dumps({"error": f"Missing fields: {', '.join(missing)}"}),
            status_code=400, headers=cors_headers(),
        )

    VALID_STATUSES = {"active", "inactive", "suspended"}
    VALID_ROLES    = {"admin","user"}

    if body["status"] not in VALID_STATUSES:
        return func.HttpResponse(json.dumps({"error": f"Invalid status"}), status_code=400, headers=cors_headers())
    if body["role"] not in VALID_ROLES:
        return func.HttpResponse(json.dumps({"error": f"Invalid role"}), status_code=400, headers=cors_headers())

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (name, organisation, last_access_date, status, role)
                VALUES (%s, %s, CURRENT_DATE, %s, %s)
                RETURNING user_id, name, organisation, last_access_date, status, role;
            """, (body["name"], body["organisation"], body["status"], body["role"]))
            new_row = dict(cur.fetchone())
        conn.commit()

    return func.HttpResponse(
        json.dumps({"message": "User created", "user": new_row}, default=json_serial),
        status_code=201, headers=cors_headers(),
    )


def update_user(req: func.HttpRequest) -> func.HttpResponse:
    body    = req.get_json()
    user_id = body.get("user_id")
    if not user_id:
        return func.HttpResponse(json.dumps({"error": "user_id is required"}), status_code=400, headers=cors_headers())

    VALID_STATUSES = {"active", "inactive", "suspended"}
    VALID_ROLES    = {"admin","user"}

    updates, params = [], []

    if "status" in body:
        if body["status"] not in VALID_STATUSES:
            return func.HttpResponse(json.dumps({"error": "Invalid status"}), status_code=400, headers=cors_headers())
        updates.append("status = %s"); params.append(body["status"])

    if "role" in body:
        if body["role"] not in VALID_ROLES:
            return func.HttpResponse(json.dumps({"error": "Invalid role"}), status_code=400, headers=cors_headers())
        updates.append("role = %s"); params.append(body["role"])

    if not updates:
        return func.HttpResponse(json.dumps({"error": "Provide at least one of: status, role"}), status_code=400, headers=cors_headers())

    params.append(user_id)
    sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s RETURNING user_id, name, status, role;"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            updated = cur.fetchone()
            if not updated:
                return func.HttpResponse(json.dumps({"error": "User not found"}), status_code=404, headers=cors_headers())
        conn.commit()

    return func.HttpResponse(
        json.dumps({"message": "User updated", "user": dict(updated)}),
        status_code=200, headers=cors_headers(),
    )
