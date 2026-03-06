"""
GET api/sow/list – returns all SOW documents for the SOW dashboard.
"""
import azure.functions as func
import logging
import json
import os
from decimal import Decimal

logger = logging.getLogger(__name__)


def _json_default(obj):
    """Make DB values JSON-serializable (Decimal -> float, date/datetime -> ISO string)."""
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("SOW list function processed a request.")
    if req.method != "GET":
        return func.HttpResponse("Method not allowed", status_code=405)
    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)

        if not os.environ.get('SQL_CONNECTION_STRING'):
            return func.HttpResponse(
                json.dumps({"sows": [], "error": "Database not configured"}),
                status_code=200,
                mimetype="application/json",
            )
        from shared.helpers import get_all_sows
        sows = get_all_sows()
        return func.HttpResponse(
            json.dumps({"sows": sows}, default=_json_default),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("SOW list failed")
        return func.HttpResponse(
            json.dumps({"error": str(e), "sows": []}),
            status_code=500,
            mimetype="application/json",
        )
