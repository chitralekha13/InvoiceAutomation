# Invoice Automation — Technical Architecture

**Target audience:** Senior engineers, architects, DevOps. Assumes familiarity with Azure, PostgreSQL, REST APIs, and JWT.

---

## 1. High-Level Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌──────────────────┐
│ Vendor Portal   │────▶│ Azure Functions  │────▶│ Azure Document  │     │ iGentic         │     │ SharePoint       │
│ (Static Web App)│     │ (Backend API)    │────▶│ Intelligence    │     │ (AI Orchestrator│     │ (Files, Excel)   │
│                 │     │                  │     │                 │────▶│  External API)  │────▶│                  │
└─────────────────┘     └────────┬─────────┘     └─────────────────┘     └─────────────────┘     └────────┬─────────┘
                                 │                                                                         │
                                 │                                                                         │
                                 ▼                                                                         │
                        ┌─────────────────┐                                                               │
                        │ PostgreSQL      │◀─────────────────────────────────────────────────────────────┘
                        │ (Azure DB)      │   (Excel register sync, JSON logs)
                        └─────────────────┘

┌─────────────────┐     ┌──────────────────┐
│ Accounts        │────▶│ Azure Functions  │────▶ PostgreSQL (read/write)
│ Dashboard       │     │ dashboard_data   │────▶ SharePoint Excel URL
│ (Static Web App)│     │ fcfigures_update │────▶ iGentic (on approved_hours)
│                 │     │ invoice_delete   │
└─────────────────┘     └──────────────────┘
```

**Data flow (upload):** Upload → SharePoint PDF → Document Intelligence (OCR) → iGentic (extraction/validation) → PostgreSQL + SharePoint Excel + JSON logs.

---

## 2. Folder Structure

| Folder | Purpose | Deploy Target |
|--------|---------|---------------|
| `frontend1/` | Vendor portal: login (MSAL), upload, retrieve documents | Azure Static Web App |
| `accountsdashboard/` | Accounts dashboard: metrics, table, edit, delete, View Payment | Azure Static Web App |
| `AzureFunctions/` | Backend API (HTTP-triggered Python functions) | Azure Functions (Consumption/Premium) |
| `AzureFunctions/shared/` | Shared helpers: SharePoint, PostgreSQL, DI, iGentic, Excel | Packaged with Functions |
| `AzureFunctions/migrations/` | SQL migrations for schema changes | Run manually on DB |
| `.github/workflows/` | CI/CD: Functions deploy, Static Web App deploy | GitHub Actions |

---

## 3. Azure Functions — API Endpoints

| HTTP | Route | Function | Purpose |
|------|-------|----------|---------|
| POST | `api/upload` | `upload` | Receive multipart file, full pipeline (SharePoint, DI, iGentic, SQL, Excel) |
| POST | `api/getdata` | `getdata` | Vendor portal: list vendor's invoices or get PDF download URL |
| GET | `api/dashboard/data` | `dashboard_data` | Accounts: rows + metrics + Excel URL (same as get_invoices) |
| GET | `api/invoices/all` | `get_invoices` | Same payload as dashboard_data (alternative route) |
| POST | `api/fcfigures/{id}/update` | `fcfigures_update` | Update invoice fields; when approved_hours changes, calls iGentic |
| DELETE | `api/invoices/{id}` | `invoice_delete` | Delete invoice from PostgreSQL |
| POST | `api/approve` | `approve` | Manager-only: set status/approval_status, sync Excel, log status change |

---

## 4. Function-by-Function Detail

### 4.1 `upload` (POST `api/upload`)

**Purpose:** Full invoice ingestion pipeline.

**Flow:**
1. Parse multipart/form-data (key `file`), validate type (PDF/PNG/JPG) and size (≤10MB).
2. Decode JWT (optional) for `vendor_id` (email/upn/preferred_username).
3. **SharePoint:** Upload PDF to `Invoices/{year}/{month}_{MonthName}`.
4. **Azure Document Intelligence:** `analyze_invoice_bytes()` — prebuilt-invoice model, returns full_text, extracted_text, structured_fields (VendorName, InvoiceId, etc.).
5. **iGentic:** `process_with_igentic()` — send invoice_processing + uploaded_file; returns orchestration result (CSV/JSON extraction).
6. **Logging:** `save_complete_log()` — write JSON to SharePoint `JSON files/{year}/{month}/`.
7. **Duplicate check:** `find_duplicate_invoice()` — compare invoice_number, vendor_name, amount, date; skip DB insert if match.
8. **PostgreSQL:** `insert_invoice()` then `update_invoice()` with extracted fields.
9. **SharePoint Excel:** `update_excel_file()` — append/update row in `Invoice_Register_Master.xlsx`.

**External calls:** SharePoint REST API, Azure Document Intelligence REST API, iGentic HTTP API.

**Data written:** PostgreSQL `invoices`, SharePoint Invoices library (PDF), SharePoint JSON files (audit), SharePoint Excel.

---

### 4.2 `getdata` (POST `api/getdata`)

**Purpose:** Vendor portal "View documents" — list or download.

**Body:** `{ action: "list" | "download", documentId?: string, accessToken?: string, userEmail?: string }`

**Flow:**
- `list`: Resolve vendor_id from JWT or body → `get_invoices_by_vendor()` → return `{ documents: [{ id, name, size, uploadDate }] }`.
- `download`: `get_invoice(document_id)` → return `{ url: pdf_url, name }` (SharePoint URL).

**External calls:** None (PostgreSQL only).

**Data read:** PostgreSQL `invoices` (filtered by vendor_id).

---

### 4.3 `dashboard_data` (GET `api/dashboard/data`)

**Purpose:** Accounts dashboard: rows, metrics, Excel URL.

**Flow:**
1. `get_dashboard_payload(req)` — if JWT present, check manager; managers see all invoices, vendors see only theirs.
2. `get_all_invoices()` or `get_invoices_by_vendor()`.
3. `_row_to_dashboard()` — map DB columns to dashboard format (pay_period_start, net_terms, etc.).
4. `_dashboard_metrics()` — total, pending, complete, need_approval, payment_initiated, total_amount.
5. `get_sharepoint_excel_url()` — build URL for Download Excel button.

**Response:** `{ status, metrics, rows, excelUrl? }`.

**External calls:** None (PostgreSQL + SharePoint URL derivation).

**Data read:** PostgreSQL `invoices`.

---

### 4.4 `get_invoices` (GET `api/invoices/all`)

**Purpose:** Same as `dashboard_data` — returns rows + metrics, no Excel URL. Used for alternative client routes.

---

### 4.5 `fcfigures_update` (POST `api/fcfigures/{id}/update`)

**Purpose:** Update invoice fields from accounts dashboard (inline edit).

**Body:** Partial object, e.g. `{ approved_hours, consultancy_name, pay_rate, ... }`.

**Flow:**
1. Map dashboard field names to DB columns (e.g. consultancy_name → vendor_name).
2. If `approved_hours` in body: call `validate_timesheet_hours_with_igentic(vendor_hours, timesheet, id)`.
   - **iGentic:** Compare vendor_hours vs approved_hours; returns approval_status (Complete / NEED APPROVAL / Need manual review) and optional payment_details.
   - If iGentic fails: fallback `_compare_hours_locally()` — match→Complete, timesheet>invoice→Need manual review, invoice>timesheet→NEED APPROVAL.
3. `update_invoice()` with mapped fields (including approval_status, payment_details).
4. `update_excel_file()` — sync Excel row.

**External calls:** iGentic (only when approved_hours is updated).

**Data written:** PostgreSQL `invoices`, SharePoint Excel.

---

### 4.6 `invoice_delete` (DELETE `api/invoices/{id}`)

**Purpose:** Delete invoice row from PostgreSQL.

**Flow:** `delete_invoice(id)` → `DELETE FROM invoices WHERE invoice_id = %s`.

**Data written:** None (deletion only). PDF and JSON logs in SharePoint remain.

---

### 4.7 `approve` (POST `api/approve`)

**Purpose:** Manager-only approval (status change).

**Body:** `{ invoice_uuid, status?, approval_status?, notes? }`

**Flow:**
1. `check_manager_permission(token)` — roles: Invoice.Approver, Manager, Admin.
2. `update_invoice()` with status, approval_status, approved_by, notes.
3. `save_status_change_log()` → SharePoint `JSON files/{year}/{month}/invoice_{id}_status_change.json`.
4. `update_excel_file()` — sync Excel.

**External calls:** None (PostgreSQL + SharePoint for log and Excel).

**Data written:** PostgreSQL `invoices`, SharePoint JSON log, SharePoint Excel.

---

## 5. Shared Helpers (`AzureFunctions/shared/helpers.py`)

### 5.1 SharePoint

| Function | Purpose | Azure Integration |
|----------|---------|-------------------|
| `get_sharepoint_context()` | Authenticate to SharePoint site | Azure AD app-only (certificate or client secret) |
| `upload_file_to_sharepoint()` | Upload file to library/folder | SharePoint REST API |
| `download_file_from_sharepoint()` | Download file by server-relative URL | SharePoint REST API |
| `save_json_to_sharepoint()` | Save JSON to `{folder}/{year}/{month}/` | SharePoint REST API |
| `get_sharepoint_excel_url()` | Full URL for Excel file (Download button) | URL derivation only |

**Auth:** `SHAREPOINT_CERT_BASE64`, `SHAREPOINT_CERT_THUMBPRINT`, `AZURE_CLIENT_ID`, `SHAREPOINT_TENANT_NAME` or `AZURE_TENANT_ID`.

---

### 5.2 PostgreSQL

| Function | Purpose | Data |
|----------|---------|------|
| `get_sql_connection()` | Connect via `SQL_CONNECTION_STRING` | — |
| `insert_invoice()` | Insert new row (invoice_id, vendor_id, doc_name, pdf_url) | `invoices` |
| `update_invoice()` | Dynamic UPDATE by kwargs | `invoices` |
| `get_invoice()` | Single row by invoice_id | `invoices` |
| `get_all_invoices()` | All rows ORDER BY created_at DESC | `invoices` |
| `get_invoices_by_vendor()` | Filter by vendor_id | `invoices` |
| `delete_invoice()` | DELETE WHERE invoice_id | `invoices` |
| `find_duplicate_invoice()` | Match invoice_number/vendor/amount/date | `invoices` |

---

### 5.3 Azure Document Intelligence

| Function | Purpose | Azure API |
|----------|---------|-----------|
| `analyze_invoice_bytes()` | Prebuilt-invoice model, returns full_text, extracted_text, structured_fields | `POST .../documentModels/prebuilt-invoice:analyze` |
| `_extract_invoice_fields()` | Map DI fields to our schema (InvoiceId→invoice_number, etc.) | — |
| `_parse_hours_from_text()` | Regex fallback for hours in full_text | — |

**Config:** `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`.

---

### 5.4 iGentic (External AI Orchestrator)

| Function | Purpose | External Call |
|----------|---------|---------------|
| `process_with_igentic()` | Upload pipeline: extract invoice fields from PDF/OCR | `POST IGENTIC_ENDPOINT` |
| `validate_timesheet_hours_with_igentic()` | Compare vendor_hours vs approved_hours | `POST IGENTIC_ENDPOINT` |
| `_extract_payment_details_from_igentic_response()` | Parse payment JSON from result/display_text | — |
| `_compare_hours_locally()` | Fallback when iGentic unavailable | — |
| `extract_fields_from_igentic()` | Parse CSV/JSON from orchestration result | — |
| `extract_csv_from_igentic_response()` | Find CSV block in result | — |
| `parse_csv_to_dict()` | Map CSV columns to DB fields | — |
| `extract_json_block_from_igentic_response()` | Parse JSON block from result | — |

**Config:** `IGENTIC_ENDPOINT` (e.g. `https://...azurewebsites.net/api/iGenticAutonomousAgent/Executor/{id}`).

---

### 5.5 Excel

| Function | Purpose | Storage |
|----------|---------|---------|
| `update_excel_file()` | Download Excel from SharePoint, append/update row, save back | SharePoint (`SHAREPOINT_EXCEL_PATH`) |

**Config:** `SHAREPOINT_EXCEL_PATH` (e.g. `Invoices/Invoice_Register_Master.xlsx`).

---

### 5.6 Logging & Audit

| Function | Purpose | Storage |
|----------|---------|---------|
| `save_complete_log()` | Full audit: extracted_data + orchestration_result + sql_record | SharePoint `JSON files/{year}/{month}/` |
| `save_status_change_log()` | Status change event | SharePoint `JSON files/{year}/{month}/` |

---

### 5.7 Authentication

| Function | Purpose | Used By |
|----------|---------|---------|
| `extract_token_from_request()` | Bearer token from Authorization | upload, getdata, approve, get_dashboard_payload |
| `decode_token()` | JWT decode (no verification) | — |
| `extract_vendor_id_from_token()` | email/upn/preferred_username | upload, getdata |
| `check_manager_permission()` | Invoice.Approver, Manager, Admin | approve, get_dashboard_payload |

---

## 6. Data Storage — Complete Map

| Storage | Location | What is Stored |
|---------|----------|----------------|
| **PostgreSQL** | Azure Database for PostgreSQL | `invoices` table: invoice_id, vendor_id, doc_name, pdf_url, vendor_name, invoice_number, invoice_amount, invoice_hours, hourly_rate, status, approval_status, start_date, end_date, approved_hours, payment_details, notes, template, addl_comments, etc. |
| **SharePoint — Invoices** | Document library `Invoices/{year}/{month}/` | Uploaded PDFs (original files) |
| **SharePoint — Excel** | Path from `SHAREPOINT_EXCEL_PATH` | `Invoice_Register_Master.xlsx` — register with invoice rows |
| **SharePoint — JSON files** | `JSON files/{year}/{month}/` | Audit logs: `invoice_{id}_upload.json`, `invoice_{id}_status_change.json` |
| **Browser** | sessionStorage | `loggedIn`, `userName`, `userEmail`, `accessToken` (vendor portal) |

