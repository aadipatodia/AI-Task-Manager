import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/gmail.send']

def register_employee(phone_number):
    """Run this to let an employee authorize the bot for their calendar."""
    creds = None
    # We don't use token.json here because that's for the MANAGER.
    # We are generating a new one for the employee.
    
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)

    # Load existing tokens
    tokens = {}
    if os.path.exists('user_tokens.json'):
        with open('user_tokens.json', 'r') as f:
            tokens = json.load(f)

    # Save this employee's token under their phone number
    tokens[phone_number] = {
        "google_credentials": json.loads(creds.to_json())
    }

    with open('user_tokens.json', 'w') as f:
        json.dump(tokens, f, indent=4)
    
    print(f" Successfully authorized and saved credentials for: {phone_number}")

if __name__ == "__main__":
    phone = input("Enter employee phone number (with country code, e.g., 919818006468): ")
    register_employee(phone)