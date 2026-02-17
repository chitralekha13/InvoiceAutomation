// Vendor portal – Function App API configuration
// For local dev: copy config.local.js.example to config.local.js and set values
// For production: pipeline overwrites this with secrets (AZURE_CLIENT_ID, etc.)
window.APP_CONFIG = {
    apiBaseUrl: "https://invoiceautomation-bdcudzfpe9cpf4d5.westus2-01.azurewebsites.net/",
    clientId: "",
    redirectUri: window.location.origin + "/index.html"
};




