import os
import httpx
import logging
from dotenv import load_dotenv

load_dotenv()

# === CONFIGURATION ===
DEFAULT_PHONE_ID = os.getenv("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
VERSION = "v22.0"

# Async HTTP client — thread-safe, connection pooling, fully concurrent-safe
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=5.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _clean_phone_number(phone: str) -> str:
    """Ensure phone is in international format without '+'."""
    phone = str(phone).replace("+", "").strip()
    if len(phone) == 10 and phone.startswith(("6", "7", "8", "9")):
        phone = "91" + phone
    return phone

async def send_whatsapp_message(recipient_number, message_text, phone_number_id=None):
    """
    Standard function for regular bot messages (AI replies, reports, etc).
    Fully async — safe under concurrent load.
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

    try:
        logger.info(
            f"[BOT_REPLY] Responding to {recipient} | "
            f"Message: {message_text[:150]}{'...' if len(message_text) > 150 else ''}"
        )

        response = await _http_client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            logger.info(
                f"[BOT_REPLY_SUCCESS] Delivered to {recipient} | "
                f"MsgLength: {len(message_text)}"
            )
            return response.json()
        else:
            logger.error(
                f"[BOT_REPLY_FAILED] Could NOT deliver to {recipient} | "
                f"Status: {response.status_code} | "
                f"Response: {response.text}"
            )
            return None

    except Exception as e:
        logger.exception(
            f"[BOT_REPLY_EXCEPTION] Exception while responding to {recipient}"
        )
        return None

async def send_registration_template(recipient_number, user_identifier, phone_number_id=None):
    """
    Updated for the 'new_template_task_manager' template.
    Targets {{user_id}} in the BODY using Named Parameters.
    Fully async.
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
            "name": "new_template_task_manager",
            "language": {
                "code": "en"
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "parameter_name": "user_id",
                            "text": user_identifier
                        }
                    ]
                }
            ]
        }
    }

    try:
        response = await _http_client.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"  Success! Template sent to {user_identifier}")
            return True
        else:
            print(f"  API Error: {response.text}")
            return False
    except Exception as e:
        print(f"  Connection Error: {e}")
        return False
    
async def upload_media(file_path, phone_number_id=None):
    active_id = phone_number_id or DEFAULT_PHONE_ID
    url = f"https://graph.facebook.com/{VERSION}/{active_id}/media"
    try:
        with open(file_path, "rb") as f:
            file_content = f.read()
        files = {"file": (os.path.basename(file_path), file_content, "application/octet-stream")}
        data = {"messaging_product": "whatsapp"}
        response = await _http_client.post(url, data=data, files=files, headers={"Authorization": f"Bearer {ACCESS_TOKEN}"})
        return response.json().get("id") if response.status_code == 200 else None
    except Exception as e:
        return None

async def send_whatsapp_document(recipient_number, file_path=None, document_url=None, filename=None, caption=None, phone_number_id=None):
    recipient = _clean_phone_number(recipient_number)
    active_id = phone_number_id or DEFAULT_PHONE_ID
    url = f"https://graph.facebook.com/{VERSION}/{active_id}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

    if file_path and os.path.exists(file_path):
        media_id = await upload_media(file_path, phone_number_id)
        if not media_id: return None
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": {"id": media_id, "filename": filename or os.path.basename(file_path)}
        }
        if caption: payload["document"]["caption"] = caption
    elif document_url:
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": {"link": document_url, "filename": filename or "document.pdf"}
        }
        if caption: payload["document"]["caption"] = caption
    else: return None

    try:
        response = await _http_client.post(url, json=payload, headers=headers)
        return response.json() if response.status_code == 200 else None
    except Exception as e:
        return None
