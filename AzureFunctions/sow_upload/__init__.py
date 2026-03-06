"""
Upload SOW: multipart file -> Document Intelligence -> iGentic (Process SOW) -> parse fields -> save to sow_documents.
"""
import azure.functions as func
import logging
import json
import os
import re
import uuid

logger = logging.getLogger(__name__)


def _parse_multipart(body: bytes, content_type: str):
    """Parse multipart/form-data and return (file_content, filename) or (None, None)."""
    if not body or "multipart/form-data" not in content_type.lower():
        return None, None
    match = re.search(r'boundary=([^;\s]+)', content_type, re.I)
    boundary = (match.group(1).strip().strip('"') if match else "").encode()
    if not boundary:
        return None, None
    parts = body.split(b"--" + boundary)
    for part in parts:
        if b'Content-Disposition' not in part or (b'name="file"' not in part and b"name='file'" not in part):
            continue
        lines = part.split(b'\r\n')
        filename = None
        for line in lines:
            if line.lower().startswith(b'content-disposition:'):
                m = re.search(rb'filename="([^"]+)"', line, re.I)
                if m:
                    filename = m.group(1).decode('utf-8', errors='replace')
                break
        idx = part.find(b'\r\n\r\n')
        if idx == -1:
            idx = part.find(b'\n\n')
        if idx != -1:
            file_content = part[idx + 4:].rstrip(b'\r\n- ')
            if file_content and filename:
                return file_content, filename
    return None, None


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("SOW upload function processed a request.")
    if req.method != "POST":
        return func.HttpResponse(
            json.dumps({"error": "Method not allowed. Use POST with multipart/form-data and key 'file'."}),
            status_code=405,
            mimetype="application/json",
        )
    try:
        body = req.get_body()
        content_type = req.headers.get("Content-Type") or ""
        file_content, filename = _parse_multipart(body, content_type)
        if not file_content or not filename:
            return func.HttpResponse(
                json.dumps({"error": "No file provided. Send multipart/form-data with key 'file'."}),
                status_code=400,
                mimetype="application/json",
            )

        ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ("pdf", "png", "jpg", "jpeg"):
            return func.HttpResponse(
                json.dumps({"error": "Invalid file type. Allowed: PDF, PNG, JPG."}),
                status_code=400,
                mimetype="application/json",
            )
        if len(file_content) > 10 * 1024 * 1024:
            return func.HttpResponse(
                json.dumps({"error": "File too large (max 10MB)."}),
                status_code=400,
                mimetype="application/json",
            )

        sys_path = os.path.join(os.path.dirname(__file__), '..')
        if sys_path not in __import__('sys').path:
            __import__('sys').path.insert(0, sys_path)
        from shared.helpers import (
            analyze_invoice_bytes,
            process_sow_with_igentic,
            _extract_sow_fields_from_igentic_response,
            insert_sow,
            upload_file_to_sharepoint,
        )

        sow_id = str(uuid.uuid4())
        safe_name = (filename or "sow.pdf").replace(" ", "_")
        if not safe_name.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
            safe_name = safe_name + ".pdf"

        # 1) Document Intelligence (extract text; same as invoice flow)
        doc_data = analyze_invoice_bytes(file_content, safe_name)
        if not doc_data:
            doc_data = {
                "full_text": "",
                "extracted_text": [],
                "timestamp": __import__('datetime').datetime.now().isoformat(),
                "status": "no_di",
            }

        full_text = (doc_data.get("full_text") or "")[:15000]
        extracted_text = (doc_data.get("extracted_text") or [])[:500]
        user_input_for_igentic = {
            "sow_processing": {
                "timestamp": doc_data.get("timestamp"),
                "file_path": safe_name,
                "extracted_text": extracted_text,
                "full_text": full_text,
                "status": doc_data.get("status", "success"),
            },
            "uploaded_file": safe_name,
        }

        # 2) iGentic – Process SOW
        orchestration_response = process_sow_with_igentic(user_input_for_igentic, sow_id)
        if orchestration_response.get("status") == "error":
            return func.HttpResponse(
                json.dumps({
                    "error": "SOW processing failed",
                    "detail": orchestration_response.get("error", "iGentic error"),
                }),
                status_code=502,
                mimetype="application/json",
            )

        # 3) Extract SOW fields from agent response
        sow_fields = _extract_sow_fields_from_igentic_response(orchestration_response)
        logger.info("Extracted SOW fields from iGentic: %s", sow_fields)

        # 4) Optional: upload file to SharePoint (Invoices/SOWs subfolder; SOWs list may not exist)
        pdf_url = None
        try:
            folder_path = "Invoices/SOWs"
            server_url = upload_file_to_sharepoint(file_content, safe_name, folder_path)
            site_url = (os.environ.get("SHAREPOINT_SITE_URL") or "").rstrip("/")
            if site_url and server_url and not server_url.startswith("http"):
                pdf_url = f"{site_url.split('/sites/')[0]}{server_url}"
            else:
                pdf_url = server_url or None
        except Exception as e:
            logger.warning("SharePoint upload for SOW skipped: %s", e)

        # 5) Save to database
        use_db = bool(os.environ.get('SQL_CONNECTION_STRING'))
        if use_db:
            try:
                insert_sow(
                    sow_id=sow_id,
                    doc_name=safe_name,
                    pdf_url=pdf_url,
                    resource_name=sow_fields.get("resource_name"),
                    consultancy_name=sow_fields.get("consultancy_name"),
                    sow_start_date=sow_fields.get("sow_start_date"),
                    sow_end_date=sow_fields.get("sow_end_date"),
                    net_terms=sow_fields.get("net_terms"),
                    max_sow_hours=sow_fields.get("max_sow_hours"),
                    rate_per_hour=sow_fields.get("rate_per_hour"),
                    project_role=sow_fields.get("project_role"),
                    sow_project_duration=sow_fields.get("sow_project_duration"),
                )
            except Exception as e:
                logger.exception("SOW insert failed: %s", e)
                return func.HttpResponse(
                    json.dumps({"error": "Database insert failed", "detail": str(e)}),
                    status_code=500,
                    mimetype="application/json",
                )
        else:
            return func.HttpResponse(
                json.dumps({"error": "Database not configured (SQL_CONNECTION_STRING)."}),
                status_code=503,
                mimetype="application/json",
            )

        return func.HttpResponse(
            json.dumps({
                "message": "SOW uploaded and processed successfully",
                "sow_id": sow_id,
                "filename": safe_name,
                "pdf_url": pdf_url,
                "data": sow_fields,
            }),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("SOW upload failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
