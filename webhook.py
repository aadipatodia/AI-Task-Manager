from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse # Added for the OAuth success page
import os
import json # Fixes "json is not defined"
from dotenv import load_dotenv

# Import functions from your other files
from engine import handle_message, SCOPES, REDIRECT_URI # Fixes "REDIRECT_URI is not defined"
from send_message import send_whatsapp_message # Fixes "send_whatsapp_message is not defined"

load_dotenv()
app = FastAPI()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
MANAGER_PHONE = "91XXXXXXXXXX" # Replace with your actual WhatsApp number

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
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            if not phone_number_id:
                continue
                
            messages = value.get("messages", [])
            for message in messages:
                if "from" not in message:
                    continue
                    
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
                        message_data = {"document": doc}
                        
                elif msg_type == "image":
                    doc = message.get("image", {})
                    if doc:
                        user_command = doc.get("caption", "").strip()
                        message_data = {"image": doc}

                if user_command or message_data:
                    handle_message(user_command, sender_phone, phone_number_id, message=message_data, full_message=message)

    return {"status": "EVENT_RECEIVED"}

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    from google_auth_oauthlib.flow import Flow
    
    code = request.query_params.get("code")
    phone = request.query_params.get("state")
    error = request.query_params.get("error")

    # --- START OF NECESSARY CHANGE: PHONE NORMALIZATION ---
    if phone:
        phone = phone.strip()
        # Add 91 if it's a 10-digit number to ensure it matches team.json keys
        if len(phone) == 10 and not phone.startswith('91'):
            phone = f"91{phone}"
    # --- END OF NECESSARY CHANGE ---

    # Dynamically find the manager
    from engine import load_team, SCOPES, REDIRECT_URI
    team = load_team()
    employee_record = next((m for m in team if m.get("phone") == phone), None)
    target_manager = employee_record.get("manager_phone") if employee_record else None

    if error:
        if target_manager:
            send_whatsapp_message(target_manager, f"⚠️ Employee ({phone}) denied access.", PHONE_NUMBER_ID)
        return HTMLResponse("Access Denied.")

    if code and phone:
        flow = Flow.from_client_secrets_file("credentials.json", scopes=SCOPES, redirect_uri=REDIRECT_URI)
        flow.fetch_token(code=code)
        creds = flow.credentials

        # --- PROTECTED JSON LOADING ---
        tokens = {}
        if os.path.exists('user_tokens.json'):
            try:
                with open('user_tokens.json', 'r') as f:
                    content = f.read().strip()
                    if content: # Only load if file is NOT empty
                        tokens = json.loads(content)
            except json.JSONDecodeError:
                tokens = {} # Reset if file was corrupted/empty

        tokens[phone] = {"google_credentials": json.loads(creds.to_json())}
        
        with open('user_tokens.json', 'w') as f:
            json.dump(tokens, f, indent=4)

        if target_manager:
            send_whatsapp_message(target_manager, f"✅ Employee ({phone}) connected!", PHONE_NUMBER_ID)
        
        return HTMLResponse("<h1>Success!</h1><p>Calendar connected. You can close this.</p>")

    return {"status": "invalid_request"}