**PostgreSQL schema:** See `AzureFunctions/create_invoices_table.sql` and `AzureFunctions/migrations/*.sql`.

---

## 7. External Azure / Third-Party Services

| Service | Used By | Env Vars | Purpose |
|---------|---------|----------|---------|
| **Azure Document Intelligence** | `analyze_invoice_bytes()` | `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY` | OCR + prebuilt-invoice extraction |
| **SharePoint Online** | upload, update_excel_file, save_json_to_sharepoint | `SHAREPOINT_SITE_URL`, `AZURE_CLIENT_ID`, `SHAREPOINT_CERT_*`, `SHAREPOINT_TENANT_NAME` | File storage, Excel, JSON logs |
| **PostgreSQL** | All DB helpers | `SQL_CONNECTION_STRING` | Invoice records |
| **iGentic (external)** | `process_with_igentic()`, `validate_timesheet_hours_with_igentic()` | `IGENTIC_ENDPOINT` | AI extraction, timesheet validation, payment details |
| **Azure AD / MSAL** | Vendor portal login | `AZURE_CLIENT_ID` (frontend config) | Microsoft sign-in |

---

## 8. Frontend Applications

### 8.1 Vendor Portal (`frontend1/`)

- **index.html:** MSAL login, redirect to upload or retrieve.
- **upload.html:** Multipart upload to `api/upload` with Bearer token.
- **retrieve.html:** `api/getdata` (list/download) with token.

