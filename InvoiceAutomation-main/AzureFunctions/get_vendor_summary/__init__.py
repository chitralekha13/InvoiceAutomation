import azure.functions as func
import json
import logging
import os
from decimal import Decimal

logger = logging.getLogger(__name__)

def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Get vendor summary function processed a request")
    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)
        from shared.helpers import get_vendor_summary, get_vendor_resources
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
        status_filter = req.params.get("status")
        due_by = req.params.get("due_by")
        month = req.params.get("month")
        
        logger.info("get_vendor_summary called with vendor_name: %s, resources: %s, status: %s, due_by: %s, month: %s", 
                    vendor_name, resources, status_filter, due_by, month)
        summary = get_vendor_summary(vendor_name, resources, status_filter, due_by, month)
        logger.info("get_vendor_summary result: %s", summary)
        resources = get_vendor_resources(vendor_name)
        logger.info("get_vendor_resources result: %s", resources)
        return func.HttpResponse(
            json.dumps({"summary": summary, "resources": resources}, default=_json_default),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )
    except Exception as e:
        logger.exception("Get vendor summary failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )