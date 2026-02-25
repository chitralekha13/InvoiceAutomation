import logging
import psycopg2
import json
import os
import azure.functions as func


def main(req: func.HttpRequest) -> func.HttpResponse:

    try:
        email = req.get_json().get("email", "").strip().lower()
    except ValueError:
        return _response({"allowed": False, "reason": "Invalid request"}, 400)

    if not email:
        return _response({"allowed": False, "reason": "Email required"}, 400)

    try:
        conn = psycopg2.connect(os.environ["SQL_CONNECTION_STRING"])
        with conn.cursor() as cur:

            cur.execute("""
                UPDATE users
                SET last_access_date = NOW() AT TIME ZONE 'UTC'
                WHERE email = %s
                AND status = 'active';
            """, (email,))

            cur.execute("""
                SELECT org
                FROM users
                WHERE email = %s
                AND status = 'active'
                group by 1;
            """, (email,))
            
            row = cur.fetchone()
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"DB error: {str(e)}")
        return _response({"allowed": False, "reason": "DB error"}, 500)

    if not row:
        return _response({"allowed": False}, 403)

    return _response({"allowed": True, "org": row[0]}, 200)


def _response(data: dict, status: int) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data),
        status_code=status,
        mimetype="application/json"
    )