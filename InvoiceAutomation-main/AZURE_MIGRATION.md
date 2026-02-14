# Azure Migration Guide – Invoice Automation

This guide walks you through moving the Invoice Automation app to Azure for cloud deployment.

---

## 1. What You Have Today

- **Backend**: Python Azure Functions in `AzureFunctions/`
  - **upload** – `POST api/upload`: upload PDF → SharePoint, SQL insert, Document Intelligence, iGentic, SQL update, JSON log
  - **get_invoices** – `GET api/invoices/all`: dashboard data (all invoices or by vendor from JWT)
  - **dashboard_data** – `GET api/dashboard/data`: same as above (for existing dashboard HTML)
  - **approve** – `POST api/approve`: manager approval, SQL update, status log
  - **fcfigures_update** – `POST api/fcfigures/{id}/update`: save invoice details from dashboard

- **Config used by code** (from `shared/helpers.py` and functions):
  - `AzureWebJobsStorage`, `FUNCTIONS_WORKER_RUNTIME`
  - `SQL_CONNECTION_STRING`
  - `SHAREPOINT_SITE_URL`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
  - `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`
  - `IGENTIC_ENDPOINT`
  - Optional: `WEBAPP_BASE_URL` (for CORS/frontend), `AZURE_TENANT_ID` (for future Azure AD)

Your plan already includes all of these. The code is ready for Azure; the work is configuration and deployment.

---

## 2. Fix Config and Keep Secrets Safe

- **Typo**: In your plan, `SHAREPOINT_SITE_URL` has `invoiveautomation` – confirm the correct tenant subdomain (e.g. `invoiceautomation`) and fix it.
- **Never commit secrets**: 
  - Copy `AzureFunctions/local.settings.json.example` to `AzureFunctions/local.settings.json`.
  - Put your real values only in `local.settings.json`. This file is in `.gitignore` – do not remove it.
  - For Azure, use **Application Settings** (or Key Vault), not a settings file in the repo.

---

## 3. Local Setup (Before Deploying)

1. **Create local settings**
   - Copy `AzureFunctions/local.settings.json.example` → `AzureFunctions/local.settings.json`.
   - Fill in your real values (SQL, SharePoint, Document Intelligence, iGentic, etc.).

2. **Python environment**
   - From repo root:  
     `cd AzureFunctions`  
     `python -m venv .venv`  
     `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Mac/Linux)  
     `pip install -r requirements.txt`

3. **Azure Storage (for local Functions runtime)**
   - Either: [Azurite](https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azurite) with `AzureWebJobsStorage: UseDevelopmentStorage=true`.
   - Or: use a real Azure Storage connection string in `local.settings.json` for `AzureWebJobsStorage`.

4. **Run Functions locally**
   - In `AzureFunctions`:  
     `func start`
   - Test: `POST http://localhost:7071/api/upload` (multipart file), `GET http://localhost:7071/api/dashboard/data`, etc.

---

## 4. Azure Resources You Need

From your plan, you already have or are planning:

| Resource | Purpose |
|----------|--------|
| **Azure SQL** (`invoiceautomation.database.windows.net` / InvoiceDB) | Invoice records |
| **SharePoint** (e.g. `.../sites/Accounts`) | PDFs + JSON_Logs |
| **App registration** (Client ID/Secret/Tenant) | SharePoint + optional Azure AD auth |
| **Document Intelligence** (`di-extract-invoice`) | Invoice extraction |
| **iGentic** (bluecoast-sk-...) | Orchestrator |
| **Function App** (to create) | Host Python Azure Functions |
| **Storage account** (for Function App) | Required by Azure Functions runtime |

Ensure the **invoices** table (and any other tables) exist in InvoiceDB; the code expects the schema used in `shared/helpers.py` (e.g. `invoice_id`, `vendor_id`, `doc_name`, `pdf_url`, `status`, `approval_status`, etc.).

---

## 5. Deploy the Function App to Azure

