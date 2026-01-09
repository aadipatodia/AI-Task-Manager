from engine import register_company

# ENTER DETAILS HERE
NEW_COMPANY_NAME = "Mobineers Info Systems Private Limited"
CHAIRMAN_NAME = "Abhay"
CHAIRMAN_PHONE = "919818006468" 
CHAIRMAN_EMAIL = "ap@mobineers.com"

# Execute this to save to MongoDB and send the WhatsApp template
company_id = register_company(
    NEW_COMPANY_NAME, 
    CHAIRMAN_NAME, 
    CHAIRMAN_PHONE, 
    CHAIRMAN_EMAIL
)

print(f"Company Registered! ID: {company_id}")