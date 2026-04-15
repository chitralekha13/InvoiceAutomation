"""
Update invoice details (Save from dashboard): POST api/fcfigures/{id}/update.
Maps dashboard fields to SQL columns and updates the invoice. Syncs to Excel after update.
"""
import azure.functions as func
import logging
import json
import os
from datetime import datetime, timezone

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
    "comments": "comments",
    "addl_comments": "addl_comments",
    "employee_id": "employee_id",
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
        from datetime import timedelta
        from shared.helpers import (
            get_invoice,
            update_invoice,
            continue_igentic_session,
            _parse_continuation_response_for_approval,
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

        # Build update kwargs: only fields that are in body and map to SQL columns
        kwargs = {}
        updated_fields = {}
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

        # When approved_hours is updated: validation and payment details all happen on iGentic (same session).
        timesheet = None
        if "approved_hours" in body:
            try:
                timesheet = float(body["approved_hours"]) if body["approved_hours"] not in ("", None) else None
                logger.info("Parsed approved_hours for iGentic validation: %s", timesheet)
            except (TypeError, ValueError):
                timesheet = None

        if timesheet is not None:
            try:
                result = continue_igentic_session(
                    invoice_id,
                    f"Timesheet hours = {int(timesheet) if timesheet == int(timesheet) else timesheet}",
                    request_label="Validate approved hours",
                )
                logger.info("iGentic response for approved hours validation: %s", result)
                cmp_result = _parse_continuation_response_for_approval(result)
                logger.info("iGentic comparison result for approved hours validation: %s", cmp_result)
                if cmp_result:
                    approval_status = cmp_result.get("approval_status") or "Pending"
                    hours_match = cmp_result.get("hours_match")
                    logger.info("iGentic approval status: %s, hours match: %s", approval_status, hours_match)
                    if approval_status in ("Approved", "Complete", "Ready for Payment", "ready for payment") or hours_match:
                        kwargs["approval_status"] = approval_status
                        kwargs["status"] = approval_status
                        if cmp_result.get("payment_details") is not None:
                            kwargs["payment_details"] = cmp_result.get("payment_details")
                        else:
                            ok_result = continue_igentic_session(
                                invoice_id,
                                "payment details",
                                request_label="Get payment details",
                            )
                            payment_details = _extract_payment_details_from_igentic_response(ok_result)
                            if payment_details:
                                kwargs["payment_details"] = payment_details
                    else:
                        logger.info("iGentic did not approve hours; approval_status: %s, hours_match: %s", approval_status, hours_match)
                        kwargs["approval_status"] = "Need Approval"
                        kwargs["status"] = "Need Approval"
                else:
                    logger.info("iGentic did not return a valid comparison result; setting Need Approval")
                    kwargs["approval_status"] = "Need Approval"
                    kwargs["status"] = "Need Approval"
            except Exception as igentic_err:
                logger.warning("iGentic approved-hours validation failed; saving approved_hours only: %s", igentic_err)

        elif "approval_status" in body:
            raw_st = body.get("approval_status")
            if raw_st is not None and str(raw_st).strip() != "":
                apply_manual_invoice_status_side_effects(
                    invoice_id,
                    existing,
                    str(raw_st).strip(),
                    kwargs,
                )
                logger.info("Manual approval_status from dashboard (fcfigures): %s", raw_st)

        # Payment Done from View Payment modal: persist so row stays green forever
        if body.get("payment_done"):
            kwargs["bill_pay_initiated_on"] = datetime.now(timezone.utc)
            # Once payment is initiated, reflect this in status
            kwargs["status"] = "Payment Initiated"
            kwargs["approval_status"] = "Payment Initiated"

        if kwargs:
            # Skip columns that may not exist (template, addl_comments)
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
                # employee_id is not mirrored to SOW from invoices; SOW is maintained manually.
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

        # Persist a JSON log of dashboard-driven updates (if anything actually changed)
        if updated_fields:
            try:
                save_complete_log(
                    invoice_id,
                    extracted_data={"updated_fields": updated_fields, "request_body": body},
                    orchestration_result={"source": "fcfigures_update"},
                    event_type="dashboard_update",
                )
            except Exception as e:
                logger.warning("Dashboard JSON log failed: %s", e)

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
