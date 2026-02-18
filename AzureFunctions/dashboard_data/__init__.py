"""
Dashboard data: same as get_invoices, route api/dashboard/data for compatibility with existing dashboard HTML.
"""
import azure.functions as func
import logging
import json
import os
from decimal import Decimal

logger = logging.getLogger(__name__)


def _json_default(obj):
    """Handle Decimal and other non-JSON types from PostgreSQL."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Dashboard data function processed a request.")
    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)
        from shared.helpers import get_dashboard_payload, get_sharepoint_excel_url

        dashboard_rows, metrics = get_dashboard_payload(req)
        excel_url = get_sharepoint_excel_url()
        payload = {
            "status": "ok",
            "metrics": metrics,
            "rows": dashboard_rows,
        }
        if excel_url:
            payload["excelUrl"] = excel_url
        return func.HttpResponse(
            json.dumps(payload, default=_json_default),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Dashboard data failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
