# Single Backend: Steps and Changes Made

Use **one backend** (AzureFunctions) and **two Static Web Apps** (vendor portal + accounts dashboard). All API calls go to the same Function App.

---

## What Changed

### 1. New function in AzureFunctions: `getdata`

- **Path:** `AzureFunctions/getdata/`
- **Route:** `POST /api/getdata`
- **Purpose:** Replaces the old `api/getdata` and `api/loaddata` for the vendor portal "View documents" page.
- **Behavior:**
  - **List:** Body `{ userEmail, accessToken }` (no action) → returns vendor's invoices as `{ documents: [ { id, name, size, uploadDate } ] }`.
  - **Download:** Body `{ action: 'download', documentId }` → returns `{ url, name }` (SharePoint PDF URL); frontend opens in new tab.
  - **Delete:** Returns 501 (not implemented). You can add later if needed.

### 2. Vendor portal (frontend1)

- **retrieve.html**
  - Loads `config.js`.
  - Uses `API_BASE + '/api/getdata'` for all three calls (list, download, delete).
  - Download: expects JSON `{ url, name }` and opens `url` in a new tab (no blob download).
- **upload.html**
  - Already uses `API_BASE + '/api/upload'` (no change).
- **config.js**
  - Must set `apiBaseUrl` to your Function App URL (e.g. `https://invoiceautomation-bdcudzfpe9cpf4d5.westus2-01.azurewebsites.net`).

### 3. Accounts dashboard (accountsdashboard)

- **config.js**
  - Must set `apiBaseUrl` to the **same** Function App URL.
- **dashboard.html**
  - Already uses `API_BASE + '/api/dashboard/data'` (no change).

### 4. GitHub workflow (kind-mud – vendor portal)

- **.github/workflows/azure-static-web-apps-kind-mud-03be2c81e.yml**
  - `api_location` set from `"backend1"` to `""`.
  - So the vendor portal Static Web App **no longer** deploys a managed API; it only deploys frontend1 and uses the external Function App via `config.js`.

### 5. No more `api/` (or `backend1`) backend

- All vendor portal API calls go to the Function App.
- You can remove or ignore the `api/` folder (getdata, loaddata) if it exists in the repo; it is no longer used.

---

## Steps to Go Live (Single Backend)

### Step 1: Deploy AzureFunctions to the Function App

1. Install [Azure Functions Core Tools](https://docs.microsoft.com/en-us/azure/azure-functions/functions-run-local) if needed.
2. In a terminal:
   ```bash
   cd InvoiceAutomation-main/AzureFunctions
   func azure login
   func azure functionapp publish invoiceautomation-bdcudzfpe9cpf4d5
   ```
   (Use your exact Function App name from Azure Portal.)
3. In Azure Portal → InvoiceAutomation (Function App) → **Functions**, confirm you see: **upload**, **dashboard_data**, **get_invoices**, **getdata**, **approve**, **fcfigures_update**.

### Step 2: Function App configuration

1. Azure Portal → InvoiceAutomation (Function App) → **Configuration** → **Environment variables** (Application settings).
2. Ensure all required settings are set (e.g. `AzureWebJobsStorage`, `FUNCTIONS_WORKER_RUNTIME`, `SQL_CONNECTION_STRING`, `SHAREPOINT_SITE_URL`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`, `IGENTIC_ENDPOINT`, etc.).
3. Save.

### Step 3: CORS

1. Function App → **CORS**.
2. Add:
   - Vendor portal Static Web App URL (e.g. `https://....azurestaticapps.net`).
   - Accounts dashboard Static Web App URL.
   - `http://localhost:5500` (optional, for local testing).
3. Save.

### Step 4: Config for both portals

1. **frontend1/config.js**  
   Set `apiBaseUrl` to your Function App URL (no trailing slash).  
   Example: `https://invoiceautomation-bdcudzfpe9cpf4d5.westus2-01.azurewebsites.net`

2. **accountsdashboard/config.js**  
   Set `apiBaseUrl` to the **same** Function App URL.

3. Commit and push so both Static Web Apps redeploy with the correct backend URL.

### Step 5: Push workflow change

- Commit and push the change to `.github/workflows/azure-static-web-apps-kind-mud-03be2c81e.yml` (`api_location: ""`).
- This stops deploying a second backend for the vendor portal.

### Step 6: Test

1. **Vendor portal**
   - Upload a file → should hit Function App `/api/upload` → success and file in SharePoint.
   - View documents → should hit `/api/getdata` (list) → list of vendor’s invoices.
   - Download → should get JSON with `url` and open PDF in new tab.
2. **Accounts dashboard**
   - Open dashboard → should hit `/api/dashboard/data` → rows and metrics.
3. **Function App**
   - Monitor / Log stream: confirm invocations for upload, getdata, dashboard_data.

---

## Architecture After Changes

```
Vendor Portal (Static Web App – frontend1)
    → config.js apiBaseUrl
    → POST /api/upload          (upload)
    → POST /api/getdata         (list, download, delete)

Accounts Dashboard (Static Web App – accountsdashboard)
    → config.js apiBaseUrl
    → GET /api/dashboard/data   (rows + metrics)
    → POST /api/approve
    → POST /api/fcfigures/{id}/update

All of the above
    → Same Function App (AzureFunctions)
    → SQL + SharePoint + Document Intelligence + iGentic
```

---

## Optional: Delete or Archive `api/` Folder

If your repo still has an `api/` (or `backend1/`) folder with getdata/loaddata:

- You can delete it or move it to an `archive/` folder so the repo clearly has a single backend (AzureFunctions).
- Only do this after you’ve deployed AzureFunctions and confirmed vendor portal and accounts dashboard work.

---

## Checklist

- [ ] AzureFunctions deployed to Function App (upload, getdata, dashboard_data, etc. visible).
- [ ] Function App Application settings and CORS configured.
- [ ] frontend1/config.js has correct `apiBaseUrl`.
- [ ] accountsdashboard/config.js has correct `apiBaseUrl`.
- [ ] kind-mud workflow has `api_location: ""` and is pushed.
- [ ] Vendor portal: upload and View documents work.
- [ ] Accounts dashboard: data loads and actions work.
- [ ] (Optional) Remove or archive `api/` folder.
