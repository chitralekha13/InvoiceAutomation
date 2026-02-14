"""
Update invoice details (Save from dashboard): POST api/fcfigures/{id}/update.
Maps dashboard fields to SQL columns and updates the invoice.
"""
import azure.functions as func
import logging
import json
import os

logger = logging.getLogger(__name__)

# Dashboard sends these; map to SQL column names (only columns that exist in invoices table)
FIELD_MAP = {
    "consultancy_name": "vendor_name",
    "current_comments": "notes",
    "project_name": "project_name",
    "template": "template",
    "joining_date": "joining_date",
    "ending_date": "ending_date",
    "approved_hours": "approved_hours",
    "addl_comments": "addl_comments",
}


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Fcfigures update function processed a request.")
    if req.method != "POST":
        return func.HttpResponse("Method not allowed", status_code=405)

    invoice_id = (req.route_params or {}).get("id")
    if not invoice_id:
        return func.HttpResponse(
            json.dumps({"error": "Invoice id required"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        body = req.get_json() if req.get_body() else {}
    except ValueError:
        body = {}

    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)
        from shared.helpers import get_invoice, update_invoice, extract_token_from_request, extract_user_id_from_token

        existing = get_invoice(invoice_id)
        if not existing:
            return func.HttpResponse(
                json.dumps({"error": "Invoice not found"}),
                status_code=404,
                mimetype="application/json",
            )

        # Build update kwargs: only fields that are in body and map to SQL columns
        kwargs = {}
        for dash_key, sql_col in FIELD_MAP.items():
            if dash_key in body:
                val = body[dash_key]
                if val == "":
                    val = None
                kwargs[sql_col] = val

        if kwargs:
            token = extract_token_from_request(req)
            user_id = extract_user_id_from_token(token) if token else "dashboard"
            kwargs["last_modified_by"] = user_id
            update_invoice(invoice_id, **kwargs)

        return func.HttpResponse(
            json.dumps({"status": "ok"}),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Fcfigures update failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
