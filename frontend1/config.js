// Vendor portal – Function App API configuration
// For local dev: copy config.local.js.example to config.local.js and set values
// For production: pipeline overwrites this with secrets (AZURE_CLIENT_ID, etc.)
window.APP_CONFIG = {
    apiBaseUrl: "https://invoiceautomation-bdcudzfpe9cpf4d5.westus2-01.azurewebsites.net",
    clientId: "f08d79c7-a658-40f6-8716-857850879ba5",
    tenantId: "a8e5d571-43e8-4c3c-96be-344156cf6887",
    redirectUri: window.location.origin + "/index.html"
};
