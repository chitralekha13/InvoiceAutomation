"""
Update SOW: POST api/sow/{id}/update. Updates editable fields in sow_documents.
"""
import azure.functions as func
import logging
import json
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)


ALLOWED_SOW_FIELDS = {
    "resource_name",
    "consultancy_name",
    "sow_start_date",
    "sow_end_date",
    "net_terms",
    "max_sow_hours",
    "rate_per_hour",
    "project_role",
    "sow_project_duration",
    "employee_id",
}


def _coerce_value(field: str, value: Any) -> Any:
    """Coerce incoming string values to appropriate types where needed."""
    if value is None:
        return None
    if field in {"max_sow_hours", "rate_per_hour"}:
        try:
            s = str(value).replace("$", "").replace(",", "").strip()
            return float(s)
        except (ValueError, TypeError):
            return value
    # Dates are stored as strings (DATE columns accept ISO-ish strings)
    return value


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("SOW update function processed a request.")
    if req.method != "POST":
        return func.HttpResponse("Method not allowed", status_code=405)

    sow_id = (req.route_params or {}).get("id")
    if not sow_id:
        return func.HttpResponse(
            json.dumps({"error": "SOW id required"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        try:
            body = req.get_json()
        except ValueError:
            body = {}

        field = (body or {}).get("field")
        value = (body or {}).get("value")

        updates: Dict[str, Any] = {}
        if field:
            if field not in ALLOWED_SOW_FIELDS:
                return func.HttpResponse(
                    json.dumps({"error": f"Field '{field}' is not editable"}),
                    status_code=400,
                    mimetype="application/json",
                )
            updates[field] = _coerce_value(field, value)
        else:
            # Optionally accept a full updates dict
            for k, v in (body or {}).get("updates", {}).items():
                if k in ALLOWED_SOW_FIELDS:
                    updates[k] = _coerce_value(k, v)

        if not updates:
            return func.HttpResponse(
                json.dumps({"error": "No valid fields to update"}),
                status_code=400,
                mimetype="application/json",
            )

        sys_path = os.path.join(os.path.dirname(__file__), "..")
        if sys_path not in __import__("sys").path:
            __import__("sys").path.insert(0, sys_path)

        from shared.helpers import (  # type: ignore
            update_sow,
            get_sow_by_id,
            propagate_employee_id_to_matching_invoices,
        )

        if not os.environ.get("SQL_CONNECTION_STRING"):
            return func.HttpResponse(
                json.dumps({"error": "Database not configured"}),
                status_code=503,
                mimetype="application/json",
            )

        update_sow(sow_id, **updates)

        if "employee_id" in updates and (updates.get("employee_id") or "").strip():
            sow_row = get_sow_by_id(sow_id)
            if sow_row:
                propagate_employee_id_to_matching_invoices(
                    sow_row.get("resource_name"),
                    sow_row.get("consultancy_name"),
                    updates.get("employee_id"),
                )

        return func.HttpResponse(
            json.dumps({"status": "ok", "updated_fields": updates}, default=str),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("SOW update failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )

