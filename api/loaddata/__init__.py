import logging
import azure.functions as func
import json
import os
from datetime import datetime
import requests

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('LoadData function processing a request.')

    try:
        # Parse request - using USER's delegated access token
        files = req.files.getlist('files')
        user_email = req.form.get('userEmail')
        access_token = req.form.get('accessToken')
        
        if not files or not user_email or not access_token:
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
        
        # Sanitize email for folder name - ensures user isolation
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
            
            # Upload file to SharePoint using USER's delegated token
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
