"""
Delete invoice: DELETE api/invoices/{id}. Removes row from PostgreSQL.
"""
import azure.functions as func
import logging
import json
import os

logger = logging.getLogger(__name__)


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Invoice delete function processed a request.")
    if req.method != "DELETE":
        return func.HttpResponse("Method not allowed", status_code=405)

    invoice_id = (req.route_params or {}).get("id")
    if not invoice_id:
        return func.HttpResponse(
            json.dumps({"error": "Invoice id required"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)
        from shared.helpers import delete_invoice

        if not os.environ.get('SQL_CONNECTION_STRING'):
            return func.HttpResponse(
                json.dumps({"error": "Database not configured"}),
                status_code=503,
                mimetype="application/json",
            )

        deleted = delete_invoice(invoice_id)
        if not deleted:
            return func.HttpResponse(
                json.dumps({"error": "Invoice not found"}),
                status_code=404,
                mimetype="application/json",
            )
        return func.HttpResponse(
            json.dumps({"status": "ok", "message": "Invoice deleted"}),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Invoice delete failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
