# Pipeline & Vendor Login Setup

## GitHub Secrets Required for Vendor Portal (frontend1)

The `azure-static-web-apps-kind-mud-03be2c81e` workflow deploys the **vendor portal**. For Microsoft login to work after deployment, add these secrets:

| Secret | Required | Description |
|--------|----------|-------------|
| **AZURE_STATIC_WEB_APPS_API_TOKEN_KIND_MUD_03BE2C81E** | Yes | Static Web App deployment token (from Azure Portal) |
| **AZURE_CLIENT_ID** | Yes | Azure AD app Client ID for MSAL login |
| **API_BASE_URL** | No | Function App URL (default: https://invoiceautomation-bdcudzfpe9cpf4d5.westus2-01.azurewebsites.net) |

### How to add secrets

1. GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret**
3. Add `AZURE_CLIENT_ID` with your Azure AD app registration Client ID (used for "Sign in with Microsoft")

### Azure AD app redirect URI

In your Azure AD app registration → **Authentication** → **Redirect URIs**, add:

- `https://<your-static-web-app>.azurestaticapps.net/index.html`

Example: `https://kind-mud-03be2c81e.azurestaticapps.net/index.html` (or your actual SWA URL)

Without this, MSAL login will fail with "AADSTS50011: The redirect URI specified in the request does not match".
