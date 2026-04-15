"""
Validation layer for approved hours: POST api/fcfigures_new/{id}.
Performs manual IF check comparing approved_hours vs invoice_hours.
Only calls iGentic (2nd call, same session) for payment details if hours match.
"""
import azure.functions as func
import logging
import json
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

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
    "comments": "comments",
    "addl_comments": "addl_comments",
    "employee_id": "employee_id",
}

def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Fcfigures_new validation function processed a request.")
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
        from datetime import timedelta
        from shared.helpers import (
            get_invoice,
            update_invoice,
            continue_igentic_session,
            _extract_payment_details_from_igentic_response,
            save_complete_log,
            _parse_net_terms_days,
            _parse_date_to_date,
            apply_manual_invoice_status_side_effects,
        )

        existing = get_invoice(invoice_id)
        if not existing:
            return func.HttpResponse(
                json.dumps({"error": "Invoice not found"}),
                status_code=404,
                mimetype="application/json",
            )

        kwargs = {}
        updated_fields = {}
        source = body.get("source", "unknown")
# Handle other fields from dashboard edit (due_date, invoice_amount, etc.)
        for dash_key, sql_col in FIELD_MAP.items():
            if dash_key in body and dash_key not in ('approved_hours', 'payment_done'):
                val = body[dash_key]
                if val is not None and val != "":
                    kwargs[sql_col] = val
                    logger.info("Updated %s: %s", sql_col, val)

        # When net terms change, recalculate due date = invoice received/created date + net terms days
        if "net_terms" in body:
            base_date = _parse_date_to_date(
                existing.get("invoice_received_date") or existing.get("created_at")
            )
            if base_date is None:
                from datetime import date
                base_date = date.today()
            net_terms_val = body.get("net_terms") or existing.get("payment_terms")
            days = _parse_net_terms_days(net_terms_val)
            if days is not None:
                new_due = base_date + timedelta(days=days)
                kwargs["due_date"] = new_due.isoformat()[:10]
                logger.info("Recalculated due_date to %s from net_terms=%s (base_date=%s, days=%s)",
                            kwargs["due_date"], net_terms_val, base_date, days)

        # approved_hours: empty body value clears DB column; non-empty runs hours vs invoice validation
        approved_hours = None
        if "approved_hours" in body:
            _raw_ah = body.get("approved_hours")
            if _raw_ah is None or str(_raw_ah).strip() == "":
                kwargs["approved_hours"] = None
            else:
                try:
                    approved_hours = float(_raw_ah)
                except (TypeError, ValueError):
                    approved_hours = None

        # Manual IF Check: Compare approved_hours vs invoice_hours
        if approved_hours is not None:
            try:
                invoice_hours = float(existing.get("invoice_hours") or 0)
                logger.info("Manual IF check: approved_hours=%s, invoice_hours=%s", approved_hours, invoice_hours)

                # Tolerance for hours matching
                tolerance = 0.5
                hours_match = abs(approved_hours - invoice_hours) < tolerance

                if hours_match:
                    # Hours match → Approved
                    logger.info("Hours match! Setting approval_status to Approved")
                    kwargs["approval_status"] = "Approved"
                    kwargs["status"] = "Approved"
                    kwargs["approved_hours"] = approved_hours

                    # Call iGentic (2nd call, same session) for payment details
                    try:
                        logger.info("Calling iGentic for payment details (2nd call, same session)")
                        ok_result = continue_igentic_session(
                            invoice_id,
                            "payment details",
                            request_label=f"The Approved hours is {approved_hours}. Get payment details",
                        )
                        logger.info("iGentic response for payment details: %s", ok_result)
                        payment_details = _extract_payment_details_from_igentic_response(ok_result)
                        if payment_details:
                            kwargs["payment_details"] = payment_details
                            logger.info("Payment details extracted and saved")
                    except Exception as igentic_err:
                        logger.warning("iGentic payment details call failed; continuing without payment details: %s", igentic_err)

                else:
                    # Hours don't match → Need Approval
                    logger.info("Hours don't match! Setting approval_status to Need Approval")
                    kwargs["approval_status"] = "Need Approval"
                    kwargs["status"] = "Need Approval"
                    kwargs["approved_hours"] = approved_hours

            except Exception as e:
                logger.error("Error during manual IF check: %s", e)
                kwargs["approval_status"] = "Need Approval"
                kwargs["status"] = "Need Approval"

        # Always apply explicit dashboard status after hours logic (use `if`, not `elif`).
        # Otherwise a body that still contains approved_hours (e.g. "", 0) can skip this branch
        # and lock the row in Need Approval when the user selects Pending.
        if "approval_status" in body:
            raw_st = body.get("approval_status")
            if raw_st is not None and str(raw_st).strip() != "":
                apply_manual_invoice_status_side_effects(
                    invoice_id,
                    existing,
                    str(raw_st).strip(),
                    kwargs,
                )
                logger.info("Manual approval_status from dashboard: %s", raw_st)

        if body.get("payment_done"):
            kwargs["bill_pay_initiated_on"] = datetime.now(timezone.utc)
            # Once payment is initiated, reflect this in status
            kwargs["status"] = "Payment Initiated"
            kwargs["approval_status"] = "Payment Initiated"
            
        if kwargs:
            # Allowed columns for update
            allowed = {
                "invoice_number",
                "vendor_name",
                "resource_name",
                "start_date",
                "end_date",
                "payment_terms",
                "invoice_hours",
                "approved_hours",
                "hourly_rate",
                "invoice_amount",
                "invoice_date",
                "due_date",
                "project_name",
                "business_unit",
                "notes",
                "comments",
                "template",
                "addl_comments",
                "approval_status",
                "status",
                "payment_details",
                "bill_pay_initiated_on",
                "employee_id",
            }
            kwargs_clean = {k: v for k, v in kwargs.items() if k in allowed}
            if kwargs_clean:
                updated_fields = kwargs_clean
                update_invoice(invoice_id, **kwargs_clean)
                logger.info("Invoice updated with: %s", kwargs_clean)
                # employee_id is not mirrored to SOW from invoices; SOW is maintained manually.

                # Sync to Excel
                try:
                    from shared.helpers import update_excel_file, get_invoice
                    inv = get_invoice(invoice_id)
                    if inv:
                        inv["invoice_id"] = invoice_id
                        update_excel_file(invoice_id, inv)
                        logger.info("Synced Excel after fcfigures_new validation for %s", invoice_id)
                except Exception as e:
                    logger.warning("Excel sync after fcfigures_new validation failed: %s", e)

        # Persist a JSON log of validation
        if updated_fields:
            try:
                save_complete_log(
                    invoice_id,
                    extracted_data={"updated_fields": updated_fields, "request_body": body},
                    orchestration_result={"source": f"fcfigures_new_{source}"},
                    event_type="hours_validation",
                )
            except Exception as e:
                logger.warning("Validation JSON log failed: %s", e)

        payload = {"status": "ok"}
        try:
            inv = get_invoice(invoice_id)
            if inv:
                inv["invoice_id"] = invoice_id
                payload["invoice"] = inv
                payload["approval_status"] = inv.get("approval_status")
                payload["payment_details"] = inv.get("payment_details")
        except Exception as e:
            logger.warning("Could not load updated invoice for response: %s", e)

        return func.HttpResponse(
            json.dumps(payload, default=str),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Fcfigures_new validation failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
    
    
