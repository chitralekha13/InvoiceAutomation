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
            continue_igentic_session,
            _parse_continuation_response_for_approval,
            _extract_payment_details_from_igentic_response,
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
                # Coerce approved_hours to number for DB
                if dash_key == "approved_hours" and val is not None:
                    try:
                        val = float(val)
                    except (TypeError, ValueError):
                        pass
                kwargs[sql_col] = val

        # When approved_hours is updated: validation and payment details all happen on iGentic (same session).
        # We only send the hours; iGentic validates (match vs invoice hours) and returns payment details if matched.
        # If iGentic fails (e.g. endpoint down), we still save approved_hours to the DB.
        if "approved_hours" in body:
            try:
                timesheet = float(body["approved_hours"]) if body["approved_hours"] not in ("", None) else None
            except (TypeError, ValueError):
                timesheet = None
            if timesheet is not None:
                try:
                    result = continue_igentic_session(
                        invoice_id,
                        f"approved hours is {int(timesheet) if timesheet == int(timesheet) else timesheet}",
                        request_label="Validate approved hours",
                    )
                    cmp_result = _parse_continuation_response_for_approval(result)
                    if cmp_result:
                        kwargs["approval_status"] = cmp_result.get("approval_status")
                        kwargs["status"] = cmp_result.get("approval_status")
                        if cmp_result.get("payment_details") is not None:
                            kwargs["payment_details"] = cmp_result.get("payment_details")
                        elif cmp_result.get("approval_status") in ("Approved", "Complete", "Ready for Payment", "ready for payment"):
                            ok_result = continue_igentic_session(
                                invoice_id,
                                "payment details",
                                request_label="Get payment details",
                            )
                            payment_details = _extract_payment_details_from_igentic_response(ok_result)
                            if payment_details:
                                kwargs["payment_details"] = payment_details
                except Exception as igentic_err:
                    logger.warning("iGentic approved-hours validation failed; saving approved_hours only: %s", igentic_err)

        if kwargs:
            # Skip columns that may not exist (template, addl_comments)
            allowed = {"invoice_number", "vendor_name", "resource_name", "start_date", "end_date",
                       "payment_terms", "invoice_hours", "approved_hours", "hourly_rate",
                       "invoice_amount", "invoice_date", "due_date", "project_name", "business_unit",
                       "notes", "template", "addl_comments", "approval_status", "status", "payment_details"}
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

        # Return updated invoice so dashboard can show new approval_status, status, payment_details
        payload = {"status": "ok"}
        try:
            inv = get_invoice(invoice_id)
            if inv:
                inv["invoice_id"] = invoice_id
                payload["invoice"] = inv
        except Exception as e:
            logger.warning("Could not load updated invoice for response: %s", e)

        return func.HttpResponse(
            json.dumps(payload, default=str),
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
