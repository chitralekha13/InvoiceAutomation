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

def list_user_files(token,user_email):
    headers={"Authorization":f"Bearer {token}"}
    folder_path=f"/{user_email}"
    url_folder=f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root:{folder_path}"
    r_folder=requests.get(url_folder,headers=headers)
    if r_folder.status_code!=200:
        return []
    url_files=f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drive/root:{folder_path}:/children"
    r_files=requests.get(url_files,headers=headers)
    r_files.raise_for_status()
    files=r_files.json().get("value",[])
    return [{"name":f["name"],"webUrl":f["webUrl"]} for f in files]

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        user_email=req.headers.get("x-ms-client-principal-name")
        if not user_email:
            return func.HttpResponse("User not authenticated",status_code=401)
        token=get_access_token()
        files=list_user_files(token,user_email)
        return func.HttpResponse(json.dumps(files),mimetype="application/json",status_code=200)
    except Exception as ex:
        logging.error(str(ex))
        return func.HttpResponse(f"Server error: {str(ex)}",status_code=500)
