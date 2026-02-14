"""
Shared helper functions for Azure Functions
Provides utilities for SharePoint, SQL, authentication, and logging
"""
import os
import json
import logging
import tempfile
import base64
import pyodbc
import jwt
from datetime import datetime
from typing import Dict, Optional, Any
from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.client_credential import ClientCredential

logger = logging.getLogger(__name__)

# ============================================================================
# SharePoint Helpers
# ============================================================================

def _get_sharepoint_tenant(site_url: str) -> str:
    """Extract tenant identifier from SharePoint site URL for certificate auth."""
    tenant_name = os.environ.get('SHAREPOINT_TENANT_NAME')
    if tenant_name:
        return tenant_name
    tenant_id = os.environ.get('AZURE_TENANT_ID')
    if tenant_id:
        return tenant_id
    # Derive from hostname: invoiveautomation.sharepoint.com -> invoiveautomation.onmicrosoft.com
    try:
        from urllib.parse import urlparse
        host = urlparse(site_url).netloc
        if '.sharepoint.com' in host:
            subdomain = host.split('.sharepoint.com')[0]
            return f"{subdomain}.onmicrosoft.com"
    except Exception:
        pass
    raise ValueError(
        "Set SHAREPOINT_TENANT_NAME (e.g. invoiveautomation.onmicrosoft.com) or "
        "AZURE_TENANT_ID for SharePoint certificate authentication"
    )

def get_sharepoint_context() -> ClientContext:
    """
    Get authenticated SharePoint context.
    Uses certificate auth (SHAREPOINT_CERT_BASE64 + SHAREPOINT_CERT_THUMBPRINT) if set,
    otherwise falls back to client secret (ClientCredential) - note: client secret
    does NOT work with Azure AD app-only for SharePoint REST API; use certificate.
    """
    site_url = os.environ.get('SHAREPOINT_SITE_URL')
    client_id = os.environ.get('AZURE_CLIENT_ID')

    if not site_url or not client_id:
        raise ValueError("SHAREPOINT_SITE_URL and AZURE_CLIENT_ID are required")

    cert_base64 = os.environ.get('SHAREPOINT_CERT_BASE64')
    cert_thumbprint = os.environ.get('SHAREPOINT_CERT_THUMBPRINT')

    if cert_base64 and cert_thumbprint:
        # Certificate-based auth (required for Azure AD app-only with SharePoint REST API)
        tenant = _get_sharepoint_tenant(site_url)
        try:
            pem_bytes = base64.b64decode(cert_base64)
            pem_content = pem_bytes.decode('utf-8') if isinstance(pem_bytes, bytes) else str(pem_bytes)
        except Exception as e:
            raise ValueError(f"Invalid SHAREPOINT_CERT_BASE64: {e}") from e

        fd, cert_path = tempfile.mkstemp(suffix='.pem')
        try:
            os.write(fd, pem_content.encode('utf-8') if isinstance(pem_content, str) else pem_content)
            os.close(fd)
        except Exception:
            try:
                os.unlink(cert_path)
            except OSError:
                pass
            raise

        cert_settings = {
            'client_id': client_id,
            'thumbprint': cert_thumbprint.strip(),
            'cert_path': cert_path,
        }
        return ClientContext(site_url).with_client_certificate(tenant, **cert_settings)
    else:
        # Client secret (only works with deprecated SharePoint Add-in, not Azure AD app)
        client_secret = os.environ.get('AZURE_CLIENT_SECRET')
        if not client_secret:
            raise ValueError(
                "SharePoint certificate auth requires SHAREPOINT_CERT_BASE64 and "
                "SHAREPOINT_CERT_THUMBPRINT. Client secret (Azure AD app) does not work "
                "for SharePoint REST API app-only access."
            )
        credentials = ClientCredential(client_id, client_secret)
        return ClientContext(site_url).with_credentials(credentials)

def upload_file_to_sharepoint(file_content: bytes, file_name: str, folder_path: str = "Invoices") -> str:
    """
    Upload file to SharePoint document library.
    
    Args:
        file_content: File content as bytes
        file_name: Name of the file
        folder_path: Library name (e.g. 'Invoices' or 'JSON_Logs') or path like 'Invoices/2025/01_January'
    
    Returns:
        Server-relative URL of uploaded file
    """
    ctx = get_sharepoint_context()
    parts = [p for p in folder_path.replace("\\", "/").strip("/").split("/") if p.strip()]
    if not parts:
        parts = ["Invoices"]
    list_name = parts[0]
    root = ctx.web.lists.get_by_title(list_name).root_folder
    root.get().execute_query()
    target_folder = root
    for part in parts[1:]:
        try:
            target_folder = target_folder.folders.get_by_name(part).get().execute_query()
        except Exception:
            target_folder = target_folder.folders.add(part).execute_query()
    uploaded_file = target_folder.upload_file(file_name, file_content).execute_query()
    return uploaded_file.properties.get("ServerRelativeUrl") or uploaded_file.properties.get("serverRelativeUrl") or ""

