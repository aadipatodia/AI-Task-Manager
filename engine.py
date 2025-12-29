import os
import json
import datetime
import requests
import base64
from google import genai
from email.message import EmailMessage
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
from send_message import send_whatsapp_message, send_whatsapp_document

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/gmail.send']

# Initialize Gemini client correctly
client = genai.Client(api_key=GEMINI_API_KEY)

# Manager's (your) credentials — always available for sending emails
MANAGER_CREDS = None
if os.path.exists('token.json'):
    MANAGER_CREDS = Credentials.from_authorized_user_file('token.json', SCOPES)
    if MANAGER_CREDS.expired and MANAGER_CREDS.refresh_token:
        MANAGER_CREDS.refresh(Request())

def get_creds_for_user(phone_number):
    try:
        with open('user_tokens.json', 'r') as f:
            user_tokens = json.load(f)
        
        user_data = user_tokens.get(phone_number)
        if user_data and "google_credentials" in user_data:
            creds_data = user_data["google_credentials"]
            creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            return creds
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    return None  # No credentials for this user

# File helpers
def load_team():
    try:
        with open('team.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_team(team):
    with open('team.json', 'w') as f:
        json.dump(team, f, indent=4)

def load_state():
    try:
        with open('state.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_state(state):
    with open('state.json', 'w') as f:
        json.dump(state, f, indent=4)

def download_document(document_id, mime_type, filename):
    url = f"https://graph.facebook.com/v20.0/{document_id}/"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print("Failed to get media URL:", response.text)
        return None
    media_url = response.json().get("url")
    if not media_url:
        return None
    download_response = requests.get(media_url, headers=headers)
    if download_response.status_code == 200:
        safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
        file_path = f"temp_{safe_filename}"
        with open(file_path, 'wb') as f:
            f.write(download_response.content)
        return file_path, mime_type, filename
    return None

def process_task(user_command, sender_phone, message=None):
    state = load_state()
    pending = state.get(sender_phone, {}).get("pending", {})

    # Handle pending yes/no for update employee
    if pending and user_command.lower() in ["yes", "no"] and pending.get("action") == "confirm_update":
        if user_command.lower() == "yes":
            team = load_team()
            existing_index = pending["context"]["existing_index"]
            new_data = pending["data"]
            team[existing_index]["email"] = new_data.get("email") or team[existing_index]["email"]
            team[existing_index]["phone"] = new_data.get("phone") or team[existing_index]["phone"]
            save_team(team)
            reply = f"✅ Updated {team[existing_index]['name'].title()}'s profile."
            state.pop(sender_phone, None)
            save_state(state)
            return reply, None
        else:
            return add_employee(pending["data"], sender_phone)

    # Handle number choice for duplicate names in task assignment
    if pending and user_command.isdigit() and pending.get("action") == "disambiguate_task":
        choice = int(user_command) - 1
        matches = pending["context"]["matches"]
        if 0 <= choice < len(matches):
            selected = matches[choice]
            data = pending["data"]
            reply, _ = assign_task(data, selected, message)
            state.pop(sender_phone, None)
            save_state(state)
            return reply, data
        return "Invalid choice. Please reply with a valid number.", None

    # Main AI processing with Gemini
    today = datetime.datetime.now()
    prompt = f"""
Today's date is {today.strftime('%A, %b %d, %Y')}.
User Command: "{user_command}"

You are a smart task & team manager bot. Return ONLY valid JSON.

Possible actions:
- assign_task
- add_employee

For assign_task:
{{
  "action": "assign_task",
  "name": "person name lowercase",
  "task": "full task description",
  "deadline": "ISO datetime or null"
}}

For add_employee:
{{
  "action": "add_employee",
  "name": "person name lowercase",
  "email": "email or empty string",
  "phone": "international phone without + or empty string"
}}

For error:
{{
  "action": "error",
  "message": "short error"
}}

Only JSON. No markdown or code blocks.
"""

    try:
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt
        )
        clean_text = response.text.strip()

        # Clean possible markdown
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:].strip()
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3].strip()

        data = json.loads(clean_text)
    except Exception as e:
        print("Gemini Error:", e)
        return "Sorry, AI is having trouble understanding. Try again.", None

    action = data.get("action")

    if action == "add_employee":
        return handle_add_employee(data, sender_phone)

    elif action == "assign_task":
        return handle_assign_task(data, sender_phone, message)

    else:
        return data.get("message", "I didn't understand that command."), data

