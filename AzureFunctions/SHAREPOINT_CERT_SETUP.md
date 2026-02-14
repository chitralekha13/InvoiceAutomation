# SharePoint Certificate Authentication Setup

SharePoint Add-ins (appregnew/appinv) are retired. For app-only access to SharePoint REST API with an Azure AD app, you **must use certificate authentication**—client secret does not work.

---

## Step 1: Create a Self-Signed Certificate

### Option A: Using OpenSSL (Windows, Mac, Linux)

```bash
# Create certificate and private key (valid 1 year)
openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 -keyout privateKey.key -out selfsigncert.crt -subj "/CN=InvoiceAutomation"

# Combine into PEM format (cert + private key in one file)
# Windows (PowerShell):
Get-Content selfsigncert.crt, privateKey.key | Set-Content -Path cert.pem -Encoding UTF8

# Mac/Linux:
cat selfsigncert.crt privateKey.key > cert.pem
```

### Option B: Using Azure Cloud Shell

1. Open [Azure Cloud Shell](https://shell.azure.com)
2. Run:
   ```bash
   openssl req -x509 -sha256 -nodes -days 365 -newkey rsa:2048 -keyout privateKey.key -out selfsigncert.crt
   cat selfsigncert.crt privateKey.key > cert.pem
   ```
3. Download `cert.pem` and `selfsigncert.crt`

---

## Step 2: Get the Certificate Thumbprint

### Windows (PowerShell)

```powershell
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2("C:\path\to\selfsigncert.crt")
$cert.Thumbprint
```

### OpenSSL

```bash
openssl x509 -in selfsigncert.crt -noout -fingerprint -sha1
# Remove colons from output, e.g. AA:BB:CC:DD -> AABBCCDD
```

---

## Step 3: Register Certificate in Azure AD App

1. Go to [Azure Portal](https://portal.azure.com) → **Microsoft Entra ID** → **App registrations**
2. Open your SharePoint app (or create one in the SharePoint tenant)
3. Go to **Certificates & secrets**
4. Click **Certificates** tab → **Upload certificate**
5. Upload the **.crt** (or .cer) file—**not** the .pem with private key
6. Copy the **Thumbprint** shown (remove colons if needed for the app setting)

---

## Step 4: Add SharePoint API Permissions

1. In the app → **API permissions** → **Add a permission**
2. **SharePoint** → **Application permissions** → add `Sites.FullControl.All`
3. Click **Grant admin consent for [tenant]**

---

## Step 5: Encode Certificate for Function App

The **cert.pem** file (cert + private key) must be base64-encoded for the app setting:

### Windows (PowerShell)

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\path\to\cert.pem"))
```

### Mac/Linux

```bash
base64 -w 0 cert.pem
```

Copy the output—it will be a long string.

---

## Step 6: Configure Function App Settings

In **Function App** → **Configuration** → **Application settings**, set:

| Setting | Value |
|---------|-------|
| `SHAREPOINT_SITE_URL` | `https://invoiveautomation.sharepoint.com/sites/Accounts` |
| `AZURE_CLIENT_ID` | Your app's Application (client) ID |
| `SHAREPOINT_CERT_BASE64` | Base64-encoded cert.pem content |
| `SHAREPOINT_CERT_THUMBPRINT` | Certificate thumbprint (no colons) |
| `AZURE_TENANT_ID` or `SHAREPOINT_TENANT_NAME` | `59b817d0-e4a9-4a51-b17e-3e60fc07b19b` or `invoiveautomation.onmicrosoft.com` |

**Remove** `AZURE_CLIENT_SECRET` if you were using it for SharePoint—it is not used with certificate auth.

---

## Step 7: Redeploy and Test

1. Save Application settings and restart the Function App
2. Redeploy the Azure Functions code (with updated `helpers.py` and `msal` in requirements)
3. Test the upload again

---

## Security Notes

- Never commit `cert.pem` or `privateKey.key` to source control
- Store `SHAREPOINT_CERT_BASE64` only in Azure Application Settings or Key Vault
- Consider using Azure Key Vault for the certificate in production
- Rotate the certificate before it expires (e.g., 1 year)
