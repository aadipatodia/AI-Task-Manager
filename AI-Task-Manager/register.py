import os
import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID') 
VERSION = os.getenv('VERSION', 'v22.0')

def send_whatsapp_message(recipient_number, user_identifier):
    """
    Sends a WhatsApp message using the 'new_template_task_manager' template.
    Uses 'user_id' parameter in the body.
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
                            "text": user_identifier,
                            "parameter_name": "user_id"  
                        }
                    ]
                }
            ]
        }
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            print(f"  Success! Message sent ")
            return True
        else:
            print(f" Failed! Status Code: {response.status_code}")
            print(f" Response: {response.text}")
            return False
            
    except Exception as e:
        print(f" An error occurred: {e}")
        return False

if __name__ == "__main__":
    CLIENT_PHONE = "9XXXXXXXXXXXXXX" 
    send_whatsapp_message(CLIENT_PHONE, "a")