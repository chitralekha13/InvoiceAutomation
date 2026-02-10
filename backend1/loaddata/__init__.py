import json
import logging
import azure.functions as func
import requests
import os

SITE_ID=os.environ.get("SITE_ID")
CLIENT_ID=os.environ.get("CLIENT_ID")
CLIENT_SECRET=os.environ.get("CLIENT_SECRET")
TENANT_ID=os.environ.get("TENANT_ID")
GRAPH_TOKEN_ENDPOINT="https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

def get_access_token():
    url=GRAPH_TOKEN_ENDPOINT.format(tenant_id=TENANT_ID)
    payload={'client_id':CLIENT_ID,'client_secret':CLIENT_SECRET,'scope':'https://graph.microsoft.com/.default','grant_type':'client_credentials'}
    r=requests.post(url,data=payload)
    r.raise_for_status()
    return r.json()['access_token']

def check_or_create_user_folder(token,user_email):
    headers={"Authorization":f"Bearer {token}"}
    folder_path=f"/{user_email}"
    url=f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root:{folder_path}"
    r=requests.get(url,headers=headers)
    if r.status_code==200:
        return True
    url_create=f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root/children"
    payload={"name":user_email,"folder":{},"@microsoft.graph.conflictBehavior":"rename"}
    r=requests.post(url_create,headers={**headers,"Content-Type":"application/json"},json=payload)
    r.raise_for_status()
    return True

def upload_file_to_user_folder(token,user_email,file_name,file_content):
    headers={"Authorization":f"Bearer {token}"}
    upload_url=f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root:/{user_email}/{file_name}:/content"
    r=requests.put(upload_url,headers=headers,data=file_content)
    r.raise_for_status()
    return r.json()

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        user_email=req.headers.get("x-ms-client-principal-name")
        if not user_email:
            return func.HttpResponse("User not authenticated",status_code=401)
        file=req.files.get("file")
        if not file:
            return func.HttpResponse("No file sent",status_code=400)
        token=get_access_token()
        check_or_create_user_folder(token,user_email)
        upload_file_to_user_folder(token,user_email,file.filename,file.read())
        return func.HttpResponse(f"File '{file.filename}' uploaded successfully to folder '{user_email}'",status_code=200)
    except Exception as ex:
        logging.error(str(ex))
        return func.HttpResponse(f"Server error: {str(ex)}",status_code=500)
