# Set up Azure Document Intelligence and connect to the flow

This guide walks you through creating a Document Intelligence resource in Azure and wiring it to the invoice upload pipeline.

## 1. Create the Document Intelligence resource in Azure

1. **Open Azure Portal**  
   Go to [https://portal.azure.com](https://portal.azure.com) and sign in.

2. **Create a new resource**  
   - Click **Create a resource**.
   - Search for **Document Intelligence** (or **Form Recognizer**).
   - Select **Document Intelligence** (Microsoft, Cognitive Services).
   - Click **Create**.

3. **Project details**  
   - **Subscription:** Azure subscription 1 (or the one you use for InvoiceAutomation).
   - **Resource group:** Use **InvoiceAutomation** (or create one, e.g. `InvoiceAutomation`).

4. **Instance details**  
   - **Region:** Prefer **West US 2** (same as your Function App) for lower latency.
   - **Name:** Choose a unique name, e.g. `invoice-di-prod` or `invoicedocintelligence`.  
     This name becomes the host in the endpoint: `https://<name>.cognitiveservices.azure.com`.
   - **Pricing tier:** **Free (F0)** for testing, or **Standard (S0)** for production.

5. **Finish**  
   Click **Review + create**, then **Create**. Wait until the resource is deployed.

## 2. Get endpoint and key

1. Open the new **Document Intelligence** resource in the portal.
2. In the left menu, go to **Keys and Endpoint** (under *Resource Management*).
3. Copy:
   - **Endpoint**  
     Example: `https://invoice-di-prod.cognitiveservices.azure.com/`  
     Use the value as-is (with or without trailing slash; the app normalizes it).
   - **KEY 1** (or KEY 2)  
     Use this as `AZURE_DI_KEY`.

## 3. Configure the Function App

1. In Azure Portal, open your **Function App** (e.g. **InvoiceAutomation**).
2. Go to **Settings** → **Configuration** (or **Environment variables**).
3. Under **Application settings**, add or update:

   | Name                 | Value                                                                 |
   |----------------------|-----------------------------------------------------------------------|
   | **AZURE_DI_ENDPOINT**| Your Document Intelligence **Endpoint** (e.g. `https://invoice-di-prod.cognitiveservices.azure.com/`) |
   | **AZURE_DI_KEY**     | Your Document Intelligence **KEY 1** (or KEY 2)                      |

4. Click **Save** and confirm. The Function App will restart and use the new settings.

## 4. How it’s used in the flow

- **Upload** (e.g. `frontend1` → `api/upload`) receives the PDF.
- The function calls **Document Intelligence** with the PDF bytes and the **prebuilt-invoice** model.
- DI returns extracted text and structured fields (invoice number, vendor, amounts, dates, etc.).
- That result is passed to **iGentic** and is also stored in the **JSON backup** in SharePoint.

Required app settings for DI:

- `AZURE_DI_ENDPOINT` – Document Intelligence endpoint URL.
- `AZURE_DI_KEY` – Document Intelligence key.

If either is missing or wrong, the pipeline continues with empty extracted data and `"status": "no_di"` in the log; once set correctly, DI will run and the JSON will contain real extracted content.
