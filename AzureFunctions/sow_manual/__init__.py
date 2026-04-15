"""
POST JSON — insert one SOW row into sow_documents without a file (same columns as upload pipeline).
"""
import json
import logging
import os
import uuid

import azure.functions as func

logger = logging.getLogger(__name__)


def _opt_str(v) -> str:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _opt_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main(req: func.HttpRequest) -> func.HttpResponse:
    if req.method != "POST":
        return func.HttpResponse(
            json.dumps({"error": "Method not allowed. Use POST with application/json."}),
            status_code=405,
            mimetype="application/json",
        )

    if not os.environ.get("SQL_CONNECTION_STRING"):
        return func.HttpResponse(
            json.dumps({"error": "Database not configured (SQL_CONNECTION_STRING)."}),
            status_code=503,
            mimetype="application/json",
        )

    try:
        body = req.get_json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return func.HttpResponse(
            json.dumps({"error": "Invalid JSON body."}),
            status_code=400,
            mimetype="application/json",
        )

    resource_name = _opt_str(body.get("resource_name"))
    employee_id = _opt_str(body.get("employee_id"))
    if not resource_name and not employee_id:
        return func.HttpResponse(
            json.dumps({"error": "Provide at least resource_name or employee_id."}),
            status_code=400,
            mimetype="application/json",
        )

    sys_path = os.path.join(os.path.dirname(__file__), "..")
    if sys_path not in __import__("sys").path:
        __import__("sys").path.insert(0, sys_path)
    from shared.helpers import insert_sow

    sow_id = str(uuid.uuid4())
    doc_name = _opt_str(body.get("doc_name")) or "(manual entry)"

    try:
        insert_sow(
            sow_id=sow_id,
            doc_name=doc_name,
            pdf_url=None,
            resource_name=resource_name,
            consultancy_name=_opt_str(body.get("consultancy_name")),
            sow_start_date=_opt_str(body.get("sow_start_date")),
            sow_end_date=_opt_str(body.get("sow_end_date")),
            net_terms=_opt_str(body.get("net_terms")),
            max_sow_hours=_opt_float(body.get("max_sow_hours")),
            rate_per_hour=_opt_float(body.get("rate_per_hour")),
            project_role=_opt_str(body.get("project_role")),
            sow_project_duration=_opt_str(body.get("sow_project_duration")),
            employee_id=employee_id,
        )
    except Exception as e:
        logger.exception("SOW manual insert failed: %s", e)
        return func.HttpResponse(
            json.dumps({"error": "Database insert failed", "detail": str(e)}),
            status_code=500,
            mimetype="application/json",
        )

    return func.HttpResponse(
        json.dumps(
            {
                "message": "SOW row created",
                "sow_id": sow_id,
                "doc_name": doc_name,
            }
        ),
        status_code=200,
        mimetype="application/json",
    )
