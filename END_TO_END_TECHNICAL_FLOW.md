# End-to-End Technical Flow — Invoice Automation

This document traces **every step** from frontend user action to backend execution: which file, which function, and in what order. Use it for debugging, onboarding, or impact analysis.

**Repo root:** `c:\Users\chitr\Downloads\InvoiceAutomation-main` (or your workspace root).

**Conventions:**
- **Frontend:** paths relative to repo root, e.g. `frontend1/upload.html`.
- **Backend:** `AzureFunctions/<function_folder>/__init__.py` → entry is always `main(req)`.
- **Shared:** `AzureFunctions/shared/helpers.py` — all HTTP functions call into here.
- **API base URL:** From `window.APP_CONFIG.apiBaseUrl` (e.g. `frontend1/config.js`, `accountsdashboard/config.js`). Full endpoint = `API_BASE + '/api/<route>'`.

---

## 1. Configuration and routing

### 1.1 Frontend API base URL

| Step | File | What happens |
|------|------|----------------|
| 1 | `frontend1/config.js` | Defines `window.APP_CONFIG.apiBaseUrl` (vendor portal). |
| 2 | `accountsdashboard/config.js` | Defines `window.APP_CONFIG.apiBaseUrl` (accounts dashboard). |
| 3 | On localhost | Each HTML injects `<script src="config.local.js">` if host is localhost/127.0.0.1; optional override. |

### 1.2 Azure Functions routing

| File | Purpose |
|------|--------|
| `AzureFunctions/host.json` | Runtime version 2.0, logging, extension bundle, 5 min timeout. No route overrides. |
| Each `AzureFunctions/<name>/function.json` | Binds HTTP trigger: method(s), route. URL = `https://<app>.azurewebsites.net/api/<route>`. |

**Route summary:**

| Function folder | File | Route | Methods | Effective URL |
|-----------------|------|--------|---------|----------------|
| upload | `AzureFunctions/upload/function.json` | `upload` | POST | `POST /api/upload` |
| getdata | `AzureFunctions/getdata/function.json` | `getdata` | POST | `POST /api/getdata` |
| dashboard_data | `AzureFunctions/dashboard_data/function.json` | `dashboard/data` | GET | `GET /api/dashboard/data` |
| fcfigures_update | `AzureFunctions/fcfigures_update/function.json` | `fcfigures/{id}/update` | POST | `POST /api/fcfigures/{id}/update` |
| invoice_delete | `AzureFunctions/invoice_delete/function.json` | `invoices/{id}` | DELETE | `DELETE /api/invoices/{id}` |
| get_invoices | `AzureFunctions/get_invoices/function.json` | `invoices/all` | GET | `GET /api/invoices/all` |
| approve | `AzureFunctions/approve/function.json` | `approve` | POST | `POST /api/approve` |

---

## 2. Flow A — Vendor portal: page load and login

### 2.1 User opens vendor portal (index)

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `frontend1/index.html` | Document load | HTML loads. |
| 2 | Frontend | `frontend1/index.html` | `<script src="config.js">` | Loads `window.APP_CONFIG` (apiBaseUrl, clientId, redirectUri). |
| 3 | Frontend | `frontend1/index.html` | Optional `config.local.js` on localhost | Overrides config if present. |
| 4 | Frontend | `frontend1/index.html` | MSAL script | `https://alcdn.msauth.net/browser/2.38.1/js/msal-browser.min.js` for login. |
| 5 | Frontend | `frontend1/index.html` | User clicks "Sign in with Microsoft" | MSAL redirects to Azure AD; no backend call in this repo. |
| 6 | Frontend | `frontend1/index.html` | Redirect back to index.html | Callback handled; token stored in sessionStorage (accessToken, userEmail, userName). |
| 7 | Frontend | `frontend1/index.html` | Navigation to upload or retrieve | Links to `upload.html` or `retrieve.html` (same origin; sessionStorage available). |

**Backend:** None for login; auth is client-side MSAL + sessionStorage.

---

## 3. Flow B — Vendor portal: upload invoice

### 3.1 User selects file and clicks Upload

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `frontend1/upload.html` | `uploadArea.addEventListener('click', …)` (line ~283) | Click on drop zone triggers file picker. |
| 2 | Frontend | `frontend1/upload.html` | `fileInput.addEventListener('change', …)` (line ~286) | `handleFiles(e.target.files)` adds files to `selectedFiles` and renders list. |
| 3 | Frontend | `frontend1/upload.html` | `uploadBtn.addEventListener('click', async () => { … })` (line ~375) | User clicks "Upload" button. |
| 4 | Frontend | `frontend1/upload.html` | Same handler | Reads `API_BASE` from `window.APP_CONFIG.apiBaseUrl` (line ~365), strips trailing slashes, forces HTTPS. |
| 5 | Frontend | `frontend1/upload.html` | Same handler | Builds `uploadUrl = base + '/api/upload'` (line ~402). |
| 6 | Frontend | `frontend1/upload.html` | Same handler | Creates `FormData`, appends each file with key `'file'`. |
| 7 | Frontend | `frontend1/upload.html` | Same handler | Sets `headers['Authorization'] = 'Bearer ' + accessToken` from sessionStorage (line ~397). |
| 8 | Frontend | `frontend1/upload.html` | `fetch(uploadUrl, { method: 'POST', headers, body: formData })` (line ~404) | **HTTP request:** `POST {API_BASE}/api/upload`, multipart/form-data, Bearer token. |

### 3.2 Backend: upload function (every step)

| Step | Location | File | Function | Description |
|------|----------|------|----------|-------------|
| 9 | Backend | `AzureFunctions/upload/__init__.py` | `main(req)` | Azure runtime invokes HTTP trigger; `req` = HttpRequest. |
| 10 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Reads `Authorization` header; if Bearer, extracts token (line ~71–73). |
| 11 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Adds parent to `sys.path`, imports `shared.helpers.decode_token` (line ~75–77). |
| 12 | Backend | `AzureFunctions/shared/helpers.py` | `decode_token(token)` | Decodes JWT (no signature verification); returns payload dict. |
| 13 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Sets `vendor_id` from decoded token (email/upn/preferred_username/sub) or "unknown" (line ~79–82). |
| 14 | Backend | `AzureFunctions/upload/__init__.py` | `_parse_multipart(body, content_type)` | Parses multipart body; returns `(file_content, filename)` for part with name `file` (line ~17–44, called ~88). |
| 15 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Validates file type (pdf/png/jpg/jpeg) and size (max 10MB) (line ~96–109). |
| 16 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Imports from `shared.helpers`: `upload_file_to_sharepoint`, `analyze_invoice_bytes`, `process_with_igentic`, `save_complete_log`, `_parse_hours_from_text` (line ~114–119). If DB configured: `insert_invoice`, `update_invoice`, `get_invoice`, `find_duplicate_invoice` (line ~123). |
| 17 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Generates `invoice_id = uuid.uuid4()`, builds folder path (e.g. Invoices/2025/01_January) (line ~125–132). |
| 18 | Backend | `AzureFunctions/shared/helpers.py` | `upload_file_to_sharepoint(file_content, safe_name, folder_path)` | Uploads file to SharePoint; returns server-relative URL (called from upload ~134). |
| 19 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Builds `pdf_url` from SharePoint site URL + server path (line ~143–144). |
| 20 | Backend | `AzureFunctions/shared/helpers.py` | `analyze_invoice_bytes(file_content, safe_name)` | Calls Azure Document Intelligence (prebuilt-invoice); returns full_text, extracted_text, structured_fields (called from upload ~147). |
| 21 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Builds `user_input_for_igentic` from invoice_data; calls `process_with_igentic(...)` (line ~159–169). |
| 22 | Backend | `AzureFunctions/shared/helpers.py` | `process_with_igentic(user_input_for_igentic, invoice_id, ...)` | Runs iGentic orchestration; returns response dict (CSV + JSON block, etc.). |
| 23 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Calls `save_complete_log(invoice_id, invoice_data, orchestration_response, "upload")` (line ~174). |
| 24 | Backend | `AzureFunctions/shared/helpers.py` | `save_complete_log(...)` | Saves JSON log (e.g. to SharePoint). |
| 25 | Backend | `AzureFunctions/upload/__init__.py` | `_extract_from_orchestrator(orchestration_response)` | Calls `shared.helpers.extract_fields_from_igentic`, `_extract_payment_details_from_igentic_response`; returns `fields` dict (line ~46–61, ~179). |
| 26 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Fallback for invoice_hours from structured_fields or `_parse_hours_from_text(full_text)` (line ~180–186). |
| 27 | Backend | `AzureFunctions/upload/__init__.py` | `main` | If DB: `find_duplicate_invoice(fields)` from shared.helpers (line ~192). If duplicate: return 200 with duplicate message, no DB insert (line ~193–205). |
| 28 | Backend | `AzureFunctions/shared/helpers.py` | `insert_invoice(invoice_id, vendor_id, safe_name, pdf_url)` | Called from upload ~210; inserts row into PostgreSQL. |
| 29 | Backend | `AzureFunctions/shared/helpers.py` | `update_invoice(invoice_id, **fields)` | Called from upload ~221; updates row with iGentic-extracted fields. |
| 30 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Imports `update_excel_file`, `get_invoice`; gets invoice from DB; builds `excel_data`; calls `update_excel_file(invoice_id, excel_data)` (line ~224–245). |
| 31 | Backend | `AzureFunctions/shared/helpers.py` | `update_excel_file(invoice_id, excel_data)` | Updates Excel file in SharePoint. |
| 32 | Backend | `AzureFunctions/upload/__init__.py` | `main` | Returns `func.HttpResponse` with JSON: message, filename, invoice_uuid, data, workflow (line ~257–272). |

### 3.3 Frontend after response

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 33 | Frontend | `frontend1/upload.html` | Same click handler | `const result = await response.json()`; if `response.ok`, shows success message, clears file list; else shows error (line ~409–425). |

---

## 4. Flow C — Vendor portal: list documents (retrieve)

### 4.1 Page load and list

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `frontend1/retrieve.html` | `window.addEventListener('load', () => loadDocuments())` (line ~280–281) | On page load, calls `loadDocuments()`. |
| 2 | Frontend | `frontend1/retrieve.html` | `async function loadDocuments()` (line ~284) | Shows loading; builds `API_BASE` from `window.APP_CONFIG.apiBaseUrl`. |
| 3 | Frontend | `frontend1/retrieve.html` | Same function | `fetch(API_BASE + '/api/getdata', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + accessToken }, body: JSON.stringify({ action: 'list', userEmail, accessToken }) })` (line ~294–298). |
| 4 | Backend | `AzureFunctions/getdata/__init__.py` | `main(req)` | HTTP trigger invoked for `POST /api/getdata`. |
| 5 | Backend | `AzureFunctions/getdata/__init__.py` | `main` | Parses body: `action = body.get("action") or "list"` (line ~22–23). |
| 6 | Backend | `AzureFunctions/getdata/__init__.py` | `main` | Imports from `shared.helpers`: `extract_token_from_request`, `extract_vendor_id_from_token`, `get_invoices_by_vendor`, `get_invoice` (line ~45–50). |
| 7 | Backend | `AzureFunctions/shared/helpers.py` | `extract_token_from_request(req)` | Returns Bearer token from Authorization header or `body.accessToken`. |
| 8 | Backend | `AzureFunctions/shared/helpers.py` | `extract_vendor_id_from_token(token)` | Decodes token; returns email/upn/preferred_username/sub/oid. |
| 9 | Backend | `AzureFunctions/getdata/__init__.py` | `main` | Resolves `vendor_id` from token or `body.userEmail` (line ~52–61). |
| 10 | Backend | `AzureFunctions/getdata/__init__.py` | `main` | For `action == "list"`: calls `get_invoices_by_vendor(vendor_id)` (line ~64–65). |
| 11 | Backend | `AzureFunctions/shared/helpers.py` | `get_invoices_by_vendor(vendor_id)` | Queries PostgreSQL for invoices by vendor_id; returns list of rows. |
| 12 | Backend | `AzureFunctions/getdata/__init__.py` | `main` | Maps rows to `{ id, name, size, uploadDate }`; returns `{ documents }` JSON (line ~66–78). |
| 13 | Frontend | `frontend1/retrieve.html` | `loadDocuments()` | Parses response; calls `renderDocuments(data.documents)` (or similar) to fill table. |

### 4.2 Search (filter client-side)

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `frontend1/retrieve.html` | `onclick="searchDocuments()"` or Enter in search input (line ~251, ~504–506) | User clicks Search or presses Enter. |
| 2 | Frontend | `frontend1/retrieve.html` | `searchDocuments()` | If no search term: calls `loadDocuments()` again (same API). If search term: filters `allDocuments` in memory and re-renders (no new backend call for filter-only). If implementation fetches again: same as Flow C steps 3–12 with same `POST /api/getdata` body. |

### 4.3 Download document

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `frontend1/retrieve.html` | `onclick="downloadDocument('${doc.id}', '${doc.name}')"` (line ~362) | User clicks Download on a row. |
| 2 | Frontend | `frontend1/retrieve.html` | `async function downloadDocument(id, name)` | `fetch(API_BASE + '/api/getdata', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + accessToken }, body: JSON.stringify({ action: 'download', documentId: id, userEmail, accessToken }) })` (line ~433–438). |
| 3 | Backend | `AzureFunctions/getdata/__init__.py` | `main(req)` | Body: `action == "download"`, `document_id` set (line ~22–23, ~80). |
| 4 | Backend | `AzureFunctions/getdata/__init__.py` | `main` | Calls `get_invoice(document_id)` from shared.helpers (line ~81). |
| 5 | Backend | `AzureFunctions/shared/helpers.py` | `get_invoice(invoice_id)` | Returns single invoice row from PostgreSQL (includes pdf_url, doc_name). |
| 6 | Backend | `AzureFunctions/getdata/__init__.py` | `main` | Returns JSON `{ url: pdf_url, name: doc_name }` (line ~96–99). |
| 7 | Frontend | `frontend1/retrieve.html` | `downloadDocument` | Reads `data.url`; opens in new tab or triggers download (e.g. `window.open(data.url)`). |

---

## 5. Flow D — Accounts dashboard: page load and refresh

### 5.1 Load dashboard data

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `accountsdashboard/dashboard.html` | Script: `API_BASE` from `window.APP_CONFIG.apiBaseUrl` (line ~299–303). | On load, base URL is set. |
| 2 | Frontend | `accountsdashboard/dashboard.html` | `window.addEventListener('load', () => loadDashboard())` (line ~318) | On load, calls `loadDashboard()`. |
| 3 | Frontend | `accountsdashboard/dashboard.html` | `async function loadDashboard()` (line ~324) | `showLoading(true)`; then `fetch(API_BASE + '/api/dashboard/data', { method: 'GET' })` (line ~330). |
| 4 | Backend | `AzureFunctions/dashboard_data/__init__.py` | `main(req)` | HTTP trigger for `GET /api/dashboard/data`. |
| 5 | Backend | `AzureFunctions/dashboard_data/__init__.py` | `main` | Imports `get_dashboard_payload`, `get_sharepoint_excel_url` from shared.helpers (line ~26). |
| 6 | Backend | `AzureFunctions/shared/helpers.py` | `get_dashboard_payload(req)` | Gets token via `extract_token_from_request(req)`; if token, `check_manager_permission(token)` and `extract_vendor_id_from_token(token)`; if manager or no vendor_id calls `get_all_invoices()`, else `get_invoices_by_vendor(vendor_id)`; maps rows with `_row_to_dashboard`, computes `_dashboard_metrics`; returns (rows, metrics). |
| 7 | Backend | `AzureFunctions/shared/helpers.py` | `get_sharepoint_excel_url()` | Returns Excel file URL if configured. |
| 8 | Backend | `AzureFunctions/dashboard_data/__init__.py` | `main` | Builds payload `{ status, metrics, rows, excelUrl? }`; returns JSON (line ~28–39). |
| 9 | Frontend | `accountsdashboard/dashboard.html` | `loadDashboard()` | Parses response; updates metric tiles and table; calls `renderTable()` and wires Edit/Delete/View Payment (line ~330 onward, ~456–467, ~473–487). |

**Refresh:** User clicks "Refresh" → `onclick="loadDashboard()"` (line ~237) → same steps 3–9.

---

## 6. Flow E — Accounts dashboard: edit cell and save

### 6.1 User edits a cell and blurs (or Enter)

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `accountsdashboard/dashboard.html` | Cell with class `editable` + `data-field`, `data-id` (line ~473) | `cell.addEventListener('click', …)` turns cell into input. |
| 2 | Frontend | `accountsdashboard/dashboard.html` | Same handler | On `input.addEventListener('blur', () => saveEdit(id, field, input.value, this))` or Enter (line ~484–486). |
| 3 | Frontend | `accountsdashboard/dashboard.html` | `async function saveEdit(invoiceId, field, value, cellEl)` | Builds body with field key (e.g. approved_hours, vendor_hours); `fetch(API_BASE + '/api/fcfigures/' + encodeURIComponent(invoiceId) + '/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })` (line ~496–499). |
| 4 | Backend | `AzureFunctions/fcfigures_update/__init__.py` | `main(req)` | HTTP trigger for `POST /api/fcfigures/{id}/update`. |
| 5 | Backend | `AzureFunctions/fcfigures_update/__init__.py` | `main` | Reads `invoice_id` from `req.route_params.get("id")`; parses JSON body (line ~39–50). |
| 6 | Backend | `AzureFunctions/fcfigures_update/__init__.py` | `main` | Imports from shared: `get_invoice`, `update_invoice`, `validate_timesheet_hours_with_igentic`, `_compare_hours_locally` (line ~55–60). |
| 7 | Backend | `AzureFunctions/shared/helpers.py` | `get_invoice(invoice_id)` | Loads existing row. |
| 8 | Backend | `AzureFunctions/fcfigures_update/__init__.py` | `main` | Maps body keys to SQL columns via `FIELD_MAP`; builds `kwargs` (line ~71–78). If `approved_hours` in body: calls `validate_timesheet_hours_with_igentic(vendor_hrs, timesheet, invoice_id)`; on failure uses `_compare_hours_locally`; sets approval_status/status/payment_details (line ~81–95). |
| 9 | Backend | `AzureFunctions/shared/helpers.py` | `update_invoice(invoice_id, **kwargs_clean)` | Updates PostgreSQL row (called from fcfigures_update ~106). |
| 10 | Backend | `AzureFunctions/fcfigures_update/__init__.py` | `main` | Imports `update_excel_file`, `get_invoice`; fetches updated invoice; calls `update_excel_file(invoice_id, inv)` (line ~108–115). |
| 11 | Backend | `AzureFunctions/shared/helpers.py` | `update_excel_file(invoice_id, inv)` | Syncs row to SharePoint Excel. |
| 12 | Backend | `AzureFunctions/fcfigures_update/__init__.py` | `main` | Returns `{ status: "ok" }` (line ~117–121). |
| 13 | Frontend | `accountsdashboard/dashboard.html` | `saveEdit` | On success, restores cell display (no full reload unless you add it). |

---

## 7. Flow F — Accounts dashboard: delete row(s)

### 7.1 Single row delete

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `accountsdashboard/dashboard.html` | `document.querySelectorAll('.btn-delete-row').forEach(btn => { btn.onclick = ... })` (line ~462–467) | User clicks "Delete" on a row. |
| 2 | Frontend | `accountsdashboard/dashboard.html` | Handler gets `id` from `td.closest('.actions-col').dataset.invoiceId`; calls `deleteRow(id, e)` (line ~464–466). |
| 3 | Frontend | `accountsdashboard/dashboard.html` | `async function deleteRow(invoiceId, ev)` (line ~564) | After confirm: `fetch(API_BASE + '/api/invoices/' + encodeURIComponent(invoiceId), { method: 'DELETE' })` (line ~569). |
| 4 | Backend | `AzureFunctions/invoice_delete/__init__.py` | `main(req)` | HTTP trigger for `DELETE /api/invoices/{id}`. |
| 5 | Backend | `AzureFunctions/invoice_delete/__init__.py` | `main` | Reads `invoice_id` from `req.route_params.get("id")` (line ~18). |
| 6 | Backend | `AzureFunctions/invoice_delete/__init__.py` | `main` | Imports `delete_invoice` from shared.helpers (line ~29). |
| 7 | Backend | `AzureFunctions/shared/helpers.py` | `delete_invoice(invoice_id)` | Deletes row from PostgreSQL; returns True if deleted. |
| 8 | Backend | `AzureFunctions/invoice_delete/__init__.py` | `main` | Returns 200 `{ status: "ok" }` or 404 if not found (line ~37–47). |
| 9 | Frontend | `accountsdashboard/dashboard.html` | `deleteRow` | On success calls `loadDashboard()` to refresh table (line ~572). |

### 7.2 Bulk delete (selected rows)

| Step | Location | File | Function / code | Description |
|------|----------|------|------------------|-------------|
| 1 | Frontend | `accountsdashboard/dashboard.html` | `deleteSelectedRows()` (line ~579) | User selects rows and triggers bulk delete (e.g. button); `getSelectedIds()` returns checked invoice ids. |
| 2 | Frontend | `accountsdashboard/dashboard.html` | Same function | For each id: `fetch(API_BASE + '/api/invoices/' + encodeURIComponent(id), { method: 'DELETE' })` (line ~586). |
| 3 | Backend | `AzureFunctions/invoice_delete/__init__.py` | `main(req)` | Same as Flow F steps 4–8 per id. |
| 4 | Frontend | `accountsdashboard/dashboard.html` | Same function | If any deleted, calls `loadDashboard()` (line ~590). |

---

## 8. Backend-only endpoints (no current UI)

| Endpoint | Method | Backend file | Entry | Purpose |
|----------|--------|--------------|--------|---------|
| `/api/invoices/all` | GET | `AzureFunctions/get_invoices/__init__.py` | `main(req)` | Returns same dashboard-style payload as `get_dashboard_payload`; route differs. |
| `/api/approve` | POST | `AzureFunctions/approve/__init__.py` | `main(req)` | Manager approval: checks token with `check_manager_permission`, updates invoice status, `save_status_change_log`, `update_excel_file`. |

---

## 9. Shared helpers reference (AzureFunctions/shared/helpers.py)

Used across the flows above:

| Function | Used by (function) | Purpose |
|----------|--------------------|---------|
| `decode_token(token)` | upload | Decode JWT payload (no verify). |
| `extract_token_from_request(req)` | getdata, dashboard_data (via get_dashboard_payload), approve | Get Bearer token from header or body. |
| `extract_vendor_id_from_token(token)` | getdata, get_dashboard_payload | Identity from JWT. |
| `extract_user_id_from_token(token)` | approve | User id from JWT. |
| `check_manager_permission(token)` | get_dashboard_payload, approve | Manager/approver role check. |
| `upload_file_to_sharepoint(...)` | upload | Upload file to SharePoint. |
| `analyze_invoice_bytes(...)` | upload | Document Intelligence prebuilt-invoice. |
| `process_with_igentic(...)` | upload | iGentic orchestration. |
| `save_complete_log(...)` | upload | Save JSON log. |
| `_parse_hours_from_text(...)` | upload | Parse hours from full text. |
| `extract_fields_from_igentic`, `_extract_payment_details_from_igentic_response` | upload (via _extract_from_orchestrator) | Parse iGentic response. |
| `insert_invoice`, `update_invoice`, `get_invoice` | upload, fcfigures_update, approve | SQL CRUD. |
| `find_duplicate_invoice` | upload | Duplicate check before insert. |
| `get_invoices_by_vendor` | getdata, get_dashboard_payload | List by vendor. |
| `get_all_invoices` | get_dashboard_payload | All invoices (manager). |
| `get_dashboard_payload(req)` | dashboard_data | Rows + metrics. |
| `get_sharepoint_excel_url()` | dashboard_data | Excel URL. |
| `delete_invoice(invoice_id)` | invoice_delete | Delete row. |
| `validate_timesheet_hours_with_igentic`, `_compare_hours_locally` | fcfigures_update | Hours validation. |
| `update_excel_file(...)` | upload, fcfigures_update, approve | Sync to SharePoint Excel. |
| `save_status_change_log` | approve | Log status change. |

---

## 10. Quick reference: Frontend → API → Backend

| User action | Frontend file | API call | Backend file | Backend entry |
|-------------|---------------|----------|--------------|----------------|
| Upload invoice | `frontend1/upload.html` | POST /api/upload | `AzureFunctions/upload/__init__.py` | `main(req)` |
| List my documents | `frontend1/retrieve.html` | POST /api/getdata (action: list) | `AzureFunctions/getdata/__init__.py` | `main(req)` |
| Download document | `frontend1/retrieve.html` | POST /api/getdata (action: download) | `AzureFunctions/getdata/__init__.py` | `main(req)` |
| Load / refresh dashboard | `accountsdashboard/dashboard.html` | GET /api/dashboard/data | `AzureFunctions/dashboard_data/__init__.py` | `main(req)` |
| Save edited cell | `accountsdashboard/dashboard.html` | POST /api/fcfigures/{id}/update | `AzureFunctions/fcfigures_update/__init__.py` | `main(req)` |
| Delete one row | `accountsdashboard/dashboard.html` | DELETE /api/invoices/{id} | `AzureFunctions/invoice_delete/__init__.py` | `main(req)` |
| Delete selected rows | `accountsdashboard/dashboard.html` | DELETE /api/invoices/{id} (per id) | `AzureFunctions/invoice_delete/__init__.py` | `main(req)` |

---

*Document generated for the Invoice Automation project. Update this file when adding new frontend pages or Azure Functions.*