**Config:** `config.js` → `apiBaseUrl`, `clientId`, `redirectUri`.

### 8.2 Accounts Dashboard (`accountsdashboard/`)

- **dashboard.html:** Fetches `api/dashboard/data`, displays metrics + table, inline edit via `api/fcfigures/{id}/update`, delete via `api/invoices/{id}`, View Payment modal for Complete rows.

**Config:** `config.js` → `apiBaseUrl`.

---

## 9. Environment Variables (Function App)

| Variable | Required | Purpose |
|----------|----------|---------|
| `SQL_CONNECTION_STRING` | Yes | PostgreSQL connection (psycopg2 format) |
| `SHAREPOINT_SITE_URL` | Yes | e.g. `https://tenant.sharepoint.com/sites/Accounts` |
| `SHAREPOINT_EXCEL_PATH` | No | Default `Invoices/Invoice_Register_Master.xlsx` |
| `AZURE_CLIENT_ID` | Yes | Azure AD app registration client ID |
| `SHAREPOINT_CERT_BASE64` | Yes* | Base64-encoded PEM certificate for app-only |
| `SHAREPOINT_CERT_THUMBPRINT` | Yes* | Certificate thumbprint |
| `SHAREPOINT_TENANT_NAME` or `AZURE_TENANT_ID` | Yes | Tenant for SharePoint auth |
| `AZURE_DI_ENDPOINT` | No | Document Intelligence endpoint (upload skips DI if unset) |
| `AZURE_DI_KEY` | No | Document Intelligence key |
| `IGENTIC_ENDPOINT` | No | iGentic API URL (upload sends; fcfigures fallback to local logic if unset) |

*Client secret does not work for SharePoint app-only; certificate required.

---

## 10. Deployment

- **Azure Functions:** GitHub Actions on push to `main` (path `AzureFunctions/**`) — uses `AZURE_FUNCTIONAPP_PUBLISH_PROFILE`, `AZURE_CREDENTIALS`.
- **Static Web Apps:** Separate workflows for vendor portal and accounts dashboard — use `AZURE_STATIC_WEB_APPS_API_TOKEN_*`.
- **Function App Settings:** See Environment Variables section above.

---

## 11. Summary of External Calls by Function

| Function | SharePoint | Document Intelligence | iGentic | PostgreSQL |
|----------|------------|----------------------|---------|------------|
| upload | ✓ (PDF, Excel, JSON) | ✓ | ✓ | ✓ |
| getdata | — | — | — | ✓ (read) |
| dashboard_data | — | — | — | ✓ (read) |
| get_invoices | — | — | — | ✓ (read) |
| fcfigures_update | ✓ (Excel) | — | ✓ (on approved_hours) | ✓ |
| invoice_delete | — | — | — | ✓ (delete) |
| approve | ✓ (Excel, JSON log) | — | — | ✓ |
