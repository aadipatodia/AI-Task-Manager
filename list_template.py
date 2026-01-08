import os
import requests
from dotenv import load_dotenv

load_dotenv()

ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
VERSION = os.getenv('VERSION', 'v21.0')
PHONE_NUMBER_ID = os.getenv('PHONE_NUMBER_ID')  # Ensure this is set to '951533594704931'

def get_waba_id_for_phone():
    # Step 1: Get businesses
    url = f"https://graph.facebook.com/{VERSION}/me?fields=businesses"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Failed to get businesses: {response.status_code} - {response.text}")
        return None
    
    businesses = response.json().get('businesses', {}).get('data', [])
    
    for business in businesses:
        business_id = business['id']
        business_name = business.get('name', 'Unknown')
        
        # Step 2: Get owned WABAs for this business
        url = f"https://graph.facebook.com/{VERSION}/{business_id}/owned_whatsapp_business_accounts"
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to get WABAs for business {business_id}: {response.status_code} - {response.text}")
            continue
        
        wabas = response.json().get('data', [])
        
        for waba in wabas:
            waba_id = waba['id']
            waba_name = waba.get('name', 'Unknown')
            
            # Step 3: Get phone numbers for this WABA
            url = f"https://graph.facebook.com/{VERSION}/{waba_id}/phone_numbers"
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                print(f"Failed to get phones for WABA {waba_id}: {response.status_code} - {response.text}")
                continue
            
            phones = response.json().get('data', [])
            
            for phone in phones:
                if phone['id'] == PHONE_NUMBER_ID:
                    print(f"Match found!")
                    print(f"WABA_ID: {waba_id}")
                    print(f"WABA Name: {waba_name}")
                    print(f"Business ID: {business_id}")
                    print(f"Business Name: {business_name}")
                    print(f"Phone Details: {phone}")
                    return waba_id
    
    print("No matching WABA found for PHONE_NUMBER_ID.")
    return None

if __name__ == "__main__":
    waba_id = get_waba_id_for_phone()
    if waba_id:
        # Now list templates for this WABA (use the code from previous response)
        url = f"https://graph.facebook.com/{VERSION}/{waba_id}/message_templates"
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            templates = response.json().get('data', [])
            for template in templates:
                print(f"Name: {template['name']}, Language: {template['language']}, Status: {template['status']}, Category: {template['category']}")
        else:
            print(f"Failed to list templates: {response.status_code} - {response.text}")