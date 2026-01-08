import os
import requests
import json
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
PHONE_NUMBER_ID = "951533594704931"
VERSION = os.getenv('VERSION', 'v21.0')

def send_whatsapp_message(recipient_number, customer_name):
    
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
            "name": "task_manager", 
            "language": {
                "code": "en_US"  
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {
                            "type": "text",
                            "text": customer_name  
                        }
                    ]
                }
            ]
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            print(f" Success! Message sent to {customer_name}")
            return True
        else:
            print(f" Failed! Status Code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"An error occurred: {e}")
        return False

if __name__ == "__main__":
    CLIENT_PHONE = "917428134319" 
    send_whatsapp_message(CLIENT_PHONE, "Aadi")