def download_file_from_sharepoint(file_path: str) -> bytes:
    """Download file from SharePoint"""
    ctx = get_sharepoint_context()
    file = ctx.web.get_file_by_server_relative_url(file_path)
    file_content = file.read()
    return file_content

def save_json_to_sharepoint(json_data: Dict, file_name: str, folder_path: str = '/JSON_Logs') -> str:
    """Save JSON data to SharePoint JSON_Logs library"""
    now = datetime.now()
    year = now.strftime('%Y')
    month = now.strftime('%m_%B')
    full_folder_path = f'{folder_path}/{year}/{month}'
    
    json_content = json.dumps(json_data, indent=2).encode('utf-8')
    return upload_file_to_sharepoint(json_content, file_name, full_folder_path)

# ============================================================================
# SQL Database Helpers
# ============================================================================

def get_sql_connection():
    """Get SQL Database connection"""
    conn_str = os.environ.get('SQL_CONNECTION_STRING')
    if not conn_str:
        raise ValueError("SQL_CONNECTION_STRING not found in environment")
    return pyodbc.connect(conn_str)

def insert_invoice(invoice_id: str, vendor_id: str, doc_name: str, pdf_url: str, **kwargs) -> None:
    """Insert new invoice record into SQL Database"""
    conn = get_sql_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO invoices (
                invoice_id, vendor_id, doc_name, pdf_url, status, created_at, invoice_received_date
            ) VALUES (?, ?, ?, ?, 'Pending', GETUTCDATE(), GETUTCDATE())
        """, invoice_id, vendor_id, doc_name, pdf_url)
        
        conn.commit()
        logger.info(f"Inserted invoice {invoice_id} into SQL Database")
    finally:
        cursor.close()
        conn.close()

def update_invoice(invoice_id: str, **kwargs) -> None:
    """Update invoice record in SQL Database"""
    conn = get_sql_connection()
    cursor = conn.cursor()
    
    try:
        # Build dynamic UPDATE query based on provided kwargs
        if not kwargs:
            return
        
        set_clauses = []
        values = []
        
        for key, value in kwargs.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)
        
        set_clauses.append("last_updated_at = GETUTCDATE()")
        values.append(invoice_id)
        
        query = f"""
            UPDATE invoices
            SET {', '.join(set_clauses)}
            WHERE invoice_id = ?
        """
        
        cursor.execute(query, *values)
        conn.commit()
        logger.info(f"Updated invoice {invoice_id} in SQL Database")
    finally:
        cursor.close()
        conn.close()

def get_invoice(invoice_id: str) -> Optional[Dict]:
    """Get invoice record from SQL Database"""
    conn = get_sql_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM invoices WHERE invoice_id = ?", invoice_id)
        row = cursor.fetchone()
        
        if not row:
            return None
        
        columns = [column[0] for column in cursor.description]
        invoice = dict(zip(columns, row))
        
        # Convert datetime objects to ISO strings
        for key, value in invoice.items():
            if hasattr(value, 'isoformat'):
                invoice[key] = value.isoformat()
        
        return invoice
    finally:
        cursor.close()
        conn.close()

def get_invoices_by_vendor(vendor_id: str) -> list:
    """Get all invoices for a vendor"""
    conn = get_sql_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT * FROM invoices WHERE vendor_id = ? ORDER BY created_at DESC",
            vendor_id
        )
        
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        
        invoices = []
        for row in rows:
            invoice = dict(zip(columns, row))
            # Convert datetime objects
            for key, value in invoice.items():
                if hasattr(value, 'isoformat'):
                    invoice[key] = value.isoformat()
            invoices.append(invoice)
        
        return invoices
    finally:
        cursor.close()
        conn.close()

def get_all_invoices() -> list:
    """Get all invoices (for accounts team)"""
    conn = get_sql_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM invoices ORDER BY created_at DESC")
        
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        
        invoices = []
        for row in rows:
            invoice = dict(zip(columns, row))
            # Convert datetime objects
            for key, value in invoice.items():
                if hasattr(value, 'isoformat'):
                    invoice[key] = value.isoformat()
            invoices.append(invoice)
        
        return invoices
    finally:
        cursor.close()
        conn.close()

# ============================================================================
# Authentication Helpers
# ============================================================================

def extract_token_from_request(req) -> Optional[str]:
    """Extract JWT token from request Authorization header"""
    auth_header = req.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    return auth_header.split(' ')[1]

def decode_token(token: str) -> Dict:
    """Decode JWT token (without verification for now)"""
    try:
        # In production, verify the token signature
        decoded = jwt.decode(token, options={"verify_signature": False})
        return decoded
    except Exception as e:
        logger.error(f"Failed to decode token: {str(e)}")
        raise

def extract_vendor_id_from_token(token: str) -> str:
    """Extract vendor_id from JWT token"""
    decoded = decode_token(token)
    # Try different possible fields
    return (
        decoded.get('email') or
        decoded.get('upn') or
        decoded.get('preferred_username') or
        decoded.get('sub') or
        decoded.get('oid')
    )

def extract_user_id_from_token(token: str) -> str:
    """Extract user identifier from JWT token"""
    decoded = decode_token(token)
    return decoded.get('email') or decoded.get('upn') or decoded.get('preferred_username')

def check_manager_permission(token: str) -> bool:
    """Check if user has manager/approver role"""
    decoded = decode_token(token)
    roles = decoded.get('roles', [])
    # Check for manager role (configure in Azure AD app registration)
    return 'Invoice.Approver' in roles or 'Manager' in roles or 'Admin' in roles


def _row_to_dashboard(row: Dict) -> Dict:
    """Map SQL row to dashboard row format (invoice_uuid, approval_status, etc.)."""
    out = dict(row)
    if "invoice_id" in out and "invoice_uuid" not in out:
        out["invoice_uuid"] = str(out["invoice_id"])
    status = out.get("approval_status") or out.get("status") or "Pending"
    if status in ("To Start", "In Progress"):
        status = "Pending"
    if status == "Need Approval":
        status = "NEED APPROVAL"
    out["approval_status"] = status
    if "status" not in out or out["status"] is None:
        out["status"] = status
    if "orchestrator_summary" not in out or out["orchestrator_summary"] is None:
        out["orchestrator_summary"] = out.get("last_agent_text") or ""
    return out


def _dashboard_metrics(rows: list) -> Dict:
    """Compute dashboard metrics from rows."""
    total = len(rows)
    pending = sum(1 for r in rows if (r.get("approval_status") or r.get("status")) == "Pending")
    complete = sum(1 for r in rows if (r.get("approval_status") or r.get("status")) == "Complete")
    need_approval = sum(1 for r in rows if (r.get("approval_status") or r.get("status")) == "NEED APPROVAL")
    payment_initiated = sum(1 for r in rows if r.get("bill_pay_initiated_on"))
    total_amount = 0.0
    for r in rows:
        try:
            v = r.get("invoice_amount")
            if v is not None:
                total_amount += float(v)
        except (TypeError, ValueError):
            pass
    return {
        "total": total,
        "pending": pending,
        "complete": complete,
        "need_approval": need_approval,
        "payment_initiated": payment_initiated,
        "total_amount": round(total_amount, 2),
    }


def get_dashboard_payload(req) -> tuple:
    """
    Get dashboard data (rows + metrics) based on request token.
    Returns (list of dashboard rows, metrics dict).
    When SQL_CONNECTION_STRING is not set, returns empty rows and zero metrics.
    """
    if not os.environ.get('SQL_CONNECTION_STRING'):
        return [], {
            "total": 0, "pending": 0, "complete": 0, "need_approval": 0,
            "payment_initiated": 0, "total_amount": 0.0,
        }
    token = extract_token_from_request(req)
    is_manager = False
    vendor_id = None
    if token:
        try:
            is_manager = check_manager_permission(token)
            vendor_id = extract_vendor_id_from_token(token)
        except Exception:
            pass
    if is_manager or not vendor_id:
        rows = get_all_invoices()
    else:
        rows = get_invoices_by_vendor(vendor_id)
    dashboard_rows = [_row_to_dashboard(r) for r in rows]
    metrics = _dashboard_metrics(dashboard_rows)
    return dashboard_rows, metrics


# ============================================================================
# Document Intelligence Helpers
# ============================================================================

def analyze_invoice_bytes(file_content: bytes, filename: str = "invoice.pdf") -> Optional[Dict]:
    """
    Analyze invoice PDF/image bytes with Azure Document Intelligence.
    Returns same structure as Backend invoice_proc_az: full_text, extracted_text, status, etc.
    """
    import requests
    import time
    endpoint = os.environ.get('AZURE_DI_ENDPOINT', '').rstrip('/')
    key = os.environ.get('AZURE_DI_KEY')
    if not endpoint or not key:
        return None
    content_type = "application/pdf"
    if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        content_type = "image/jpeg" if 'jpg' in filename.lower() or 'jpeg' in filename.lower() else "image/png"
    headers = {"Ocp-Apim-Subscription-Key": key, "Content-Type": content_type}
    for path_prefix, api_version in [("formrecognizer", "2023-07-31"), ("documentintelligence", "2023-07-31")]:
        analyze_url = f"{endpoint}/{path_prefix}/documentModels/prebuilt-invoice:analyze?api-version={api_version}"
        try:
            resp = requests.post(analyze_url, headers=headers, data=file_content, timeout=60)
            if resp.status_code in (404, 400, 401):
                continue
            if resp.status_code not in (200, 202):
                continue
            operation_location = resp.headers.get("Operation-Location")
            if not operation_location:
                continue
            for _ in range(60):
                time.sleep(1)
                poll_resp = requests.get(operation_location, headers={"Ocp-Apim-Subscription-Key": key}, timeout=30)
                if poll_resp.status_code != 200:
                    continue
                result = poll_resp.json()
                if result.get("status") == "succeeded":
                    payload = result.get("analyzeResult") or result.get("result") or result
                    extracted_text = []
                    full_text_parts = []
                    for page in (payload.get("pages") or []):
                        for line in (page.get("lines") or []):
                            t = (line.get("content") or "").strip()
                            extracted_text.append(t)
                            full_text_parts.append(t)
                    full_text = "\n".join(full_text_parts) if full_text_parts else (payload.get("content") or "")
                    if not full_text and payload.get("content"):
                        full_text = payload["content"]
                        extracted_text = [s.strip() for s in full_text.split("\n") if s.strip()]
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "file_path": filename,
                        "extracted_text": extracted_text,
                        "full_text": full_text[:15000] if full_text else "",
                        "status": "success",
                        "source": "document_intelligence_rest",
                    }
                if result.get("status") == "failed":
                    break
        except Exception as e:
            logger.warning(f"DI {path_prefix} error: {e}")
            continue
    return None


def process_with_document_intelligence(pdf_url: str) -> Dict:
    """
    Process PDF with Azure Document Intelligence
    
    Args:
        pdf_url: URL or path to PDF file
    
    Returns:
        Extracted data dictionary
    """
    import requests
    
    endpoint = os.environ.get('AZURE_DI_ENDPOINT')
    key = os.environ.get('AZURE_DI_KEY')
    
    if not endpoint or not key:
        raise ValueError("Document Intelligence not configured")
    
    # Use Document Intelligence REST API
    # This is a simplified version - adjust based on your needs
    analyze_url = f"{endpoint}formrecognizer/documentModels/prebuilt-invoice:analyze?api-version=2023-07-31"
    
    headers = {
        'Ocp-Apim-Subscription-Key': key,
        'Content-Type': 'application/json'
    }
    
    # Start analysis
    body = {
        'urlSource': pdf_url  # Or use base64Source for direct file upload
    }
    
    response = requests.post(analyze_url, headers=headers, json=body)
    response.raise_for_status()
    
    # Get operation ID
    operation_id = response.headers.get('Operation-Location').split('/')[-1]
    
    # Poll for results (simplified - implement proper polling)
    result_url = f"{endpoint}formrecognizer/documentModels/prebuilt-invoice/analyzeResults/{operation_id}?api-version=2023-07-31"
    
    # Wait and get results (implement retry logic)
    import time
    time.sleep(5)  # Simplified - implement proper polling
    
    result_response = requests.get(result_url, headers={'Ocp-Apim-Subscription-Key': key})
    result_response.raise_for_status()
    
    result = result_response.json()
    
    # Extract fields from result
    extracted_data = {}
    if 'analyzeResult' in result and 'documents' in result['analyzeResult']:
        doc = result['analyzeResult']['documents'][0]
        fields = doc.get('fields', {})
        
        extracted_data = {
            'invoice_number': fields.get('InvoiceId', {}).get('value'),
            'invoice_amount': fields.get('InvoiceTotal', {}).get('value'),
            'invoice_date': fields.get('InvoiceDate', {}).get('value'),
            'vendor_name': fields.get('VendorName', {}).get('value'),
            'vendor_address': fields.get('VendorAddress', {}).get('value'),
            # Add more fields as needed
        }
    
    return extracted_data

# ============================================================================
# iGentic Orchestrator Helpers
# ============================================================================

def process_with_igentic(extracted_data: Dict, invoice_id: str, session_id: Optional[str] = None) -> Dict:
    """
    Process invoice with iGentic Orchestrator (same payload as Backend igentic_json_post).
    
    Args:
        extracted_data: Dict with doc_name, full_text, extracted_text, timestamp, status
        invoice_id: Invoice ID (used as sessionId)
        session_id: Optional session ID for workflow continuation
    
    Returns:
        Orchestration result
    """
    import requests
    endpoint = os.environ.get('IGENTIC_ENDPOINT')
    if not endpoint:
        return {"status": "error", "error": "IGENTIC_ENDPOINT not configured"}
    payload = {
        "request": "Process invoice",
        "userInput": json.dumps(extracted_data),
        "sessionId": session_id or invoice_id,
    }
    try:
        response = requests.post(endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=120)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.exception("iGentic call failed")
        return {"status": "error", "error": str(e)}

# ============================================================================
# Excel Helpers
# ============================================================================

def update_excel_file(invoice_id: str, invoice_data: Dict) -> None:
    """Update SharePoint Excel file with invoice data"""
    from openpyxl import load_workbook
    import io
    
    # Download Excel from SharePoint
    excel_path = '/Invoices/Invoice_Register_Master.xlsx'
    excel_content = download_file_from_sharepoint(excel_path)
    
    # Load workbook
    wb = load_workbook(io.BytesIO(excel_content))
    ws = wb.active
    
    # Find row with invoice_id or append new row
    row_found = False
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=False), start=2):
        if row[0].value == invoice_id:
            # Update existing row
            ws.cell(row=row_idx, column=2, value=invoice_data.get('vendor_id'))
            ws.cell(row=row_idx, column=3, value=invoice_data.get('invoice_number'))
            ws.cell(row=row_idx, column=4, value=invoice_data.get('invoice_amount'))
            ws.cell(row=row_idx, column=5, value=invoice_data.get('status'))
            # ... update other columns
            row_found = True
            break
    
    if not row_found:
        # Append new row
        ws.append([
            invoice_id,
            invoice_data.get('vendor_id'),
            invoice_data.get('invoice_number'),
            invoice_data.get('invoice_amount'),
            invoice_data.get('status'),
            invoice_data.get('approved_hours'),
            invoice_data.get('invoice_date'),
            invoice_data.get('pdf_url'),
            invoice_data.get('approved_by'),
            invoice_data.get('notes'),
            invoice_data.get('created_at'),
            invoice_data.get('last_updated_at'),
        ])
    
    # Save and upload back to SharePoint
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    ctx = get_sharepoint_context()
    file = ctx.web.get_file_by_server_relative_url(excel_path)
    file.save(output.read()).execute_query()

# ============================================================================
# Logging Helpers
# ============================================================================

def save_complete_log(invoice_id: str, extracted_data: Dict, orchestration_result: Dict, event_type: str = 'upload') -> None:
    """Save complete audit trail to SharePoint JSON_Logs"""
    try:
        # Get current SQL record
        sql_record = get_invoice(invoice_id)
        
        log_data = {
            'invoice_id': invoice_id,
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'extracted_data': extracted_data,
            'orchestration_result': orchestration_result,
            'database_record': sql_record
        }
        
        # Save to SharePoint
        file_name = f'invoice_{invoice_id}_{event_type}.json'
        save_json_to_sharepoint(log_data, file_name)
        
        logger.info(f"Saved JSON log for invoice {invoice_id}")
    except Exception as e:
        logger.error(f"Failed to save JSON log: {str(e)}")

def save_status_change_log(invoice_id: str, old_status: str, new_status: str, changed_by: str) -> None:
    """Save status change log"""
    log_data = {
        'invoice_id': invoice_id,
        'timestamp': datetime.utcnow().isoformat(),
        'event_type': 'status_change',
        'old_status': old_status,
        'new_status': new_status,
        'changed_by': changed_by,
        'database_record': get_invoice(invoice_id)
    }
    
    file_name = f'invoice_{invoice_id}_status_change.json'
    save_json_to_sharepoint(log_data, file_name)
