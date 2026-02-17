"""
Upload invoice: validate JWT (optional), upload PDF to SharePoint, insert SQL,
run Document Intelligence, run iGentic, update SQL, save JSON log.
"""
import azure.functions as func
import logging
import json
import os
import uuid
import io
import re

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
        if b'Content-Disposition' not in part or b'name="file"' not in part and b"name='file'" not in part:
            continue
        lines = part.split(b'\r\n')
        filename = None
        for line in lines:
            if line.lower().startswith(b'content-disposition:'):
                m = re.search(rb'filename="([^"]+)"', line, re.I)
                if m:
                    filename = m.group(1).decode('utf-8', errors='replace')
                break
        # Content starts after first blank line
        idx = part.find(b'\r\n\r\n')
        if idx == -1:
            idx = part.find(b'\n\n')
        if idx != -1:
            file_content = part[idx + 4:].rstrip(b'\r\n- ')
            if file_content and filename:
                return file_content, filename
    return None, None


def _extract_from_orchestrator(resp: dict) -> dict:
    """Extract fields from iGentic response for SQL update."""
    out = {}
    if not isinstance(resp, dict):
        return out
    # Display text / result
    raw = (resp.get("result") or resp.get("display_text") or resp.get("displayText") or "")
    if isinstance(raw, dict):
        raw = json.dumps(raw)
    text = (raw or "").lower()
    # Status
    if "complete" in text or "ready for payment" in text:
        out["approval_status"] = "Complete"
        out["status"] = "Complete"
    elif "need approval" in text or "manual review" in text:
        out["approval_status"] = "NEED APPROVAL"
        out["status"] = "NEED APPROVAL"
    else:
        out["approval_status"] = "Pending"
        out["status"] = "Pending"
    # Try to get structured data from agentResponses or similar
    for key in ("agentResponses", "agent_responses", "data"):
        val = resp.get(key)
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                pass
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    c = item.get("Content") or item.get("content") or ""
                    if isinstance(c, dict):
                        for k, v in c.items():
                            if v is not None and k in (
                                "invoice_number", "invoice_amount", "approved_hours", "vendor_name", "vendor_hours"
                            ):
                                out[k] = v
                        break
    return out


def main(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Upload function processed a request.")
    try:
        # Optional: validate JWT and get vendor_id
        vendor_id = "unknown"
        token = None
        auth = req.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token = auth.split(" ", 1)[1]
            try:
                import sys
                sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
                from shared.helpers import decode_token
                decoded = decode_token(token)
                vendor_id = (
                    decoded.get("email") or decoded.get("upn") or
                    decoded.get("preferred_username") or decoded.get("sub") or "unknown"
                )
            except Exception as e:
                logger.warning("Token decode failed, using vendor_id=unknown: %s", e)

        body = req.get_body()
        content_type = req.headers.get("Content-Type", "") or ""
        file_content, filename = _parse_multipart(body, content_type)
        if not file_content or not filename:
            return func.HttpResponse(
                json.dumps({"error": "No file provided. Send multipart/form-data with key 'file'."}),
                status_code=400,
                mimetype="application/json",
            )

        # Validate file type and size (e.g. PDF, max 10MB)
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
            upload_file_to_sharepoint,
            analyze_invoice_bytes,
            process_with_igentic,
            save_complete_log,
        )
        use_db = bool(os.environ.get('SQL_CONNECTION_STRING'))
        if use_db:
            from shared.helpers import insert_invoice, update_invoice, get_invoice, save_complete_log

        invoice_id = str(uuid.uuid4())
        safe_name = (filename or "invoice.pdf").replace(" ", "_")
        if not safe_name.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
            safe_name = safe_name + ".pdf"

        # 1) Upload to SharePoint (library Invoices, optional subpath 2025/01_January)
        now = __import__('datetime').datetime.now()
        folder_path = f"Invoices/{now.year}/{now.month:02d}_{now.strftime('%B')}"
        try:
            server_url = upload_file_to_sharepoint(file_content, safe_name, folder_path)
        except Exception as e:
            logger.exception("SharePoint upload failed")
            return func.HttpResponse(
                json.dumps({"error": f"SharePoint upload failed: {str(e)}"}),
                status_code=500,
                mimetype="application/json",
            )

        site_url = (os.environ.get("SHAREPOINT_SITE_URL") or "").rstrip("/")
        pdf_url = f"{site_url}{server_url}" if server_url and not server_url.startswith("http") else (server_url or "")

        # 2) Insert into SQL (optional - skipped if SQL_CONNECTION_STRING not set)
        if use_db:
            try:
                insert_invoice(invoice_id, vendor_id, safe_name, pdf_url)
            except Exception as e:
                logger.exception("SQL insert failed")
                return func.HttpResponse(
                    json.dumps({"error": f"Database insert failed: {str(e)}"}),
                    status_code=500,
                    mimetype="application/json",
                )

        # 3) Document Intelligence
        invoice_data = analyze_invoice_bytes(file_content, safe_name)
        if not invoice_data:
            # Document Intelligence not configured or failed; upload still succeeds
            invoice_data = {
                "full_text": "",
                "extracted_text": [],
                "structured_fields": {},
                "timestamp": __import__('datetime').datetime.now().isoformat(),
                "status": "no_di",
            }

        # 4) iGentic – userInput format: {"invoice_processing": {...}, "uploaded_file": "..."}
        user_input_for_igentic = {
            "invoice_processing": {
                "timestamp": invoice_data.get("timestamp"),
                "file_path": safe_name,
                "extracted_text": (invoice_data.get("extracted_text") or [])[:500],
                "full_text": (invoice_data.get("full_text") or "")[:15000],
                "structured_fields": invoice_data.get("structured_fields") or {},
                "status": invoice_data.get("status", "success"),
            },
            "uploaded_file": safe_name,
        }
        orchestration_response = process_with_igentic(user_input_for_igentic, invoice_id, invoice_id)

        # 5) Save JSON backup to SharePoint (always – Document Intelligence + iGentic result)
        try:
            save_complete_log(invoice_id, invoice_data, orchestration_response, "upload")
        except Exception as e:
            logger.warning("Save JSON log failed: %s", e)

        # 6) Update SQL from orchestrator (optional)
        if use_db:
            fields = _extract_from_orchestrator(orchestration_response)
            if fields:
                try:
                    update_invoice(invoice_id, **fields)
                except Exception as e:
                    logger.warning("SQL update after iGentic failed: %s", e)

            # 7) Optional: update Excel (if configured)
            try:
                from shared.helpers import update_excel_file
                inv = get_invoice(invoice_id)
                if inv:
                    update_excel_file(invoice_id, inv)
            except Exception as e:
                logger.warning("Excel update skipped: %s", e)

        return func.HttpResponse(
            json.dumps({
                "message": "File uploaded and processed successfully",
                "filename": safe_name,
                "invoice_uuid": invoice_id,
                "data": {"invoice_processing": invoice_data, "agent_orchestration": orchestration_response},
                "workflow": {
                    "sessionId": invoice_id,
                    "display_text": (orchestration_response.get("result") or orchestration_response.get("display_text") or ""),
                    "next_participant": None,
                },
            }),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Upload failed")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json",
        )
