import logging
import azure.functions as func
import json
import os
from datetime import datetime
import requests
import msal

def get_app_access_token():
    """Get application-only access token using client credentials"""
    client_id = os.environ.get('AZURE_CLIENT_ID')
    client_secret = os.environ.get('AZURE_CLIENT_SECRET')
    tenant_id = os.environ.get('AZURE_TENANT_ID')
    
    if not all([client_id, client_secret, tenant_id]):
        raise Exception("Missing Azure AD credentials in environment variables")
    
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    scope = ["https://graph.microsoft.com/.default"]
    
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret
    )
    
    result = app.acquire_token_for_client(scopes=scope)
    
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception(f"Failed to acquire token: {result.get('error_description')}")

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('LoadData function processing a request.')

    try:
        # Parse request - NO LONGER ACCEPTING USER ACCESS TOKEN
        files = req.files.getlist('files')
        user_email = req.form.get('userEmail')
        
        if not files or not user_email:
            return func.HttpResponse(
                json.dumps({"error": "Missing required parameters"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # SharePoint configuration from environment variables
        site_id = os.environ.get('SHAREPOINT_SITE_ID')
        
        if not site_id:
            return func.HttpResponse(
                json.dumps({"error": "SharePoint configuration missing"}),
                status_code=500,
                mimetype="application/json"
            )
        
        # Get application access token (not user token)
        try:
            access_token = get_app_access_token()
        except Exception as e:
            logging.error(f"Failed to get app token: {str(e)}")
            return func.HttpResponse(
                json.dumps({"error": "Authentication failed"}),
                status_code=500,
                mimetype="application/json"
            )
        
        # Sanitize email for folder name
        folder_name = user_email.replace('@', '_').replace('.', '_')
        
        # Check if user folder exists, create if not
        folder_path = f"Documents/{folder_name}"
        folder_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{folder_path}"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Try to get folder, create if doesn't exist
        folder_response = requests.get(folder_url, headers=headers)
        
        if folder_response.status_code == 404:
            # Create folder
            create_folder_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/Documents/children"
            folder_data = {
                "name": folder_name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "rename"
            }
            create_response = requests.post(create_folder_url, headers=headers, json=folder_data)
            
            if create_response.status_code not in [200, 201]:
                logging.error(f"Failed to create folder: {create_response.text}")
                return func.HttpResponse(
                    json.dumps({"error": "Failed to create user folder"}),
                    status_code=500,
                    mimetype="application/json"
                )
        
        # Upload files
        uploaded_files = []
        allowed_extensions = ['.pdf', '.png', '.jpg', '.jpeg']
        
        for file in files:
            file_name = file.filename
            file_extension = os.path.splitext(file_name)[1].lower()
            
            # Validate file type
            if file_extension not in allowed_extensions:
                logging.warning(f"Rejected file {file_name} - unsupported format")
                continue
            
            file_content = file.read()
            
            # Validate file size (10MB limit)
            if len(file_content) > 10 * 1024 * 1024:
                logging.warning(f"Rejected file {file_name} - exceeds 10MB limit")
                continue
            
            # Upload file to SharePoint using APP credentials
            upload_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{folder_path}/{file_name}:/content"
            
            upload_headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/octet-stream'
            }
            
            upload_response = requests.put(upload_url, headers=upload_headers, data=file_content)
            
            if upload_response.status_code in [200, 201]:
                uploaded_files.append({
                    "name": file_name,
                    "size": len(file_content),
                    "uploadDate": datetime.utcnow().isoformat()
                })
            else:
                logging.error(f"Failed to upload {file_name}: {upload_response.text}")
        
        return func.HttpResponse(
            json.dumps({
                "success": True,
                "uploadedFiles": uploaded_files,
                "message": f"Successfully uploaded {len(uploaded_files)} file(s)"
            }),
            status_code=200,
            mimetype="application/json"
        )
        
    except Exception as e:
        logging.error(f"Error in LoadData function: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
