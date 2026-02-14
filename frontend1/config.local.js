// IMPORTANT: Replace with your actual Function App URL
// Get this from: Azure Portal → InvoiceAutomation (Function App) → Overview → URL
// Example: https://invoiceautomation.azurewebsites.net
window.APP_CONFIG = {
    apiBaseUrl: "https://invoiceautomation.azurewebsites.net",  // ← UPDATE THIS with your Function App URL
    clientId: "YOUR_AZURE_AD_CLIENT_ID",
    redirectUri: window.location.origin + "/"
};
