# Azure AD Application Permissions Setup Guide

## Problem
SharePoint upload fails with:
```
ValueError: Microsoft Graph token has no application roles (roles claim missing/empty).
```

The token shows `roles=None`, indicating the app registration lacks Microsoft Graph Application permissions.

---

## Your App Registration Details
- **Client ID**: `725021b2-8178-4266-9e68-8d39ce3b5a84`
- **Tenant ID**: `59b817d0-e4a9-4a51-b17e-3e60fc07b19b`
- **Auth Method**: Certificate-based (X.509)

**⚠️ IMPORTANT**: These are the **backend Function App** credentials from your logs. Do NOT use the frontend config values (different app registration).

---

## Step-by-Step Fix

### Step 1: Access Azure Portal
1. Go to [https://portal.azure.com](https://portal.azure.com)
2. Sign in with your tenant admin account (required for Admin consent)
3. Search for **"App registrations"** in the top search bar
4. Click **App registrations**

### Step 2: Locate Your App Registration
1. In the App registrations page, click **All applications** tab (if not already selected)
2. Search for the Client ID: `725021b2-8178-4266-9e68-8d39ce3b5a84`
3. **⚠️ CRITICAL**: This is the **backend Function App** registration, NOT the frontend one
4. Click on the app name to open its details page
5. **Verify the Directory (tenant)** shows the correct tenant ID: `59b817d0-e4a9-4a51-b17e-3e60fc07b19b`

### Step 3: Add Microsoft Graph Application Permissions
1. In the left sidebar, click **API permissions**
2. Click the blue **+ Add a permission** button
3. In the "Request API permissions" panel:
   - Click **Microsoft Graph**
   - Select **Application permissions** (NOT "Delegated permissions")

### Step 4: Add Required Permissions

Search for and **select** each of these permissions:

| Permission | Purpose |
|-----------|---------|
| `Sites.ReadWrite.All` | Full SharePoint site read/write access |
| `Files.ReadWrite.All` | File operations across the tenant |

**Steps for each**:
1. Type the permission name in the search box (e.g., "Sites.ReadWrite.All")
2. Check the checkbox next to the permission
3. Repeat for the next permission

After selecting both, click **Add permissions** button at the bottom.

### Step 5: Grant Admin Consent
⚠️ **This step requires tenant admin privileges.**

1. Back on the **API permissions** page, you should now see both permissions listed but with a warning icon
2. Click the blue **Grant admin consent for [Your Tenant Name]** button
3. Click **Yes** in the confirmation dialog
4. Wait for the page to reload—the warning icons should change to green checkmarks

**Status should show**:
- ✅ `Sites.ReadWrite.All` – Granted (green checkmark)
- ✅ `Files.ReadWrite.All` – Granted (green checkmark)

### Step 6: Create or Recreate the Certificate
If you need to create a new certificate, follow these steps.

#### Option A: Create a certificate with PowerShell (Windows)
1. Open PowerShell as your user.
2. Run these commands to create a self-signed certificate and export it:

```powershell
$cert = New-SelfSignedCertificate -Subject "CN=InvoiceAutomationGraphCert" -KeyExportPolicy Exportable -KeySpec Signature -KeyLength 2048 -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears(2)
$pwd = ConvertTo-SecureString -String "P@ssw0rd!" -Force -AsPlainText
$pfxPath = "$env:USERPROFILE\invoiceautomation_graph_cert.pfx"
Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $pwd
Export-Certificate -Cert $cert -FilePath "$env:USERPROFILE\invoiceautomation_graph_cert.cer"
```

> **Note**: The `CN=InvoiceAutomationGraphCert` is just a descriptive name for the certificate. It doesn't need to match your app registration name or any specific Azure resource. Azure AD identifies your app by the Client ID (`725021b2-8178-4266-9e68-8d39ce3b5a84`), not by the certificate's Common Name.

3. Copy the certificate thumbprint:

```powershell
$cert.Thumbprint
```

4. Remove spaces and use that value for `SHAREPOINT_CERT_THUMBPRINT`.


#### Option B: Create certificate with OpenSSL (Linux/macOS)
1. Run:

```bash
openssl req -x509 -nodes -days 730 -newkey rsa:2048 -keyout invoiceautomation_graph_cert.key -out invoiceautomation_graph_cert.crt -subj "/CN=InvoiceAutomationGraphCert"
openssl pkcs12 -export -out invoiceautomation_graph_cert.pfx -inkey invoiceautomation_graph_cert.key -in invoiceautomation_graph_cert.crt -passout pass:P@ssw0rd!
```

2. Extract the thumbprint from the certificate file:

```bash
openssl x509 -in invoiceautomation_graph_cert.crt -noout -fingerprint -sha1
```

3. Remove the colons and use the resulting value for `SHAREPOINT_CERT_THUMBPRINT`.

#### Upload the certificate to Azure AD
1. In the Azure Portal, go to your App registration.
2. Click **Certificates & secrets**.
3. Under the **Certificates** tab, click **Upload certificate**.
4. Upload the `.cer` file (`invoiceautomation_graph_cert.cer`).

> Azure AD only needs the public certificate. Do not upload the `.pfx` here.

#### Set the private key in Function App settings
The Function App requires the private key in base64 form.

1. Convert the `.pfx` to base64:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\invoiceautomation_graph_cert.pfx")) | Out-File -Encoding ascii "$env:USERPROFILE\invoiceautomation_graph_cert.b64"
```

Or on Linux/macOS:

```bash
base64 invoiceautomation_graph_cert.pfx > invoiceautomation_graph_cert.b64
```

2. Copy the content of `invoiceautomation_graph_cert.b64` into the Function App setting `SHAREPOINT_CERT_BASE64`.
3. Set `SHAREPOINT_CERT_THUMBPRINT` to the cleaned certificate thumbprint (no spaces or colons).

### Step 7: Verify Certificate Configuration
1. In the left sidebar, click **Certificates & secrets**
2. Click the **Certificates** tab
3. Verify that your certificate is listed and the thumbprint matches `SHAREPOINT_CERT_THUMBPRINT` in your Function App settings
4. **Thumbprint format**: Remove all spaces from the certificate thumbprint

**Example**:
```
Raw thumbprint: AB CD EF 01 23 45 67 89 AB CD EF 01 23 45 67 89 AB CD EF 01
Cleaned: ABCDEF0123456789ABCDEF0123456789ABCDEF01
```

---

## Step 8: Deploy & Test

### Option A: Automatic Redeployment (Recommended)
1. Push a commit to `main` branch in GitHub
2. GitHub Actions automatically redeploys the Function App (token cache expires after changes)

```bash
git commit --allow-empty -m "Redeploy after Azure AD permissions update"
git push origin main
```

### Option B: Manual Function App Restart
1. Go to [Azure Portal](https://portal.azure.com) → Function App (invoiceautomation)
2. Click **Restart** button
3. Wait for restart to complete (~30 seconds)

### Option C: Wait for Token Expiration
- Existing tokens are cached for 1 hour
- The next upload attempt after 1 hour will use a fresh token with the new permissions

### Test Upload
1. Upload an invoice via the vendor portal
2. Check Function App logs: should now show `roles=` with a list of roles (not `None`)

---

## Verification: What to Look For

### ✅ Success
Logs should show:
```
[Information] Graph token claims: aud=https://graph.microsoft.com tid=59b817d0-e4a9-4a51-b17e-3e60fc07b19b appid=725021b2-8178-4266-9e68-8d39ce3b5a84 roles=sites.readwrite.all,files.readwrite.all
```

### ❌ Still Failing
Logs still show:
```
[Information] Graph token claims: ... roles=None
```

**If still failing after 1+ hour**:
1. Verify you granted **Admin consent** (not just added the permissions)
2. Check the certificate thumbprint exactly matches (no extra spaces)
3. Restart the Function App or wait another hour for cache expiration
4. Check Azure AD audit logs for permission grant errors

---

## Troubleshooting

### Issue: "Grant admin consent" button is grayed out
**Solution**: You don't have tenant admin rights. Contact your Azure AD admin to grant Admin consent.

### Issue: Certificate thumbprint mismatch
**Steps**:
1. Get the actual certificate thumbprint from Function App settings
2. In Azure Portal, go Certificates & secrets → Certificates tab
3. Click the certificate to see its thumbprint
4. Copy exactly (including hyphens), remove all spaces
5. **Your thumbprint**: `6291529983AF1679246CDAB8BE2100E5E7808A49`

### Issue: Application showing "Organization requires administrator consent"
**Solution**: This is expected for sensitive Microsoft Graph permissions. Click "Grant admin consent" again to confirm.

### Issue: Still no roles after 2+ hours
**Action items**:
1. **Check API permissions page** – Are both permissions showing with green checkmarks?
2. **Verify tenant match** – Is SHAREPOINT_CERT_THUMBPRINT from a certificate issued in the same tenant?
3. **Contact Microsoft Support** – If permissions are correct but token still has no roles, there may be a policy or certificate issue

### Issue: Wrong App Registration Modified
**Symptoms**: You added permissions but still get `roles=None`
**Cause**: Your app has separate frontend and backend app registrations. You modified the wrong one.
**Solution**:
- **Frontend app** (for user login): `f08d79c7-a658-40f6-8716-857850879ba5` in tenant `a8e5d571-43e8-4c3c-96be-344156cf6887`
- **Backend app** (for SharePoint): `725021b2-8178-4266-9e68-8d39ce3b5a84` in tenant `59b817d0-e4a9-4a51-b17e-3e60fc07b19b`
- **Always modify the backend app** for SharePoint permissions (this guide uses the correct backend values)

---

## Related Configuration

### Function App Settings Required
Ensure these are set in your Azure Function App configuration:

```
SHAREPOINT_CERT_BASE64      = MIIKQgIBAzCCCf4GCSqGSIb3DQEHAaCCCe8EggnrMIIJ5zCCBgAGCSqGSIb3DQEHAaCCBfEEggXtMIIF6TCCBeUGCyqGSIb3DQEMCgECoIIE/jCCBPowHAYKKoZIhvcNAQwBAzAOBAgd9/SMJd+a8gICB9AEggTYawVFYYKlu+g/tHIAy/Q1vyzNmWWF/jQ+yHtYICrkiuOb87ACO7cK4rw8KseibGAcopttQ3+1+VyWCBuQkkdBNJnZOEHSR8rUT5TLvRbpLxXA4xyTh4SpH2yVhwX6pGhxFzpzUmrtI1tmo8Mo3AFQVVNxFKF3yj+8hhE6gesIGQrww5/3sSyrZdaUB2sdaqQTunnBDUbcTiPgNk1Ts9ckmoXCVUo+FjQuMuhU3c8Bi/Y8kljzYALxZxrZG2zibbKHvGUgDgYTPjKZMn2HoBhJXsEDWuq94fvYeHqyCfdixZShuJYzNKuLcFGzROdA/Uuj3nrSWNb/RN3nywSdd3uX0+kEvfS2A9BTMYC09X4UunHDwzMSIgwmM4wmOdXBwuDlwjOwmHCJCNCOWxHqDGbfsjp1L+lsawa9mKRGu/FICoEoWIF1EKStic7jWz9sD5N2uIJZi9PAEB/80thOF4wZlyXuD/cCGFCvIazky3i9fLxj1eKDfkkO7D2E9pDayw6mfaxyWwgb3+qMJtOupRxtggeKIOLrZbVvPUq5BBnmtIQEZS7C5iqTFVjM0kvRUJUD+x5NOpGxSRpeTZSarpF2SBuuj30uj4Fra+1jjPckcM0VHF4zvuXWDTghYvks6bDPejAPr04rC68pYw/ndrCcP4nORssQLTgCt8nkWuaihPiuZKr5Bzk6n64pabAZdGhN5Kjw3forwRr9o0zvqaRxRFe0CUnVkhdHPs57J2Q9Pt6II1zocdkYsNBL+u0Nl0172vqXN3nGbaogcmvpbTvOFJ2sg1AOVYL7y8S3qm7nxTO7sWafBnDb0vNprxK1mwmYNI1rmadWCzsbFjfyFUZ8yVakGTAFfpxhxLcFjnKIsFkbV4LouhTWTR0CrZ/thQ4xnSzxMFlptzogBznOLhEZIvl6P6yx03CVL55uEvtRRDK6k8piqw3rbg1ePmubIvr45et6ZlvhWTIaaDIULckgyi7suIhHAxk4vkeWQR1PkTjQIyZJ/Y6iVQGVKjA5jSXgDXAh5n35zpBVm2/QbfkRJyetuodih1hM00KtrFiFcFdiY3GSdgt2242h8XynI1CQue6layTiT7a61wP3w2TDyvKEzcAyWigHvzZROA9NqeyKiMzEmlzQZDjLkjWbPSUshOt/U2CKOkCWGK/b2R0EJLcTPYx2fjKCGnQvZhifssGVaKa2+RdT4LkVsuVA2gUop71JGuvDkoIrgbes2pJSwIFqq+afiGc1gsxzbQhndY4xnCo8VgotGsydSywl1/4Ub5lntuu5NJ56sxE0UDiEN48bkAZh4QjQQlW5JWw4+ih3curRNEQ4QbW7LCMWbQWWyfymFJsk44AT75arCXuPBCgdgPVUaubddkB8GRuswrUXNlWGW4IMYVIpv6kYPfASy7Klq0l8/1hoyS15MrC8G+kyaBmeR+Y2y7f1eoWdOXwmyvaltPhiNn1AIB1JSqLOfYzLNIN/cT/kOZWvbcIASlpj0aA0mjUG0J5KoT4bVfvPkevGa9XJqP9PScACwE9PgN4+cEN4S2NM65QxWgCKi3SMdSm9unB3xJ7vbn6o0aOeol6I01oT0ykkGjAXgqojTSePh2Ch2nk/z+YwP6fREOWXXbyUiA037+QG+Bx2Hl/4acB8KfIEqTGB0zATBgkqhkiG9w0BCRUxBgQEAQAAADBdBgkqhkiG9w0BCRQxUB5OAHQAZQAtADYANgA3ADcAYQBhAGEAZAAtADUAMQBiADQALQA0ADMAMgBmAC0AOAA4AGIAYQAtAGUAZQA2AGMANgBkAGUAZQBkADYAYgA5MF0GCSsGAQQBgjcRATFQHk4ATQBpAGMAcgBvAHMAbwBmAHQAIABTAHQAcgBvAG4AZwAgAEMAcgB5AHAAdABvAGcAcgBhAHAAaABpAGMAIABQAHIAbwB2AGkAZABlAHIwggPfBgkqhkiG9w0BBwagggPQMIIDzAIBADCCA8UGCSqGSIb3DQEHATAcBgoqhkiG9w0BDAEDMA4ECNVCtFWIekjzAgIH0ICCA5iL5iKsOvJHGrxur6O+tOdHNQNFGHXX4bVC6cgV6G0uYwERfAbscLtHwib/r2xNNjwh0cTcteNHh4vkJtlNTOknYMtyn85s9pvoQx57gQpK3LQL7O7OUFbLNuC4BGWRa1PfoFP+DwWjJhxqPkA1q7ihYQ0lPW8yE5VQFkFge4isXJhXThQ7I+1InTiup0kWkQA0XBxl3jGQBC0yXmbu43+EgvxPsaP8tQfZxIuSzsxfGto2o60r9SPdwZ1du+FGOidNV6ffESbqp2cRTHEFnSRfgLvXlK2tOEHhWOwU1Q39RdLdtaXVSd8cYeaZSupHfrei2vqJhw9muizNQb+eOskLqSJnCrqN7a0JUlkvi4oQKEvisQlcjMTsfUDj/1bxsFix8bQmuSZGphshwN4QuabjohERNqUpjy4lcNg6KJwSWzKvBp5oKpRgzWJ/IPmmRauMLXEEflfm6hpohA1+CRQdkbo40GLwFnJ2CWgDRX6K1ZB+KYje/HI3XCwjK7ESjsZOjKc0UWOv//tDwyKme4Y9S/M4If6OBabgJ0C31c9ktRdNZw5sCXdal/ZagWBpPJwKm1zoBYFOG/pYJBe1RSvaHvaFMQ48UBMirSXG+QCFpJMKaXgOVJdsW+fre6u3a/CWjz+J3dvqAk9WWQCVp9YPQiBlpIoPh67mkTWPJTXmrGa3KfhXKl4ICB0IHGH2XvOMLYhaciu6Rb6P/Z9EW2svCbruuqGkbk/ZnBh/fBcGtbrhIAqwINIH0aob73+1QbXe/Jc6xrdZww4z+4ee+VezWfG0gumLBIodY/Lv1sHqTZ8PbwApbncL8HfnXQWFay8KXVujNBfg180FPXLU60yfB8qXLW08B7blrHxK/7HC9xJzdSHoQhWQh77csXwCTVmjp16oQdI5sjsgsKxPIZBeEA493L9kdvhYf1RFRw2FmqyGWZHdEDntzkYJS/q704Cg6HJSKkwS4VL5WsRiVV8wk5oX880dQ2fT6x17KsfE3QSGqwm2njupSD+HSjLMvZitt/biMf8D1flnzT9eEoGVP0A0aFaUXA+xVhdjGL96MWk1vqnX1QWtkQG+tCdCNkdYDjDFipPl2s4pHqMWjoUosXq3ylRnDofFaMQW9RoQ3r2dXghzuPnycRH+Ad52NSSYk2yOvrWEXJgSQEYWoJPy2v8eJHFEO3QcO4+932sgHUTxCmJ9kNiO6ksJIxubKSYZyNuWFVcFHjA7MB8wBwYFKw4DAhoEFHfncgbH64JXLOylrSJC5I+zyWyxBBTVcKAOyHukhfjUO2d6ogk7YBNXVgICB9A=
SHAREPOINT_CERT_THUMBPRINT  = 6291529983AF1679246CDAB8BE2100E5E7808A49
SHAREPOINT_SITE_URL         = https://invoiceautomation.sharepoint.com/sites/Accounts
AZURE_CLIENT_ID             = 725021b2-8178-4266-9e68-8d39ce3b5a84
AZURE_AUTHORITY             = https://login.microsoftonline.com/{tenant_id}
```

### Code Reference
The error is raised in [shared/helpers.py](AzureFunctions/shared/helpers.py#L119):
- Token acquisition uses certificate credentials with MSAL
- `roles` claim is extracted from the JWT payload
- Missing or empty `roles` indicates permission/consent issue, not certificate issue

---

## Additional Resources

- [Microsoft Graph Application Permissions](https://learn.microsoft.com/en-us/graph/permissions-reference)
- [Certificate-based authentication for Azure AD](https://learn.microsoft.com/en-us/entra/identity-platform/certificate-credentials)
- [Admin consent flow documentation](https://learn.microsoft.com/en-us/entra/identity-platform/application-consent-experience)
