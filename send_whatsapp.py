import os
import requests
import json
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID')
VERSION = os.getenv('VERSION', 'v21.0')

def send_whatsapp_message(recipient_number, template_name="hello_world"):
    """
    Sends a WhatsApp message using the Cloud API.
    recipient_number should include country code (e.g., '919876543210')
    """
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": "en_US"
            }
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        
        # Check for the common "Object ID does not exist" error
        if response.status_code != 200:
            print(f"Failed! Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
        print("Message sent successfully!")
        return True
        
    except Exception as e:
        print(f"An error occurred: {e}")
        return False

if __name__ == "__main__":
    # Test with your client's number
    CLIENT_PHONE = "917428134319" 
    send_whatsapp_message(CLIENT_PHONE)