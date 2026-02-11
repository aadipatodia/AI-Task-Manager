import os
import requests
import logging
from dotenv import load_dotenv
import json

load_dotenv()

def log_reasoning(step: str, details: dict | str):
    logger.info(
        "[GEMINI_REASONING] %s | %s",
        step,
        json.dumps(details, ensure_ascii=False) if isinstance(details, dict) else details
    )

# === CONFIGURATION ===
DEFAULT_PHONE_ID = os.getenv("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
VERSION = "v22.0" 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _clean_phone_number(phone: str) -> str:
    """Ensure phone is in international format without '+'."""
    phone = str(phone).replace("+", "").strip()
    if len(phone) == 10 and phone.startswith(("6", "7", "8", "9")):
        phone = "91" + phone
    return phone

def send_whatsapp_message(recipient_number, message_text, phone_number_id=None):
    """
    Standard function for regular bot messages with enhanced logging.
    """
    recipient = _clean_phone_number(recipient_number)
    active_id = phone_number_id or DEFAULT_PHONE_ID
    url = f"https://graph.facebook.com/{VERSION}/{active_id}/messages"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": message_text}
    }

    # 1. LOG: Before Request - Track what is being sent
    logger.info(f"[WHATSAPP_START] Sending message to {recipient}")
    log_reasoning("WHATSAPP_SEND_PAYLOAD", {
        "to": recipient,
        "msg_preview": message_text[:50] + "..." if len(message_text) > 50 else message_text,
        "phone_id": active_id
    })

    try:
        response = requests.post(url, json=payload, headers=headers)
        
        # 2. LOG: Response Level - Status Code check
        logger.info(f"[WHATSAPP_RESPONSE] Meta Status: {response.status_code}")

        if response.status_code == 200:
            resp_data = response.json()
            # 3. LOG: Success Detail (Meta Message ID)
            log_reasoning("WHATSAPP_SEND_SUCCESS", {
                "recipient": recipient,
                "wam_id": resp_data.get("messages", [{}])[0].get("id")
            })
            return resp_data
        else:
            # 4. LOG: Failure Detail - Crucial for "Session Expired" or "Invalid Recipient"
            logger.error(f"[WHATSAPP_SEND_ERROR] Status: {response.status_code} | Body: {response.text}")
            log_reasoning("WHATSAPP_API_FAILURE", {
                "recipient": recipient,
                "error_body": response.text
            })
            return None

    except Exception as e:
        # 5. LOG: Network/System Exceptions
        logger.error(f"[WHATSAPP_EXCEPTION] Critical failure: {str(e)}")
        log_reasoning("WHATSAPP_SYSTEM_CRASH", {"error": str(e)})
        return None

def send_registration_template(recipient_number, user_identifier, phone_number_id=None):
    """
    Updated for the 'new_template_task_manager' template.
    Targets {{user_id}} in the BODY using Named Parameters.
    """
    pn_id = phone_number_id or os.getenv("PHONE_NUMBER_ID")
    access_token = os.getenv("ACCESS_TOKEN")
    url = f"https://graph.facebook.com/{VERSION}/{pn_id}/messages"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "template",
        "template": {
            "name": "new_template_task_manager", # New template name
            "language": {
                "code": "en"
            },
            "components": [
                {
                    "type": "body", # Variable is now in the body
                    "parameters": [
                        {
                            "type": "text",
                            "parameter_name": "user_id", # New parameter name
                            "text": user_identifier
                        }
                    ]
                }
            ]
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"  Success! Template sent to {user_identifier}")
            return True
        else:
            print(f"  API Error: {response.text}")
            return False
    except Exception as e:
        print(f"  Connection Error: {e}")
        return False
    
def upload_media(file_path, phone_number_id=None):
    active_id = phone_number_id or DEFAULT_PHONE_ID
    url = f"https://graph.facebook.com/{VERSION}/{active_id}/media"
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            data = {"type": "application/octet-stream", "messaging_product": "whatsapp"}
            response = requests.post(url, data=data, files=files, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
        return response.json().get("id") if response.status_code == 200 else None
    except Exception as e:
        return None

def send_whatsapp_document(recipient_number, file_path=None, document_url=None, filename=None, caption=None, phone_number_id=None):
    recipient = _clean_phone_number(recipient_number)
    active_id = phone_number_id or DEFAULT_PHONE_ID
    url = f"https://graph.facebook.com/{VERSION}/{active_id}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

    logger.info(f"[WHATSAPP_DOC_START] Preparing document for {recipient}")

    if file_path and os.path.exists(file_path):
        # Path 1: Local File Upload
        logger.info(f"[WHATSAPP_DOC_LOCAL] Uploading local file: {file_path}")
        media_id = upload_media(file_path, phone_number_id)
        
        if not media_id:
            logger.error(f"[WHATSAPP_DOC_UPLOAD_FAILED] Could not get media_id for {file_path}")
            return None
            
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": {"id": media_id, "filename": filename or os.path.basename(file_path)}
        }
        if caption: payload["document"]["caption"] = caption
        
    elif document_url:
        # Path 2: External URL
        logger.info(f"[WHATSAPP_DOC_URL] Sending hosted document: {document_url}")
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": {"link": document_url, "filename": filename or "document.pdf"}
        }
        if caption: payload["document"]["caption"] = caption
    else:
        logger.warning("[WHATSAPP_DOC_SKIPPED] No valid file_path or document_url provided.")
        return None

    try:
        log_reasoning("WHATSAPP_DOC_PAYLOAD", payload)
        response = requests.post(url, json=payload, headers=headers)

        logger.info(f"[WHATSAPP_DOC_RESPONSE] Status: {response.status_code}")
        
        if response.status_code == 200:
            resp_json = response.json()
            log_reasoning("WHATSAPP_DOC_SUCCESS", {"msg_id": resp_json.get("messages", [{}])[0].get("id")})
            return resp_json
        else:
            logger.error(f"[WHATSAPP_DOC_SEND_ERROR] Status: {response.status_code} | Body: {response.text}")
            log_reasoning("WHATSAPP_DOC_API_FAILURE", {"response": response.text})
            return None
            
    except Exception as e:
        logger.error(f"[WHATSAPP_DOC_EXCEPTION] Critical error: {str(e)}")
        log_reasoning("WHATSAPP_DOC_CRASH", {"error": str(e)})
        return None