import azure.functions as func
import json
import logging
import os
from decimal import Decimal

logger = logging.getLogger(__name__)


def _norm_status_key(value) -> str:
    if value is None:
        return ""
    return str(value).lower().replace(" ", "_").strip()


def _row_matches_consultancy_filters(row: dict, status: str, due_by: str, month: str) -> bool:
    """Apply optional status / due_by / month filters (same semantics as accounts dashboard)."""
    st = (status or "").strip().lower()
    if st and st != "all":
        if st == "payment_initiated":
            if not row.get("bill_pay_initiated_on"):
                return False
        else:
            rk = _norm_status_key(row.get("approval_status") or row.get("status") or "")
            if rk != st:
                return False
    if due_by:
        d = row.get("due_date") or row.get("dueDate")
        if not d:
            return False
        ds = str(d)[:10]
        db = str(due_by)[:10]
        if ds > db:
            return False
    if month:
        ca = row.get("created_at") or row.get("Created_at")
        if not ca:
            return False
        if str(ca)[:7] != str(month)[:7]:
            return False
    return True


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Get consultancy invoices function processed a request")
    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)
        from shared.helpers import get_invoices_by_vendor_and_resources

        vendor_name = req.params.get("vendor_name")
        if not vendor_name:
            return func.HttpResponse(
                json.dumps({"error": "vendor_name is required"}),
                status_code=400,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*"}
            )

        resources_param = req.params.get("resources")
        resources = resources_param.split(",") if resources_param else []

        status = req.params.get("status") or ""
        due_by = req.params.get("due_by") or ""
        month = req.params.get("month") or ""

        invoices = get_invoices_by_vendor_and_resources(vendor_name, resources)
        if status or due_by or month:
            invoices = [r for r in invoices if _row_matches_consultancy_filters(r, status, due_by, month)]
        return func.HttpResponse(
            json.dumps({"rows": invoices}, default=_json_default),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )
    except Exception as e:
        logger.exception("Get consultancy invoices failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )