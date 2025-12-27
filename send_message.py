# send_message.py
import requests
import os
from dotenv import load_dotenv

load_dotenv()
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")

def send_whatsapp_message(to, message, phone_number_id):
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        print(f"Failed to send text to {to}: {response.text}")
    else:
        print(f"Sent text to {to}: {message[:50]}...")

def send_whatsapp_document(to, file_path, filename, mime_type, phone_number_id):
    """
    Sends a document via WhatsApp Cloud API using media upload (temporary).
    file_path: local path to the downloaded file
    filename: original name of the file
    mime_type: e.g., 'application/pdf', 'image/jpeg'
    """
    # Step 1: Upload media to get media ID
    upload_url = f"https://graph.facebook.com/v20.0/{phone_number_id}/media"
    files = {
        'file': (filename, open(file_path, 'rb'), mime_type),
        'type': (None, mime_type),
        'messaging_product': (None, 'whatsapp')
    }
    data = {
        'messaging_product': 'whatsapp'
    }
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    upload_response = requests.post(upload_url, headers=headers, data=data, files=files)
    
    if upload_response.status_code != 200:
        print(f"Media upload failed: {upload_response.text}")
        return

    media_id = upload_response.json().get("id")
    if not media_id:
        print("No media ID received")
        return

    # Step 2: Send message with document using media ID
    send_url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "caption": f"Attached document: {filename}",
            "filename": filename
        }
    }

    send_response = requests.post(send_url, json=payload, headers=headers)
    if send_response.status_code == 200:
        print(f"Document sent successfully to {to}: {filename}")
    else:
        print(f"Failed to send document to {to}: {send_response.text}")