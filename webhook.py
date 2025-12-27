from fastapi import FastAPI, Request, HTTPException, Query
import os
from dotenv import load_dotenv
from engine import handle_message

load_dotenv()
app = FastAPI()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

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

                if user_command or message_data:  # Only process if there's command or document
                    handle_message(user_command, sender_phone, phone_number_id, message=message_data, full_message=message)

    return {"status": "EVENT_RECEIVED"}