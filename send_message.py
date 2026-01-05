import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

# === CONFIGURATION ===
DEFAULT_PHONE_ID = os.getenv("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
VERSION = "v22.0"  # Current stable version as of Jan 2026. Update if Meta announces newer.

# Optional: Set up logging to console (and file if needed)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _clean_phone_number(phone: str) -> str:
    """Ensure phone is in international format without '+'."""
    phone = str(phone).replace("+", "").strip()
    # Add India country code if 10 digits (common case)
    if len(phone) == 10 and phone.startswith(("6", "7", "8", "9")):
        phone = "91" + phone
    return phone


def send_whatsapp_message(recipient_number: str, message_text: str, phone_number_id: str = None) -> dict:
    """
    Send a simple text message via WhatsApp Cloud API.
    Returns the API response JSON on success, None on failure.
    """
    recipient = _clean_phone_number(recipient_number)
    active_id = phone_number_id or DEFAULT_PHONE_ID

    if not active_id or not ACCESS_TOKEN:
        logger.error("PHONE_NUMBER_ID or ACCESS_TOKEN missing in environment!")
        return None

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
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            logger.info(f"WhatsApp text sent successfully to {recipient}")
            return response.json()
        else:
            # Log full error from Meta
            error_detail = response.text
            try:
                error_json = response.json()
                error_msg = error_json.get("error", {}).get("message", error_detail)
                error_code = error_json.get("error", {}).get("code", "unknown")
                logger.error(f"WhatsApp send failed ({response.status_code}) Code {error_code}: {error_msg}")
            except:
                logger.error(f"WhatsApp send failed ({response.status_code}): {error_detail}")
            return None

    except requests.exceptions.Timeout:
        logger.error("WhatsApp request timed out")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("Network connection error while sending WhatsApp message")
        return None
    except Exception as e:
        logger.error(f"Unexpected error sending WhatsApp message: {e}")
        return None


def upload_media(file_path: str, phone_number_id: str = None) -> str:
    """
    Upload a local file to WhatsApp servers and return the media ID.
    Required for sending documents/images from local files.
    """
    active_id = phone_number_id or DEFAULT_PHONE_ID
    url = f"https://graph.facebook.com/{VERSION}/{active_id}/media"

    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            data = {"type": "application/octet-stream", "messaging_product": "whatsapp"}

            response = requests.post(url, data=data, files=files, headers={
                "Authorization": f"Bearer {ACCESS_TOKEN}"
            }, timeout=30)

        if response.status_code == 200:
            media_id = response.json().get("id")
            logger.info(f"Media uploaded successfully: {media_id}")
            return media_id
        else:
            logger.error(f"Media upload failed: {response.status_code} - {response.text}")
            return None

    except FileNotFoundError:
        logger.error(f"File not found for upload: {file_path}")
        return None
    except Exception as e:
        logger.error(f"Error uploading media: {e}")
        return None


def send_whatsapp_document(
    recipient_number: str,
    file_path: str = None,
    document_url: str = None,
    filename: str = None,
    caption: str = None,
    phone_number_id: str = None
) -> dict:
    """
    Send a document. Prefer local file_path (more reliable).
    If only document_url is provided, sends via link (less reliable for large/private files).
    """
    recipient = _clean_phone_number(recipient_number)
    active_id = phone_number_id or DEFAULT_PHONE_ID

    url = f"https://graph.facebook.com/{VERSION}/{active_id}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

    # Priority: Use local file upload if file_path provided
    if file_path and os.path.exists(file_path):
        media_id = upload_media(file_path, phone_number_id)
        if not media_id:
            return None

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": {
                "id": media_id,
                "filename": filename or os.path.basename(file_path),
            }
        }
        if caption:
            payload["document"]["caption"] = caption

    elif document_url:
        # Fallback: Send via public link (must be HTTPS and accessible)
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "document",
            "document": {
                "link": document_url,
                "filename": filename or "document.pdf"
            }
        }
        if caption:
            payload["document"]["caption"] = caption

    else:
        logger.error("send_whatsapp_document: Either file_path or document_url must be provided")
        return None

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            logger.info(f"Document sent successfully to {recipient}")
            return response.json()
        else:
            error_detail = response.text
            try:
                err = response.json().get("error", {})
                logger.error(f"Document send failed: ({response.status_code}) {err.get('code')} - {err.get('message')}")
            except:
                logger.error(f"Document send failed: {response.status_code} - {error_detail}")
            return None

    except Exception as e:
        logger.error(f"Error sending document: {e}")
        return None