1. **Create a Function App** (Azure Portal or CLI)
   - Runtime: **Python** (e.g. 3.9, 3.10, or 3.11).
   - OS: Linux or Windows (Linux is common for Python).
   - Create a **Storage account** for the app if you don’t have one.
   - Plan: Consumption or Premium (Consumption is fine to start).

2. **Deploy the code**
   - **Option A – VS Code**: Azure Functions extension → right‑click `AzureFunctions` folder → Deploy to Function App.
   - **Option B – CLI**:  
     `func azure functionapp publish <YourFunctionAppName>`  
     (run from the `AzureFunctions` folder.)
   - **Option C – CI/CD**: Azure DevOps or GitHub Actions with `azure/functions-action` or `Azure/functions-action`, building/deploying from `AzureFunctions`.

3. **Application Settings in Azure**
   - In the Function App → **Configuration** → **Application settings**, add every key from your plan (same names as in `local.settings.json`):
     - `AzureWebJobsStorage` – use the storage connection string for this Function App.
     - `FUNCTIONS_WORKER_RUNTIME` = `python`
     - `SQL_CONNECTION_STRING`
     - `SHAREPOINT_SITE_URL` (fix typo if needed)
     - `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
     - `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`
     - `IGENTIC_ENDPOINT`
     - `WEBAPP_BASE_URL` – set to your frontend URL (e.g. Static Web App) for CORS if you add it in code.
   - Do **not** put these secrets in the repo; only in Azure (or Key Vault).

4. **CORS** (if the frontend calls the Function App from a browser)
   - Function App → **CORS** → add your frontend origin(s), e.g. `https://<your-static-web-app>.azurestaticapps.net` and `http://localhost:PORT` for local dev.

---

## 6. Frontend (Static Web App)

You have `frontend1/` and GitHub workflows for Azure Static Web Apps. The backend is **Azure Functions** (separate from SWA’s built‑in API).

- **Option A – Same domain**: Configure Static Web App to proxy `/api/*` to your Function App (e.g. with a [backend link](https://learn.microsoft.com/en-us/azure/static-web-apps/backend-internal)) so the frontend keeps calling `/api/...`.
- **Option B – Different host**: Point the frontend’s API base URL to your Function App, e.g. `https://<YourFunctionApp>.azurewebsites.net/api`. Update `fetch('/api/...')` to use that base URL (or an env variable) so the same code works for local and production.

Your current HTML uses `/api/loaddata` and `/api/getdata`; the Functions expose `api/upload`, `api/invoices/all`, `api/dashboard/data`, `api/approve`, `api/fcfigures/{id}/update`. You may need to align routes (e.g. map `loaddata`/`getdata` to `dashboard/data` or `invoices/all`) or add small proxy routes.

---

## 7. Security Checklist

- **Secrets**: Never commit `local.settings.json` or any file with real keys. Use Application Settings (or Key Vault) in Azure.
- **Production**: Prefer **Azure Key Vault** references for secrets (Function App → Configuration → Key Vault references).
- **Auth**: The app uses JWT for vendor/manager checks. For production, validate JWTs properly (signature, issuer, audience) instead of `options={"verify_signature": False}` in `helpers.py`.
- **HTTPS**: Use HTTPS only in production (Azure provides this for the Function App and Static Web App).

---

## 8. Next Steps (Ordered)

1. Fix `SHAREPOINT_SITE_URL` typo and create `local.settings.json` from the example (local only).
2. Run the Function App locally (`func start`) and test upload + dashboard + approve.
3. Create the Function App and Storage account in Azure.
4. Deploy the `AzureFunctions` project to the Function App.
5. Add all Application Settings in the Function App (and enable CORS if needed).
6. Test the deployed endpoints (Postman or browser) and fix any DI/SharePoint/SQL connectivity (firewall, managed identity later if you use it).
7. Wire the frontend to the deployed API URL and align routes (`loaddata`/`getdata` vs `dashboard/data`/`invoices/all`).
8. (Optional) Move secrets to Key Vault and switch to Key Vault references; enable proper JWT verification.

If you tell me your preferred next step (e.g. “deploy with GitHub Actions” or “add CORS and WEBAPP_BASE_URL to the code”), I can outline the exact changes and commands.
