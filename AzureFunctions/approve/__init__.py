"""
Approve invoice: validate manager permission, update SQL (status, approved_by), save JSON log, optional Excel sync.
"""
import azure.functions as func
import logging
import json
import os

logger = logging.getLogger(__name__)


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Approve function processed a request.")
    if req.method != "POST":
        return func.HttpResponse("Method not allowed", status_code=405)

    try:
        body = req.get_json() if req.get_body() else {}
    except ValueError:
        body = {}
    invoice_uuid = (body or {}).get("invoice_uuid") or (body or {}).get("invoice_id")
    if not invoice_uuid:
        return func.HttpResponse(
            json.dumps({"error": "invoice_uuid required"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)
        from shared.helpers import (
            extract_token_from_request,
            check_manager_permission,
            extract_user_id_from_token,
            get_invoice,
            update_invoice,
            save_status_change_log,
            update_excel_file,
        )

        token = extract_token_from_request(req)
        if token and not check_manager_permission(token):
            return func.HttpResponse(
                json.dumps({"error": "Forbidden: manager/approver access required"}),
                status_code=403,
                mimetype="application/json",
            )
        approved_by = (extract_user_id_from_token(token) if token else None) or "system"

        existing = get_invoice(invoice_uuid)
        if not existing:
            return func.HttpResponse(
                json.dumps({"error": "Invoice not found"}),
                status_code=404,
                mimetype="application/json",
            )

        old_status = existing.get("status") or existing.get("approval_status") or "Pending"
        new_status = (body or {}).get("status") or (body or {}).get("approval_status") or "Approved"
        notes = (body or {}).get("notes") or existing.get("notes")

        update_invoice(
            invoice_uuid,
            status=new_status,
            approval_status=new_status,
            approved_by=approved_by,
            notes=notes,
            last_modified_by=approved_by,
        )

        try:
            save_status_change_log(invoice_uuid, old_status, new_status, approved_by)
        except Exception as e:
            logger.warning("Save status change log failed: %s", e)

        try:
            inv = get_invoice(invoice_uuid)
            if inv:
                update_excel_file(invoice_uuid, inv)
        except Exception as e:
            logger.warning("Excel update skipped: %s", e)

        return func.HttpResponse(
            json.dumps({"success": True, "message": "Invoice approved", "invoice_uuid": invoice_uuid}),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Approve failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
