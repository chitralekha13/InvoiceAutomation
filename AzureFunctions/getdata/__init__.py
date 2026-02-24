"""
Vendor portal "View documents": list vendor's invoices, optional download.
Single backend - replaces the old api/getdata.
"""
import azure.functions as func
import logging
import json
import os

logger = logging.getLogger(__name__)


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Getdata function processed a request.")
    if req.method != "POST":
        return func.HttpResponse("Method not allowed", status_code=405)

    try:
        body = req.get_json() if req.get_body() else {}
    except ValueError:
        body = {}

    #action = (body or {}).get("action") or "list"
    action = (body or {}).get("action")
    document_id = (body or {}).get("documentId")
    vendor_id   = (body or {}).get("org")

    try:
        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)

        use_db = bool(os.environ.get('SQL_CONNECTION_STRING'))
        if not use_db:
            # No database: return empty list for list, not found for download
            if action == "list":
                return func.HttpResponse(
                    json.dumps({"documents": []}),
                    status_code=200,
                    mimetype="application/json",
                )
            if action == "download":
                return func.HttpResponse(
                    json.dumps({"error": "Document not found (database not configured)"}),
                    status_code=404,
                    mimetype="application/json",
                )

        from shared.helpers import (
            extract_token_from_request,
            extract_vendor_name_from_token,
            get_invoices_by_vendor,
            get_invoice,
            get_sharepoint_context,
        )

        # Resolve vendor_id from token or body
        token = body.get("accessToken")
        #extract_token_from_request(req) or (body or {}).get("accessToken")
        

        #if token:
        #    try:
        #       vendor_id = extract_vendor_name_from_token(token)
        #    except Exception:
        #       pass
        #if vendor_id == "unknown" and (body or {}).get("userEmail"):
        #   vendor_id = (body or {}).get("userEmail")

        if action == "list":
            rows = get_invoices_by_vendor(vendor_id)
            # Shape expected by retrieve.html: { documents: [ { id, name, size, uploadDate } ] }
            documents = []
            for r in rows:
                documents.append({
                    "id": r.get("invoice_id") or r.get("invoice_uuid"),
                    "name": r.get("doc_name") or "document",
                    "uploadDate": r.get("created_at") or r.get("invoice_received_date") or "",
                })
            return func.HttpResponse(
                json.dumps({"documents": documents}),
                status_code=200,
                mimetype="application/json",
            )

        if action == "download" and document_id:
            inv = get_invoice(document_id)
            if not inv:
                return func.HttpResponse(
                    json.dumps({"error": "Document not found"}),
                    status_code=404,
                    mimetype="application/json",
                )
            # Return PDF URL so frontend can open or download
            pdf_url = inv.get("pdf_url")
            if not pdf_url:
                return func.HttpResponse(
                    json.dumps({"error": "No file URL"}),
                    status_code=404,
                    mimetype="application/json",
                )
            return func.HttpResponse(
                json.dumps({"url": pdf_url, "name": inv.get("doc_name") or "document.pdf"}),
                status_code=200,
                mimetype="application/json",
            )
        
        if action == "stream" and document_id:
            inv = get_invoice(document_id)
            sharepoint_url = inv.get("pdf_url")
            file_path = "/" + sharepoint_url.split("/", 3)[-1] if sharepoint_url.startswith("http") else sharepoint_url

            try:
                ctx = get_sharepoint_context()
                file_content = ctx.web.get_file_by_server_relative_url(file_path).read()
            except Exception as e:
                logger.exception("SharePoint download failed")
                return func.HttpResponse(
                    json.dumps({"error": f"Failed to fetch file: {str(e)}"}),
                    status_code=502,
                    mimetype="application/json"
                )

            file_name = inv.get("doc_name") or "document.pdf"

            return func.HttpResponse(
                body=file_content,
                status_code=200,
                headers={
                    "Content-Type":                "application/pdf",
                    "Content-Disposition":         f'inline; filename="{file_name}"',
                    "Access-Control-Allow-Origin": "*",
                }
            )

        return func.HttpResponse(
            json.dumps({"error": "Unknown action"}),
            status_code=400,
            mimetype="application/json",
        )

    except Exception as e:
        logger.exception("Getdata failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
