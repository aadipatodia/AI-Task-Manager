from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
import os
import json 
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow # Added missing import 

# Import functions from engine.py
# Removed 'tokens_col' from this list to fix the ImportError 
from engine import handle_message, SCOPES, REDIRECT_URI
from send_message import send_whatsapp_message 

load_dotenv()
app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
PROCESSED_MESSAGE_IDS = set()

@app.get("/")
async def home():
    return {"message": "WhatsApp Task Bot is running"}

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token")
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Forbidden")

@app.post("/webhook")
async def handle_webhook(request: Request):
    data = await request.json()
    print("Received webhook data:", data)
    
    if not data or "entry" not in data:
        return {"status": "EVENT_RECEIVED"}
    
    for entry in data["entry"]:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            
            if "statuses" in value:
                continue
            
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            if not phone_number_id:
                continue
                
            messages = value.get("messages", [])
            for message in messages:
                if "from" not in message:
                    continue
                
                msg_id = message.get("id")
                if not msg_id:
                    continue
                
                #deduplication guard
                if msg_id in PROCESSED_MESSAGE_IDS:
                    print(f"Duplicate message ignored: {msg_id}")
                    continue
                
                PROCESSED_MESSAGE_IDS.add(msg_id)
                    
                    
                sender_phone = message["from"]
                user_command = ""
                message_data = {}

                msg_type = message.get("type")

                if msg_type == "text":
                    text_body = message.get("text", {})
                    user_command = text_body.get("body", "")

                elif msg_type == "document":
                    doc = message.get("document", {})
                    if doc:
                        user_command = doc.get("caption", "").strip()
                        message_data = {"document": doc, "type": "document"}
                        
                elif msg_type == "image":
                    doc = message.get("image", {})
                    if doc:
                        user_command = doc.get("caption", "").strip()
                        message_data = {"image": doc, "type": "image"}

                if user_command.strip() or message_data:
                    # Circular import risk check: Ensure engine.py does not import from webhook.py
                    await handle_message(user_command, sender_phone, phone_number_id, message=message_data, full_message=message)

    return {"status": "EVENT_RECEIVED"}

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    state = request.query_params.get('state')
    
    # FIXED: Changed 'flow.from_client_secrets_file' to 'Flow.from_client_secrets_file'
    # The variable 'flow' was used before it was defined 
    flow = Flow.from_client_secrets_file(
        'client_secret.json',
        scopes=SCOPES,
        state=state
    )
    flow.redirect_uri = REDIRECT_URI
    
    # Exchange authorization code for tokens
    code = request.query_params.get('code')
    flow.fetch_token(code=code)
    creds = flow.credentials

    # File-based storage logic 
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())

    return {"message": "Authentication successful! You can close this window."}