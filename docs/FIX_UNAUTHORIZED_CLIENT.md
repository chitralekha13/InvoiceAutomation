# Fix: "unauthorized_client: The client does not exist or is not enabled for consumers"

This error appears when you click **"Sign in with Microsoft"** on the **Vendor Portal** (frontend1), not the Accounts Dashboard.

---

## Step 1: Identify Where the Error Appears

- **Vendor Portal** (upload invoices): URL like `https://kind-mud-03be2c81e.6.azurestaticapps.net` — uses Microsoft login  
- **Accounts Dashboard**: URL like `https://gray-forest-033ccce1e.6.azurestaticapps.net` — uses simple username/password (no Microsoft login)

If the error is on the **Vendor Portal**, continue with the steps below.

---

## Step 2: Check GitHub Secret for Client ID

1. Open your GitHub repo: **https://github.com/chitralekha13/InvoiceAutomation**
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Confirm that **`AZURE_CLIENT_ID`** exists.
4. If it is missing, add it:
   - Click **New repository secret**
   - Name: `AZURE_CLIENT_ID`
   - Value: the Application (client) ID from your Azure AD app (see Step 4)
5. If you are not sure whether the value is correct, update it with the correct Client ID from Azure.

---

## Step 3: Get the Correct Client ID from Azure

1. Go to **https://portal.azure.com** and sign in.
2. Search for **"App registrations"** and open it.
3. Find the app used for the Invoice Portal (often named "InvoiceAutomation" or similar).
4. Open the app and copy the **Application (client) ID**.
5. Make sure this value is set in GitHub as **`AZURE_CLIENT_ID`**.

---

## Step 4: Enable Personal Microsoft Accounts (for "consumers" error)

1. In **App registrations**, open the same app.
2. Click **Manifest** in the left menu.
3. Find the line `"signInAudience":` (around line 15–20).
4. Change the value to:
   ```json
   "signInAudience": "AzureADandPersonalMicrosoftAccount"
   ```
5. Click **Save** at the top.

This allows both work/school accounts and personal Microsoft accounts (outlook.com, live.com, etc.).

---

## Step 5: Add Redirect URI for the Vendor Portal

1. In the same app, click **Authentication**.
2. Under **Platform configurations**, click **Add a platform**.
3. Choose **Single-page application**.
4. Add this Redirect URI:
   ```
   https://kind-mud-03be2c81e.6.azurestaticapps.net/index.html
   ```
   (Use your actual Vendor Portal URL if it’s different.)
5. Click **Configure**.
6. Save the changes.

---

## Step 6: Redeploy the Vendor Portal

After changing the GitHub secret or app registration:

1. Go to **https://github.com/chitralekha13/InvoiceAutomation**
2. Click **Actions**.
3. Find the latest workflow run for the **frontend1** Static Web App.
4. Click **Re-run all jobs** (or push a small change to trigger a new deploy).

---

## Quick Checklist

| Step | Action |
|------|--------|
| 1 | Confirm the error is on the Vendor Portal (Sign in with Microsoft) |
| 2 | Ensure `AZURE_CLIENT_ID` is set in GitHub Secrets and is correct |
| 3 | Get the correct Client ID from App registrations in Azure Portal |
| 4 | Set `signInAudience` to `AzureADandPersonalMicrosoftAccount` in the app Manifest |
| 5 | Add the Vendor Portal URL as a Redirect URI in the app’s Authentication |
| 6 | Re-run the workflow or push a commit to redeploy |

---

## If It Still Fails

1. **Verify the config being used**
   - Open the Vendor Portal.
   - Press F12 → **Network** tab.
   - Refresh the page.
   - Find **config.js** and open it.
   - Confirm `clientId` is not empty and matches your Azure app’s Client ID.

2. **Verify your Vendor Portal URL**
   - In Azure Portal: **Static Web Apps** → your Vendor Portal app → **Overview**.
   - Copy the **URL** and ensure it matches the Redirect URI you added in Step 5.
