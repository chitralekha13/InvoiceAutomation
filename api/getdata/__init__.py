import logging
import azure.functions as func
import json
import os
import requests

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('GetData function processing a request.')

    try:
        # Parse request body - using USER's delegated access token
        req_body = req.get_json()
        user_email = req_body.get('userEmail')
        access_token = req_body.get('accessToken')
        action = req_body.get('action', 'list')
        document_id = req_body.get('documentId')
        
        if not user_email or not access_token:
            return func.HttpResponse(
                json.dumps({"error": "Missing required parameters"}),
                status_code=400,
                mimetype="application/json"
            )
        
        # SharePoint configuration
        site_id = os.environ.get('SHAREPOINT_SITE_ID')
        
        if not site_id:
            return func.HttpResponse(
                json.dumps({"error": "SharePoint configuration missing"}),
                status_code=500,
                mimetype="application/json"
            )
        
        # Sanitize email for folder name - ensures user isolation
        folder_name = user_email.replace('@', '_').replace('.', '_')
        folder_path = f"Documents/{folder_name}"
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Handle different actions
        if action == 'list':
            # List all files in user's folder only
            list_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{folder_path}:/children"
            
            response = requests.get(list_url, headers=headers)
            
            if response.status_code == 404:
                # Folder doesn't exist yet
                return func.HttpResponse(
                    json.dumps({"documents": []}),
                    status_code=200,
                    mimetype="application/json"
                )
            
            if response.status_code != 200:
                logging.error(f"Failed to list files: {response.text}")
                return func.HttpResponse(
                    json.dumps({"error": "Failed to retrieve documents"}),
                    status_code=500,
                    mimetype="application/json"
                )
            
            data = response.json()
            documents = []
            
            for item in data.get('value', []):
                if 'file' in item:  # Only include files, not folders
                    documents.append({
                        "id": item['id'],
                        "name": item['name'],
                        "size": item.get('size', 0),
                        "uploadDate": item.get('createdDateTime'),
                        "downloadUrl": item.get('@microsoft.graph.downloadUrl')
                    })
            
            return func.HttpResponse(
                json.dumps({"documents": documents}),
                status_code=200,
                mimetype="application/json"
            )
        
        elif action == 'download':
            if not document_id:
                return func.HttpResponse(
                    json.dumps({"error": "Document ID required"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            # SECURITY: Get file info and verify it belongs to user's folder
            file_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{document_id}"
            
            response = requests.get(file_url, headers=headers)
            
            if response.status_code != 200:
                logging.error(f"Failed to get file info: {response.text}")
                return func.HttpResponse(
                    json.dumps({"error": "Failed to retrieve document"}),
                    status_code=500,
                    mimetype="application/json"
                )
            
            file_data = response.json()
            
            # SECURITY CHECK: Verify file is in user's folder
            file_path = file_data.get('parentReference', {}).get('path', '')
            expected_path_part = f"/drive/root:/Documents/{folder_name}"
            
            if expected_path_part not in file_path:
                logging.warning(f"User {user_email} attempted to access file outside their folder: {file_path}")
                return func.HttpResponse(
                    json.dumps({"error": "Access denied"}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            download_url = file_data.get('@microsoft.graph.downloadUrl')
            
            if not download_url:
                return func.HttpResponse(
                    json.dumps({"error": "Download URL not available"}),
                    status_code=500,
                    mimetype="application/json"
                )
            
            # Download file content
            file_response = requests.get(download_url)
            
            if file_response.status_code != 200:
                return func.HttpResponse(
                    json.dumps({"error": "Failed to download file"}),
                    status_code=500,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                file_response.content,
                status_code=200,
                mimetype="application/octet-stream"
            )
        
        elif action == 'delete':
            if not document_id:
                return func.HttpResponse(
                    json.dumps({"error": "Document ID required"}),
                    status_code=400,
                    mimetype="application/json"
                )
            
            # SECURITY: Get file info and verify it belongs to user's folder
            file_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{document_id}"
            
            response = requests.get(file_url, headers=headers)
            
            if response.status_code != 200:
                logging.error(f"Failed to get file info: {response.text}")
                return func.HttpResponse(
                    json.dumps({"error": "Failed to retrieve document"}),
                    status_code=500,
                    mimetype="application/json"
                )
            
            file_data = response.json()
            
            # SECURITY CHECK: Verify file is in user's folder
            file_path = file_data.get('parentReference', {}).get('path', '')
            expected_path_part = f"/drive/root:/Documents/{folder_name}"
            
            if expected_path_part not in file_path:
                logging.warning(f"User {user_email} attempted to delete file outside their folder: {file_path}")
                return func.HttpResponse(
                    json.dumps({"error": "Access denied"}),
                    status_code=403,
                    mimetype="application/json"
                )
            
            # Delete file
            delete_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/items/{document_id}"
            
            response = requests.delete(delete_url, headers=headers)
            
            if response.status_code not in [200, 204]:
                logging.error(f"Failed to delete file: {response.text}")
                return func.HttpResponse(
                    json.dumps({"error": "Failed to delete document"}),
                    status_code=500,
                    mimetype="application/json"
                )
            
            return func.HttpResponse(
                json.dumps({"success": True, "message": "Document deleted successfully"}),
                status_code=200,
                mimetype="application/json"
            )
        
        else:
            return func.HttpResponse(
                json.dumps({"error": "Invalid action"}),
                status_code=400,
                mimetype="application/json"
            )
        
    except Exception as e:
        logging.error(f"Error in GetData function: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
