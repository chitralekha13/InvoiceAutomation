"""
Update invoice details (Save from dashboard): POST api/fcfigures/{id}/update.
Maps dashboard fields to SQL columns and updates the invoice. Syncs to Excel after update.
"""
import azure.functions as func
import logging
import json
import os

logger = logging.getLogger(__name__)

# Dashboard editable fields -> SQL column names
FIELD_MAP = {
    "invoice_number": "invoice_number",
    "consultancy_name": "vendor_name",
    "resource_name": "resource_name",
    "pay_period_start": "start_date",
    "pay_period_end": "end_date",
    "net_terms": "payment_terms",
    "vendor_hours": "invoice_hours",
    "approved_hours": "approved_hours",
    "pay_rate": "hourly_rate",
    "invoice_amount": "invoice_amount",
    "invoice_date": "invoice_date",
    "due_date": "due_date",
    "project_name": "project_name",
    "business_unit": "business_unit",
    "template": "template",
    "current_comments": "notes",
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
        from shared.helpers import (
            get_invoice,
            update_invoice,
            validate_timesheet_hours_with_igentic,
            _compare_hours_locally,
        )

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

        # When approved_hours is updated: send to iGentic for timesheet vs vendor_hours comparison
        if "approved_hours" in body:
            vendor_hrs = existing.get("invoice_hours") or existing.get("vendor_hours")
            try:
                timesheet = float(body["approved_hours"]) if body["approved_hours"] not in ("", None) else None
            except (TypeError, ValueError):
                timesheet = None
            if vendor_hrs is not None and timesheet is not None:
                cmp_result = validate_timesheet_hours_with_igentic(
                    float(vendor_hrs), timesheet, invoice_id
                )
                if not cmp_result:
                    cmp_result = _compare_hours_locally(float(vendor_hrs), timesheet)
                kwargs["approval_status"] = cmp_result.get("approval_status")
                kwargs["status"] = cmp_result.get("approval_status")

        if kwargs:
            # Skip columns that may not exist (template, addl_comments)
            allowed = {"invoice_number", "vendor_name", "resource_name", "start_date", "end_date",
                       "payment_terms", "invoice_hours", "approved_hours", "hourly_rate",
                       "invoice_amount", "invoice_date", "due_date", "project_name", "business_unit",
                       "notes", "template", "addl_comments", "approval_status", "status"}
            kwargs_clean = {k: v for k, v in kwargs.items() if k in allowed}
            if kwargs_clean:
                update_invoice(invoice_id, **kwargs_clean)
                # Sync to Excel
                try:
                    from shared.helpers import update_excel_file, get_invoice
                    inv = get_invoice(invoice_id)
                    if inv:
                        inv["invoice_id"] = invoice_id
                        update_excel_file(invoice_id, inv)
                        logger.info("Synced Excel after dashboard edit for %s", invoice_id)
                except Exception as e:
                    logger.warning("Excel sync after dashboard edit failed: %s", e)

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
