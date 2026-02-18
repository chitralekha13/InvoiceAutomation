# Invoice Automation

Invoice upload, processing, and management: Vendor Portal → Document Intelligence → iGentic → PostgreSQL → Accounts Dashboard + Excel.

## Architecture

| Component | Location | Deploy |
|-----------|----------|--------|
| **Vendor Portal** (upload, Microsoft login) | `frontend1/` | Static Web App |
| **Accounts Dashboard** (invoice table, edit) | `accountsdashboard/` | Static Web App |
| **Backend API** | `AzureFunctions/` | Azure Functions |
| **Database** | PostgreSQL | Azure Database for PostgreSQL |
| **Storage** | SharePoint | PDFs, JSON logs, Excel |

## Quick Deploy (GitHub)

1. Push to `main` → GitHub Actions deploy:
   - `azure-static-web-apps-kind-mud-03be2c81e` → Vendor Portal
   - `azure-static-web-apps-gray-forest-033ccce1e` → Accounts Dashboard
   - `azure-functions-deploy` → Function App

2. **GitHub Secrets** required:
   - `AZURE_CLIENT_ID` – Azure AD app (Microsoft login)
   - `API_BASE_URL` – Function App URL (optional, has default)
   - `AZURE_STATIC_WEB_APPS_API_TOKEN_KIND_MUD_03BE2C81E` – Vendor Portal deploy
   - `AZURE_STATIC_WEB_APPS_API_TOKEN_GRAY_FOREST_033CCCE1E` – Dashboard deploy
   - `AZURE_CREDENTIALS` / `AZURE_FUNCTIONAPP_PUBLISH_PROFILE` – Function App deploy

3. **Function App** config (Azure Portal → Configuration):
   - `SQL_CONNECTION_STRING`, `SHAREPOINT_SITE_URL`, `SHAREPOINT_EXCEL_PATH`
   - `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`, `IGENTIC_ENDPOINT`
   - SharePoint: `AZURE_CLIENT_ID`, `SHAREPOINT_CERT_BASE64`, `SHAREPOINT_CERT_THUMBPRINT`

## Local Development

1. Copy `AzureFunctions/local.settings.json.example` → `local.settings.json` and fill values.
2. Copy `frontend1/config.local.js.example` → `frontend1/config.local.js` (and `accountsdashboard/config.local.js.example` → `accountsdashboard/config.local.js`).
3. Run Function App: `cd AzureFunctions && func start`
4. Serve frontends locally or use deployed Static Web Apps.

## Docs

- [docs/SETUP_DOCUMENT_INTELLIGENCE.md](docs/SETUP_DOCUMENT_INTELLIGENCE.md) – Document Intelligence setup
- [docs/FIX_UNAUTHORIZED_CLIENT.md](docs/FIX_UNAUTHORIZED_CLIENT.md) – Microsoft login troubleshooting
- [AzureFunctions/SHAREPOINT_CERT_SETUP.md](AzureFunctions/SHAREPOINT_CERT_SETUP.md) – SharePoint certificate auth
- [AzureFunctions/create_invoices_table.sql](AzureFunctions/create_invoices_table.sql) – PostgreSQL schema
- [AzureFunctions/migrations/](AzureFunctions/migrations/) – DB migrations
