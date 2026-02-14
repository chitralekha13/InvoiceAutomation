# Full Code Review Checklist – Pre-Push

## ✅ Flow Verification

### Vendor Portal (frontend1)
1. **Login (index.html)** → MSAL login with clientId, redirectUri → stores accessToken, userEmail
2. **Upload (upload.html)** → POST to `apiBaseUrl + '/api/upload'` with FormData → Function App
3. **Retrieve (retrieve.html)** → POST to `apiBaseUrl + '/api/getdata'` with action list/download → Function App

### Function App (AzureFunctions)
1. **upload** → Parse multipart → SharePoint (cert auth) → optional SQL → Document Intelligence → iGentic → success
2. **getdata** → list: get_invoices_by_vendor; download: get_invoice → returns documents/URL
3. **dashboard_data / get_invoices** → get_dashboard_payload → rows + metrics (empty if no DB)

### Accounts Portal (accountsdashboard)
1. **Login** → Simple form → stores userName, userEmail in sessionStorage → redirects to dashboard
2. **Dashboard** → Fetches from apiBaseUrl + '/api/dashboard/data' → displays metrics and rows

---

## ✅ Config Loading (Fixed)

- **index.html**: config.js (blocking) → config.local.js (override if exists)
- **upload.html, retrieve.html**: config.js → config.local.js (override)
- **dashboard.html**: config.local.js → config.js fallback

---

## ✅ Pre-Push Checklist

| Item | Status |
|------|--------|
| AZURE_CLIENT_ID in GitHub Secrets | Required for vendor login |
| AZURE_STATIC_WEB_APPS_API_TOKEN_KIND_MUD_03BE2C81E | Required for frontend1 deploy |
| Azure AD app redirect URI | Add Static Web App URL + /index.html |
| Function App CORS | Allow Static Web App origin |
| SHAREPOINT_CERT_BASE64, SHAREPOINT_CERT_THUMBPRINT | Required for SharePoint upload |
| SQL_CONNECTION_STRING | Optional – omit for SharePoint-only mode |

---

## Files Modified (Summary)

See "Files Written To" section below.