def handle_add_employee(data, sender_phone):
    name_key = data.get("name", "").lower().strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()

    if not name_key:
        return "Please provide a name.", data
    if not email and not phone:
        return "Please provide at least email or phone.", data

    team = load_team()
    name_lower = name_key.lower()
    matches = [m for m in team if name_lower in m["name"].lower()]

    if matches:
        state = load_state()
        state[sender_phone] = {
            "pending": {
                "action": "confirm_update",
                "data": data,
                "context": {"existing_index": team.index(matches[0])}
            }
        }
        save_state(state)
        existing = matches[0]
        return (f"Found existing {name_key.title()} (Email: {existing.get('email','none')}, "
                f"Phone: {existing.get('phone','none')}).\nUpdate this profile? Reply yes/no"), data

    return add_employee(data, sender_phone)

def add_employee(data, sender_phone):
    team = load_team()
    new_member = {
        "name": data["name"].lower(),
        "email": data.get("email", ""),
        "phone": data.get("phone", "")
    }
    team.append(new_member)
    save_team(team)
    reply = (f" New employee added!\nName: {data['name'].title()}\n"
             f"Email: {new_member['email'] or 'not set'}\n"
             f"Phone: {new_member['phone'] or 'not set'}")
    return reply, data

def handle_assign_task(data, sender_phone, message):
    team = load_team()
    name_key = data.get("name", "").strip()

    if not name_key:
        return "Please specify a person's name in the task.", data

    name_lower = name_key.lower()

    # Partial match: anyone whose full name contains the keyword (case-insensitive)
    matches = [
        member for member in team
        if name_lower in member["name"].lower()
    ]

    # No one found
    if not matches:
        return f"No one found with name containing '{name_key}'. Add them first with 'Add employee...'", data

    # Exactly one match → assign directly
    if len(matches) == 1:
        selected = matches[0]
        return assign_task(data, selected, message)

    # Multiple matches → disambiguate
    state = load_state()
    state[sender_phone] = {
        "pending": {
            "action": "disambiguate_task",
            "data": data,
            "context": {"matches": matches}
        }
    }
    save_state(state)

    # Build user-friendly list
    options = "\n".join([
        f"{i+1}. {m['name'].title()} — Email: {m.get('email', 'none')}, Phone: {m.get('phone', 'none')}"
        for i, m in enumerate(matches)
    ])

    return (
        f"Multiple people found with name containing '{name_key}':\n{options}\n\n"
        f"Which one do you mean? Reply with the number (1, 2, ...)"
    ), data

