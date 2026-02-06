from fastapi import FastAPI, Request, HTTPException, Query
import os
import logging
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from engine import handle_message, SCOPES, REDIRECT_URI
from redis_session import redis_client  # Leverage existing Redis connection

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

# Time in seconds to keep message IDs in Redis (e.g., 24 hours)
# This prevents duplicates even if Meta retries a webhook after a server restart.
DEDUPLICATION_TTL = 86400 

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
    
    if not data or "entry" not in data:
        return {"status": "EVENT_RECEIVED"}
    
    for entry in data["entry"]:
        for change in entry.get("changes", []):
            value = change.get("value", {})
            
            # Skip status updates (delivered/read receipts)
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
                
                # --- ATOMIC DEDUPLICATION CHECK USING REDIS ---
                # setnx (Set if Not Exists) returns 1 if key is new, 0 if it already exists
                dedup_key = f"processed_msg:{msg_id}"
                is_new = redis_client.set(dedup_key, "1", ex=DEDUPLICATION_TTL, nx=True)
                
                if not is_new:
                    logger.info(f"Duplicate message ignored: {msg_id}")
                    continue
                # ----------------------------------------------
                
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
                    img = message.get("image", {})
                    if img:
                        user_command = img.get("caption", "").strip()
                        message_data = {"image": img, "type": "image"}

                if user_command.strip() or message_data:
                    # Pass the message to the engine for processing
                    await handle_message(
                        user_command, 
                        sender_phone, 
                        phone_number_id, 
                        message=message_data, 
                        full_message=message
                    )

    return {"status": "EVENT_RECEIVED"}

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    state = request.query_params.get('state')
    
    # Corrected usage of Flow class from google_auth_oauthlib
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

    # Save credentials for future use
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())

    return {"message": "Authentication successful! You can close this window."}