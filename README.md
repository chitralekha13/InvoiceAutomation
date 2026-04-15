# Invoice Automation

Invoice upload → Document Intelligence → iGentic → PostgreSQL → Dashboard + Excel.  
iGentic uses **one session per invoice** (sessionId = invoice_id); follow-ups (e.g. approved hours) use `continue_igentic_session()` so the same chat context is used.

## Structure

| Component | Folder | Deploy |
|-----------|--------|--------|
| Vendor Portal (upload, Microsoft login) | `frontend1/` | Static Web App |
| Accounts Dashboard | `accountsdashboard/` | Static Web App |
| Backend API | `AzureFunctions/` | Azure Functions |

## Deploy

Push to `main` → GitHub Actions deploy all three.

**GitHub Secrets:** `AZURE_CLIENT_ID`, `API_BASE_URL`, `AZURE_STATIC_WEB_APPS_API_TOKEN_*`, `AZURE_CREDENTIALS`, `AZURE_FUNCTIONAPP_PUBLISH_PROFILE`

**Function App Settings:** `SQL_CONNECTION_STRING`, `SHAREPOINT_SITE_URL`, `SHAREPOINT_EXCEL_PATH`, `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY`, `IGENTIC_ENDPOINT`, `SHAREPOINT_CERT_BASE64`, `SHAREPOINT_CERT_THUMBPRINT`

**Azure AD:** Add Redirect URI `https://<vendor-portal-url>/index.html`; set `signInAudience` to `AzureADandPersonalMicrosoftAccount` if using personal accounts.

**PostgreSQL:** Run `AzureFunctions/create_invoices_table.sql` and `AzureFunctions/migrations/001_add_template_addl_comments.sql` if needed.
