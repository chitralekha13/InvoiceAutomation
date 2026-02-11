"""
Get invoices: for accounts team returns all invoices; for vendors returns only their invoices.
Returns data in dashboard format: { status, metrics, rows }.
"""
import azure.functions as func
import logging
import json
import os

logger = logging.getLogger(__name__)


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Get invoices function processed a request.")
    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)
        from shared.helpers import get_dashboard_payload

        dashboard_rows, metrics = get_dashboard_payload(req)
        return func.HttpResponse(
            json.dumps({
                "status": "ok",
                "metrics": metrics,
                "rows": dashboard_rows,
            }),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Get invoices failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