def assign_task(data, selected, message):
    today = datetime.datetime.now()
    deadline = data.get('deadline')
    if not deadline:
        start = today.replace(hour=9, minute=0, second=0, microsecond=0)
        deadline = start.isoformat() + "Z"
        end_time = (start + datetime.timedelta(hours=1)).isoformat() + "Z"
    else:
        start_dt = datetime.datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        end_time = (start_dt + datetime.timedelta(hours=1)).isoformat() + "Z"

    assignee_name = data['name'].title()
    assignee_phone = selected.get('phone', "")
    assignee_email = selected.get('email', "")

    if not assignee_email:
        return f"Task assigned to {assignee_name}, but no email found in team — email not sent.", data

    # 1. Calendar: Only in employee's calendar if they connected
    assignee_creds = get_creds_for_user(assignee_phone) if assignee_phone else None

    calendar_created = False
    calendar_note = ""

    if assignee_creds:
        try:
            calendar_service = build('calendar', 'v3', credentials=assignee_creds)
            calendar_service.events().insert(
                calendarId='primary',
                body={
                    'summary': f"Task: {data['task']}",
                    'description': f"Assigned by manager via WhatsApp Bot\nDue: {data.get('deadline') or 'ASAP'}",
                    'start': {'dateTime': deadline, 'timeZone': 'UTC'},
                    'end': {'dateTime': end_time, 'timeZone': 'UTC'}
                }
            ).execute()
            calendar_created = True
        except Exception as e:
            print("Calendar error:", e)
            calendar_note = "Calendar event failed (check permissions)."
    else:
        calendar_note = f"{assignee_name} has not connected their Google account — no event created in their calendar."

    # 2. Email: Always from YOUR (manager's) Gmail
    email_sent = False
    if MANAGER_CREDS:
        try:
            gmail_service = build('gmail', 'v1', credentials=MANAGER_CREDS)
            msg = EmailMessage()
            body = f"New task assigned to you:\n\nTask: {data['task']}\nDue: {data.get('deadline') or 'ASAP'}\n\n— Assigned via WhatsApp AI Task Bot"
            msg.set_content(body)
            msg['Subject'] = 'New Task Assignment'
            msg['From'] = 'me'  # Your email
            msg['To'] = assignee_email

            file_path = None
            if message and "document" in message:
                doc = message["document"]
                downloaded = download_document(doc["id"], doc["mime_type"], doc.get("filename", "document"))
                if downloaded:
                    file_path, mime_type, filename = downloaded
                    with open(file_path, 'rb') as f:
                        msg.add_attachment(f.read(), maintype=mime_type.split('/')[0],
                                           subtype=mime_type.split('/')[1], filename=filename)

            gmail_service.users().messages().send(
                userId="me",
                body={'raw': base64.urlsafe_b64encode(msg.as_bytes()).decode()}
            ).execute()
            email_sent = True

            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print("Email send failed:", e)
    else:
        email_sent = False

    # 3. WhatsApp to employee (from bot number)
    whatsapp_sent = False
    if assignee_phone:
        try:
            whatsapp_msg = f"🚀 *New Task Assigned*\n\nTask: {data['task']}\nDue: {data.get('deadline', 'ASAP')}"
            send_whatsapp_message(assignee_phone, whatsapp_msg, PHONE_NUMBER_ID)

            if message and "document" in message:
                doc = message["document"]
                downloaded = download_document(doc["id"], doc["mime_type"], doc.get("filename", "document"))
                if downloaded:
                    file_path, mime_type, filename = downloaded
                    send_whatsapp_document(assignee_phone, file_path, filename, mime_type, PHONE_NUMBER_ID)
                    os.remove(file_path)

            whatsapp_sent = True
        except Exception as e:
            print("WhatsApp send failed:", e)

    # Final reply to you (manager)
    reply = f" Task assigned to {assignee_name} (Due: {data.get('deadline', 'ASAP')})"

    if calendar_created:
        reply += "\n Event created in their calendar"
    else:
        reply += f"\n {calendar_note}"

    if email_sent:
        reply += "\n Email sent from your account"
    else:
        reply += "\n Email not sent (check your Gmail connection)"

    if whatsapp_sent:
        reply += "\n WhatsApp notification sent"
    else:
        reply += "\n WhatsApp not sent (test mode restriction or no phone)"

    return reply, data

def handle_message(user_command, sender_phone, phone_number_id, message=None, full_message=None):
    state = load_state()
    processed = load_processed_messages()

    # Get unique message ID for deduplication
    msg_id = None
    if full_message and "id" in full_message:
        msg_id = full_message["id"]
    elif message and "document" in message:
        msg_id = message["document"].get("id")

    # Skip if already processed
    if msg_id and msg_id in processed:
        print(f"Skipping duplicate message ID: {msg_id}")
        return

    # Restore pending document if user is replying after being asked
    pending_doc = state.get(sender_phone, {}).get("pending_document")
    if pending_doc and not message:  # Text reply after document-only message
        message = {"document": pending_doc}

    # Case 1: Document sent with no caption/command
    if not user_command and message and "document" in message:
        doc = message["document"]
        # Save document for later use
        state[sender_phone] = {"pending_document": doc}
        save_state(state)

        reply = ("You sent a document! 📎\n"
                 "Who should I assign this to and what task?\n\n"
                 "Reply like:\n"
                 "• Send to Aadi and tell him to summarize by 9pm\n"
                 "• Assign this to John for review tomorrow")
        send_whatsapp_message(sender_phone, reply, phone_number_id)

        # Mark as processed
        if msg_id:
            processed.add(msg_id)
            save_processed_messages(processed)
        return

    # Case 2: Normal message with text/caption (with or without document)
    if user_command:
        status, _ = process_task(user_command.strip(), sender_phone, message)
        print("Bot reply:", status)
        send_whatsapp_message(sender_phone, status, phone_number_id)

        # Clear pending document after successful use
        if sender_phone in state and "pending_document" in state[sender_phone]:
            state[sender_phone].pop("pending_document")
            if not state[sender_phone]:
                state.pop(sender_phone)
            save_state(state)

    # Mark message as processed (after successful handling)
    if msg_id:
        processed.add(msg_id)
        save_processed_messages(processed)
        
def load_processed_messages():
    try:
        with open('processed_messages.json', 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

def save_processed_messages(processed_set):
    with open('processed_messages.json', 'w') as f:
        json.dump(list(processed_set), f)