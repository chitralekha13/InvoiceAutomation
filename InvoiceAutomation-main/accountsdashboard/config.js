// Accounts Portal configuration
// Copy to config.local.js and adjust for local development
window.APP_CONFIG = {
    clientId: "YOUR_AZURE_AD_APP_CLIENT_ID",
    redirectUri: window.location.origin + "/accountsdashboard/index.html",
    apiBaseUrl: "https://YOUR_FUNCTION_APP.azurewebsites.net"
};
