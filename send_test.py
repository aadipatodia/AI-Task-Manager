import os
import requests
from dotenv import load_dotenv

# 1. Load your credentials from the .env file
load_dotenv()

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")  # Should be 929123666952098

RECIPIENT_PHONE = "917428134319" 

url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"

headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}


payload = {
    "messaging_product": "whatsapp",
    "to": RECIPIENT_PHONE,
    "type": "template",
    "template": {
        "name": "hello_world",
        "language": { "code": "en_US" }
    }
}

print(f"--- WhatsApp Test Connection ---")
print(f"Sending request to Phone ID: {PHONE_NUMBER_ID}")

try:
    response = requests.post(url, json=payload, headers=headers)
    status_code = response.status_code
    data = response.json()

    if status_code == 200:
        print(f"✅ SUCCESS!")
        print(f"Message ID: {data['messages'][0]['id']}")
        print(f"\nNext Step: Check your phone! Once you receive the message,")
        print(f"reply to it to start testing your main bot (engine.py).")
    else:
        print(f"❌ FAILED with Status Code: {status_code}")
        print(f"Error Details: {data}")
        
except Exception as e:
    print(f"An unexpected error occurred: {e}")