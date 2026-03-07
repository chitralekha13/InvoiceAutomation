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
        from shared.helpers import (
            get_invoice,
            update_invoice,
            continue_igentic_session,
            _extract_payment_details_from_igentic_response,
            save_complete_log,
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

        # Extract approved_hours from request
        approved_hours = body.get("approved_hours")
        if approved_hours is not None:
            try:
                approved_hours = float(approved_hours)
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
                "template",
                "addl_comments",
                "approval_status",
                "status",
                "payment_details",
                "bill_pay_initiated_on",
            }
            kwargs_clean = {k: v for k, v in kwargs.items() if k in allowed}
            if kwargs_clean:
                updated_fields = kwargs_clean
                update_invoice(invoice_id, **kwargs_clean)
                logger.info("Invoice updated with: %s", kwargs_clean)

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

        # Return updated invoice
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
        logger.exception("Fcfigures_new validation failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
    
    
