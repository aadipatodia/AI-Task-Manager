import os
import json
import datetime
import base64
from google import genai
from email.message import EmailMessage
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
from send_message import send_whatsapp_message, send_whatsapp_document, send_registration_template
from google_auth_oauthlib.flow import Flow 
from pymongo import MongoClient
import certifi
import uuid

load_dotenv()

# --- DATABASE INITIALIZATION ---
MONGO_URI = os.getenv("MONGO_URI")
db_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = db_client['ai_task_manager']

# MongoDB Collections (Replace your JSON files)
users_col = db['users']
tasks_col = db['tasks']
team_col = db['team']
state_col = db['state']
tokens_col = db['user_tokens']
processed_col = db['processed_messages']

# --- CONFIG FILE RECREATORS (Static Secrets) ---
def create_file_from_env(filename, env_var_name):
    """Recreates static config files from Render environment variables."""
    if not os.path.exists(filename):
        content = os.getenv(env_var_name)
        if content:
            with open(filename, 'w') as f:
                f.write(content)
            print(f" Created {filename} from environment.")

create_file_from_env("credentials.json", "CREDENTIALS_JSON")
create_file_from_env("token.json", "TOKEN_JSON")

# --- GLOBAL CONFIG ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/gmail.send']
CLIENT_SECRETS_FILE = "credentials.json"
REDIRECT_URI = "https://ai-task-manager-38w7.onrender.com/oauth2callback" 

client = genai.Client(api_key=GEMINI_API_KEY)
MANAGER_CREDS = None
if os.path.exists('token.json'):
    MANAGER_CREDS = Credentials.from_authorized_user_file('token.json', SCOPES)
    if MANAGER_CREDS.expired and MANAGER_CREDS.refresh_token:
        MANAGER_CREDS.refresh(Request())


def save_user(phone_number, name, email, role="Employee", supervisor_id=None):
    clean_phone = str(phone_number).replace("+", "").strip()
    existing_user = users_col.find_one({"phone_id": clean_phone})
    subordinates = existing_user.get("subordinates", []) if existing_user else []
    
    user_data = {
        "name": name,
        "email": email,
        "role": role,
        "supervisor_id": supervisor_id,
        "subordinates": subordinates
    }
    result = users_col.update_one({"phone_id": clean_phone}, {"$set": user_data}, upsert=True)
    status = "updated" if result.matched_count > 0 else "added"
    return f"User {name} successfully {status}."

# --- Updated engine.py functions ---

def load_team(company_id):
    """Fetch only team members belonging to this specific company."""
    return list(team_col.find({"company_id": company_id}, {"_id": 0}))

def save_team(team_list, company_id):
    """Only update the team list for this specific company."""
    if not team_list: return
    # CRITICAL: Only delete documents for THIS company
    team_col.delete_many({"company_id": company_id})
    for member in team_list:
        member["company_id"] = company_id
    team_col.insert_many(team_list)

def load_users(company_id):
    """Fetch users filtered by company_id."""
    users = {}
    for user in users_col.find({"company_id": company_id}):
        phone = user.pop("phone_id", None)
        if phone:
            user.pop("_id", None)
            users[phone] = user
    return users

def load_tasks(company_id):
    """Load tasks for a specific company, sorted by deadline."""
    return list(tasks_col.find({"company_id": company_id}, {"_id": 0}).sort("deadline", 1))

def save_tasks(tasks_list, company_id):
    """Save tasks while preserving the company partition."""
    # CRITICAL: Only delete tasks for THIS company
    tasks_col.delete_many({"company_id": company_id})
    if tasks_list:
        for task in tasks_list:
            task["company_id"] = company_id
        tasks_col.insert_many(tasks_list)

def load_state(company_id):
    """Load the conversational state specific to this company."""
    doc = state_col.find_one({"id": "global_state", "company_id": company_id})
    return doc.get("data", {}) if doc else {}

def save_state(state_dict, company_id):
    """Save state with a company_id to prevent conversational overlap."""
    state_col.update_one(
        {"id": "global_state", "company_id": company_id}, 
        {"$set": {"data": state_dict, "company_id": company_id}}, 
        upsert=True
    )

def load_processed_messages():
    return {d["msg_id"] for d in processed_col.find({}, {"msg_id": 1})}

def save_processed_messages(processed_set):
    for msg_id in processed_set:
        processed_col.update_one({"msg_id": msg_id}, {"$set": {"msg_id": msg_id}}, upsert=True)

def get_creds_for_user(phone_number, company_id):
    # Partition the query by company_id to prevent unauthorized token access
    user_data = tokens_col.find_one({"phone": phone_number, "company_id": company_id})
    if user_data and "google_credentials" in user_data:
        creds_data = user_data["google_credentials"]
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Ensure the refreshed token is saved back to the correct company partition
            tokens_col.update_one(
                {"phone": phone_number, "company_id": company_id}, 
                {"$set": {"google_credentials": json.loads(creds.to_json())}}
            )
        return creds
    return None

def download_document(document_id, mime_type, filename):
    url = f"https://graph.facebook.com/v20.0/{document_id}/"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    response = send_whatsapp_message.get(url, headers=headers)
    if response.status_code != 200:
        print("Failed to get media URL:", response.text)
        return None
    media_url = response.json().get("url")
    if not media_url:
        return None
    download_response = send_whatsapp_message.get(media_url, headers=headers)
    if download_response.status_code == 200:
        safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
        file_path = f"temp_{safe_filename}"
        with open(file_path, 'wb') as f:
            f.write(download_response.content)
        return file_path, mime_type, filename
    return None

def get_authorization_url(phone_number):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    # Added prompt='consent' to ensure a refresh_token is returned every time
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        state=phone_number,
        prompt='consent'  # <--- ADD THIS LINE
    )
    return auth_url

def format_task_list(task_list, title, is_assigned=False):
    """
    Requirement 3: Groups tasks into OVERDUE, DUE TODAY, UPCOMING, and COMPLETED.
    Includes team pending counts at the bottom.
    """
    if not task_list:
        return f"*{title}*\nNo tasks found.\n"
    
    now = datetime.datetime.now()
    overdue, due_today, upcoming, completed = [], [], [], []
    team_counts = {}

    for t in task_list:
        # 1. Track Pending Counts for Footer
        assignee_name = t.get('assignee_name', 'Unknown').title()
        if t['status'] != 'done':
            team_counts[assignee_name] = team_counts.get(assignee_name, 0) + 1

        # 2. Parse Date (Removing 'Z' if present)
        dt = datetime.datetime.fromisoformat(t['deadline'].replace("Z", ""))
        
        # 3. Format Strings
        is_today = dt.date() == now.date()
        time_str = f"{dt.strftime('%I:%M %p')} Today" if is_today else dt.strftime("%d %b")
        assignee_ctx = f" (to {assignee_name})" if is_assigned else ""
        status_note = f" (Done: {t.get('remarks', 'closed')})" if t['status'] == 'done' else ""
        
        task_line = f"{t['task']}{assignee_ctx}    task id: {t['task_id']}\n   Due: {time_str}{status_note}"

        # 4. Categorize
        if t['status'] == 'done':
            completed.append(task_line)
        elif dt < now:
            overdue.append(task_line)
        elif is_today:
            due_today.append(task_line)
        else:
            upcoming.append(task_line)

    # 5. Build final report
    report = f"*{title}*\n"
    if overdue: report += "\n*🔴 OVERDUE*\n" + "\n".join([f"{i+1}. {l}" for i, l in enumerate(overdue)]) + "\n"
    if due_today: report += "\n*🟡 DUE TODAY*\n" + "\n".join([f"{i+1}. {l}" for i, l in enumerate(due_today)]) + "\n"
    if upcoming: report += "\n*🟢 UPCOMING*\n" + "\n".join([f"{i+1}. {l}" for i, l in enumerate(upcoming)]) + "\n"
    if completed: report += "\n*✅ COMPLETED*\n" + "\n".join([f"{i+1}. {l}" for i, l in enumerate(completed)]) + "\n"

    # 6. Add Team Pending Summary
    if is_assigned and team_counts:
        report += "\n*team pending task count*\n"
        for name, count in team_counts.items():
            report += f"{name}: {count}\n"

    return report

def get_pending_tasks(phone, company_id, limit=5, today_only=False):
    tasks = load_tasks(company_id)
    my_tasks = [t for t in tasks if t['assignee_phone'] == phone and t['status'] == 'pending']   
     
    if today_only:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        my_tasks = [t for t in my_tasks if t['deadline'].startswith(today_str)]
    
    # Apply the limit here by slicing the list
    limited_tasks = my_tasks[:limit]
    
    # Remove 'limit=limit' from the function call
    return format_task_list(my_tasks[:limit], "Your Pending Tasks", is_assigned=False)

def get_all_pending_counts(phone, company_id):
    # FIXED: Pass company_id to load functions
    tasks = load_tasks(company_id)
    team = load_team(company_id)
    subs = [e for e in team if e.get('manager_phone') == phone]
    if not subs:
        return "You don't have any direct reports."
    my_employees = {e['phone']: e['name'].title() for e in subs}
    now = datetime.datetime.now()
    user_counts = {name: 0 for name in my_employees.values()}
    for t in tasks:
        if t['assignee_phone'] in my_employees and t['status'] == 'pending':
            assignee_name = t['assignee_name'].title()
            user_counts[assignee_name] += 1
    report = "*Team Pending Task Counts*\n\n"
    for name, count in user_counts.items():
        report += f"{name}: {count} pending\n"
    return report

def get_user_pending_tasks(target_name, phone, company_id, limit=10):
    # Pass company_id to load the correct team
    team = load_team(company_id)
    employee = next((e for e in team if e.get("name").lower() == target_name.lower() and e.get("manager_phone") == phone), None)
    if not employee:
        return f"Could not find employee '{target_name}' in your team.", None
    # Pass company_id to load tasks
    return get_pending_tasks(employee['phone'], company_id, limit=limit, today_only=False)


def get_performance_stats(company_id, target_phone=None):
    tasks = load_tasks(company_id) 
    team = load_team(company_id)
    now = datetime.datetime.now()
    
    # Logic for Requirement 2 (Specific) vs Requirement 1 (All)
    if target_phone:
        display_team = [e for e in team if e.get('phone') == target_phone]
    else:
        display_team = team

    if not display_team:
        return "No employees found in the database."

    report = "*Performance Report*\n" + "="*20 + "\n"

    for member in display_team:
        phone = member.get('phone')
        name = member.get('name', 'Unknown').title()
        
        # Filter all tasks for this specific member
        member_tasks = [t for t in tasks if t.get('assignee_phone') == phone]
        
        assigned = len(member_tasks)
        completed = len([t for t in member_tasks if t.get('status') == 'done'])
        
        # Split Pending tasks into Within vs Beyond Time
        pending_tasks = [t for t in member_tasks if t.get('status') == 'pending']
        within_time = 0
        beyond_time = 0
        
        for t in pending_tasks:
            try:
                # Compare deadline string to current time
                deadline_dt = datetime.fromisoformat(t['deadline'].replace("Z", ""))
                if deadline_dt > now:
                    within_time += 1
                else:
                    beyond_time += 1
            except:
                within_time += 1 # Fallback for formatting issues

        # Requirement 1 formatting: Aggregates for each person in the loop
        report += f"\n *Name:* {name}\n"
        report += f"Task Assigned: {assigned}\n"
        report += f"Task Completed: {completed}\n"
        report += f"Task Pending: {len(pending_tasks)}\n"
        report += f"  - Within time: {within_time}\n"
        report += f"  - Beyond time: {beyond_time}\n"
        report += "-"*15

    return report


def register_company(company_name, chairman_name, chairman_phone, chairman_email):
    """
    The entry point for a new company.
    Generates a unique company_id and sets the first Chairman.
    """
    new_company_id = str(uuid.uuid4())[:8] # Unique 8-character ID
    
    chairman_data = {
        "name": chairman_name.lower(),
        "email": chairman_email,
        "phone": chairman_phone,
        "role": "chairman",
        "company_id": new_company_id,
        "company_name": company_name
    }
    
    team_col.insert_one(chairman_data)
    
    # Send welcome message ONLY to the Chairman
    welcome = (f"Hello {chairman_name.title()}! \n\n"
               f"Your company '{company_name}' is now registered.\n"
               f"Company ID: {new_company_id}\n\n"
               "You can now add Managers by typing: 'Add manager [Name], [Email], [Phone]'")
    
    send_registration_template(chairman_phone, chairman_name, PHONE_NUMBER_ID)
    return new_company_id

def delete_employee(target_name, manager_phone, company_id):
    """
    Deletes an employee from the company's team collection.
    """
    # Load company team only
    team = load_team(company_id)
    
    # 1. Find the employee within the specific company partition
    employee = next((e for e in team if target_name in e.get("name", "").lower()), None)
    
    if not employee:
        return f"❌ Could not find an employee named '{target_name.title()}' in your company team."

    # 2. Prevent self-deletion
    if employee['phone'] == manager_phone:
        return "❌ Error: You cannot delete your own profile. Access denied."

    # 3. Perform the deletion in MongoDB using company_id filter for safety
    result = team_col.delete_one({"phone": employee['phone'], "company_id": company_id})
    
    # 4. Return result
    if result.deleted_count > 0:
        return f"✅ Successfully removed {employee['name'].title()} from the company database."
    else:
        return f"⚠️ Error: Found {employee['name'].title()} but failed to remove from MongoDB."
    
    
def process_task(user_command, sender_phone, company_id, message=None, role="manager"):
    # Always load fresh state for the specific company
    state = load_state(company_id)
    user_state = state.get(sender_phone, {})
    pending = user_state.get("pending", {})
    
    # 1. State-Based Logic (Digits for Disambiguation and Yes/No for Updates)
    # We execute this BEFORE the AI call to ensure pending actions take priority.

    # Handle Digit Selections (Disambiguation)
    if pending and user_command.strip().isdigit() and pending.get("action") == "disambiguate_task":
        choice = int(user_command.strip()) - 1
        matches = pending.get("context", {}).get("matches", [])
        if 0 <= choice < len(matches):
            selected = matches[choice]
            data = pending["data"]
            
            # FIXED: Added company_id to the call
            reply, _ = assign_task(data, selected, message, sender_phone, company_id)
            
            # FIXED: Added company_id to state loading/saving
            state = load_state(company_id)
            if sender_phone in state:
                state[sender_phone].pop("pending", None)
                save_state(state, company_id)
            return reply, data
        else:
            return f"Invalid choice. Please reply with a number between 1 and {len(matches)}.", None

    # Handle Yes/No Confirmations
    if pending and user_command.strip().lower() in ["yes", "no"] and pending.get("action") == "confirm_update":
        if user_command.strip().lower() == "yes":
            # FIXED: Added company_id to team loading/saving
            team = load_team(company_id)
            existing_index = pending["context"]["existing_index"]
            new_data = pending["data"]
            
            # Update profile within the company partition
            team[existing_index]["email"] = new_data.get("email") or team[existing_index]["email"]
            team[existing_index]["phone"] = new_data.get("phone") or team[existing_index]["phone"]
            save_team(team, company_id)
            reply = f" Updated {team[existing_index]['name'].title()}'s profile."
            
            # FIXED: Added company_id to state loading/saving
            state = load_state(company_id)
            if sender_phone in state:
                state[sender_phone].pop("pending", None)
                save_state(state, company_id)
            return reply, None
        else:
            # FIXED: Added company_id to state loading/saving
            state = load_state(company_id)
            if sender_phone in state:
                state[sender_phone].pop("pending", None)
                save_state(state, company_id)
            # FIXED: Added company_id to add_employee call
            return add_employee(pending["data"], sender_phone, company_id)

    # 2. Main AI processing with Gemini (Prompt remains exactly as requested)
    today = datetime.datetime.now()
    
    prompt = f"""
Today's date is {today.strftime('%A, %b %d, %Y')}.
Current Company ID: {company_id}
Your Role: {role.upper()}

You are a multi-tenant Task Manager Bot. 
Follow these HIERARCHY RULES strictly:
1. CHAIRMAN: Only the Chairman can 'add_employee' with role='manager' or 'employee'. They can delete anyone.
2. MANAGER: Managers can 'add_employee' with role='employee' only. They can assign tasks to employees.
3. EMPLOYEE: Can only use 'get_my_pending_tasks' and 'close_task'. They CANNOT add employees or see team reports.

Key Guidelines:
- There is a heirarchal system, so if a person A assigns task to B and C, so A will be called manager of B and C, if B assigns task to D and E, then B will be manager of D and E but still an junior/employee of A 
- If the user asks for their own pending tasks (e.g., "show me all my tasks", "my tasks", "what tasks do I have"), use "get_my_pending_tasks".
- If the user asks for tasks they have assigned to others (e.g., "report of all tasks I have assigned", "tasks I assigned", "tasks assigned by me"), use "get_assigned_by_me_tasks".
- For team-wide report/counts (e.g., "team report", "pending for all"), use "get_all_pending_counts" (Manager only).
- For a specific person's tasks (e.g., "ABC's tasks"), use "get_user_pending_tasks" (Manager only).
- For assigning tasks, use "assign_task".
- For closing a task, use "close_task".

Possible actions:
- assign_task
{{  
  "action": "assign_task",
  "name": "name1, name2, etc in lowercase",
  "task": "full task description",
  "deadline": "ISO datetime or null"
}}
- add_employee
{{
  "action": "add_employee",
  "name": "person name lowercase",
  "email": "email or empty string",
  "phone": "international phone without + or empty string"
}}
- get_user_pending_tasks 
{{
  "action": "get_user_pending_tasks",
  "name": "person name lowercase",
  "limit": 10
}}
- get_all_pending_counts 
{{
  "action": "get_all_pending_counts"
}}
- get_my_pending_tasks
{{
  "action": "get_my_pending_tasks",
  "limit": 10,
  "today_only": false
}}
- get_assigned_by_me_tasks
{{
  "action": "get_assigned_by_me_tasks",
  "limit": 10,
  "today_only": false
}}
- close_task
{{
  "action": "close_task",
  "task_id": "the numeric ID of the task",
  "remarks": "closure comments or status remarks"
}}
- error
{{
  "action": "error",
  "message": "short error"
}}
- get_team_performance 
{{
  "action": "get_team_performance"
}}
- get_employee_performance
{{
  "action": "get_employee_performance",
  "name": "person name lowercase"
}}
- delete_employee
{{
  "action": "delete_employee",
  "name": "person name lowercase"
}}
Only JSON. No markdown.
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        clean_text = response.text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:].strip()
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3].strip()
        data = json.loads(clean_text)
    except Exception as e:
        print("Gemini Error:", e)
        return "Sorry, AI is having trouble understanding. Try again.", None

    action = data.get("action")

    # 3. Action Handling
    # 3. Action Handling
    if action == "get_my_pending_tasks":
        limit = data.get("limit", 5)
        today_only = data.get("today_only", False)
        # Pass company_id to ensure the user only sees their tasks within their specific company partition
        return get_pending_tasks(sender_phone, company_id, limit=limit, today_only=today_only), data

    # Requirement: Chairman sees all, Manager sees their team
    elif action == "get_all_pending_counts":
        if role not in ["manager", "chairman"]: 
            return "Access Denied: Managers or the Chairman only.", data
        
        # Load all tasks for this specific company partition
        all_company_tasks = load_tasks(company_id)
        
        if role == "chairman":
            report_data = all_company_tasks
            report_title = "Company-Wide Pending Tasks"
        else: # manager
            report_data = [t for t in all_company_tasks if t.get('manager_phone') == sender_phone]
            report_title = "Team Pending Tasks"
            
        return format_task_list(report_data, report_title, is_assigned=True), data

    # Logic: Shows tasks personally assigned by the sender within the company
    elif action == "get_assigned_by_me_tasks":
        tasks = load_tasks(company_id)
        my_assigned = [t for t in tasks if t.get('manager_phone') == sender_phone]
        return format_task_list(my_assigned, "Tasks Assigned by Me", is_assigned=True), data

    # Logic: Search for a specific person's tasks within the company
    elif action == "get_user_pending_tasks":
        if role not in ["manager", "chairman"]: 
            return "Access Denied: Managers or the Chairman only.", data
            
        target_name = data.get("name", "").lower()
        team = load_team(company_id)
        
        # Isolation: Search only within the company's team list
        employee = next((e for e in team if target_name in e.get("name", "").lower()), None)
        
        if not employee: 
            return f"Could not find {target_name} in your company team.", data

        tasks = load_tasks(company_id)
        user_tasks = [t for t in tasks if t.get('assignee_phone') == employee['phone']]
        return format_task_list(user_tasks, f"Pending Tasks for {target_name.title()}", is_assigned=True), data
    
    elif action == "add_employee":
        # Restricted Hierarchy: Employees cannot add new members
        if role == "employee": 
            return "Access Denied: Only Managers or the Chairman can add members.", data
        # Pass company_id and role to ensure handler can restrict Manager-level creation to the Chairman
        return handle_add_employee(data, sender_phone, company_id, role)

    elif action == "assign_task":
        # Restricted Hierarchy: Employees cannot assign tasks
        if role == "employee": 
            return "Access Denied: Only Managers or the Chairman can assign tasks.", data
            
        names = [n.strip() for n in data.get('name', '').split(',')]
        all_replies = []
        for individual_name in names:
            temp_data = data.copy()
            temp_data['name'] = individual_name
            # Pass company_id to the assignment helper for isolation
            reply, _ = handle_assign_task(temp_data, sender_phone, company_id, message)
            all_replies.append(reply)
        return "\n\n".join(all_replies), data

    elif action == "close_task":
        # Pass company_id to verify the task belongs to the user's company partition
        return handle_close_task(data, sender_phone, company_id)
    
    # REQUIREMENT 1: Team-wide stats (Partitioned by company)
    elif action == "get_team_performance":
        if role not in ["manager", "chairman"]: 
            return "Access Denied: This feature is for management only.", data
        return get_performance_stats(company_id=company_id), data

    # REQUIREMENT 2: Specific employee stats (Partitioned by company)
    elif action == "get_employee_performance":
        if role not in ["manager", "chairman"]: 
            return "Access Denied: This feature is for management only.", data
        
        target_name = data.get("name", "").lower()
        team = load_team(company_id)
        
        employee = next((e for e in team if target_name in e.get("name", "").lower()), None)
        if not employee:
            return f"Could not find employee '{target_name}' in your company team.", data
            
        return get_performance_stats(company_id=company_id, target_phone=employee['phone']), data
    
    elif action == "delete_employee":
        # CRITICAL SECURITY: Only the Chairman can delete profiles
        if role != "chairman":
            return "Unauthorized. Only the company Chairman can delete members.", data
            
        target_name = data.get("name", "").lower()
        if not target_name:
            return "Please specify the name of the person you want to delete.", data
            
        return delete_employee(target_name, sender_phone, company_id)

    else:
        # Save the conversational state specifically for this company partition
        save_state(state, company_id)
        return data.get("message", "I didn't understand that command."), data

# --- Helper function for the new action ---
def get_assigned_by_me_tasks(phone, company_id):
    # FIXED: Pass company_id to load only relevant tasks
    tasks = load_tasks(company_id) 
    my_tasks = [t for t in tasks if t.get('manager_phone') == phone]
    
    if not my_tasks:
        return "You haven't assigned any tasks yet."

    now = datetime.datetime.now()
    
    # Categories for Requirement 3
    completed, overdue, due_today, upcoming = [], [], [], []
    # Dictionary for Team Pending Task Count summary
    team_counts = {}

    for t in my_tasks:
        assignee_name = t.get('assignee_name', 'Unknown').title()
        deadline_dt = datetime.datetime.fromisoformat(t['deadline'].replace("Z", ""))
        
        # Track pending counts for the bottom summary
        if t['status'] != 'done':
            team_counts[assignee_name] = team_counts.get(assignee_name, 0) + 1

        # Categorize tasks
        if t['status'] == 'done':
            completed.append(t)
        elif deadline_dt < now:
            overdue.append(t)
        elif deadline_dt.date() == now.date():
            due_today.append(t)
        else:
            upcoming.append(t)

    # Build the final formatted string
    report = " *Task Assignment Report*\n"
    
    # Use the helper to format each section exactly as requested
    report += format_report_section(" OVERDUE", overdue, now)
    report += format_report_section(" DUE TODAY", due_today, now)
    report += format_report_section(" UPCOMING", upcoming, now)
    report += format_report_section(" COMPLETED", completed, now)

    # Add the "Team Pending Task Count" at the bottom
    if team_counts:
        report += "\n*team pending task count*\n"
        for name, count in team_counts.items():
            report += f"{name}: {count}\n"

    return report


def format_report_section(title, task_list, now):
    if not task_list:
        return ""
    
    section = f"\n* {title}*\n"
    for i, t in enumerate(task_list, 1):
        dt = datetime.datetime.fromisoformat(t['deadline'].replace("Z", ""))
        
        # Specific formatting: Show "Today" if it matches, else show the Date
        if dt.date() == now.date():
            time_str = f"{dt.strftime('%I:%M %p')} Today"
        else:
            time_str = dt.strftime("%d %b")
        
        assignee = t.get('assignee_name', 'Unknown').title()
        
        # Requirement 6: Specific "Done" status format
        status_note = ""
        if t['status'] == 'done':
            # You can customize "closed by manager" or use the actual remarks
            status_note = f" (Done: {t.get('remarks', 'closed by manager')})"
        
        section += (f"{i}. {t['task']} (to {assignee})    task id: {t['task_id']}\n"
                    f"   Due: {time_str}{status_note}\n")
    return section

def handle_close_task(data, sender_phone, company_id):
    # Load only the company's tasks
    tasks = load_tasks(company_id)
    task_id = str(data.get("task_id"))
    remarks = data.get("remarks", "No remarks provided.")
   
    # Find the task assigned to this sender with this ID within their specific company
    task_index = next((i for i, t in enumerate(tasks) if str(t.get("task_id")) == task_id and t.get("assignee_phone") == sender_phone), None)
   
    if task_index is None:
        return f"Could not find a pending task with ID #{task_id} assigned to you.", None
        
    # Update Task Status
    tasks[task_index]["status"] = "done"
    tasks[task_index]["remarks"] = remarks
    # Save tasks back to the company partition
    save_tasks(tasks, company_id)
   
    task_name = tasks[task_index]["task"]
    manager_phone = tasks[task_index].get("manager_phone")
    assignee_name = tasks[task_index].get("assignee_name", "Employee").title()
    
    # Notify Manager of the closure
    if manager_phone:
        manager_msg = f" *Task Completed*\n\nEmployee: {assignee_name}\nTask: {task_name}\nRemarks: {remarks}"
        try:
            send_whatsapp_message(manager_phone, manager_msg, PHONE_NUMBER_ID)
        except Exception as e:
            print(f"Failed to notify manager: {e}")
            
    return f" Task #{task_id} marked as completed. Your manager has been notified.", data

def handle_get_specific_user_tasks(data, sender_phone, company_id):
    target_name = data.get("name", "").lower()
    # Pass company_id
    team = load_team(company_id)
   
    # Find the employee record within the company
    employee = next((e for e in team if e.get("name") == target_name and e.get("manager_phone") == sender_phone), None)
   
    if not employee:
        return f"Could not find employee '{target_name}' in your team.", None
   
    # Pass company_id
    return get_pending_tasks(employee['phone'], company_id, limit=10), None
   
def handle_add_employee(data, sender_phone, company_id, requester_role):
    name_key = data.get("name", "").lower().strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    
    if not name_key:
        return "Please provide a name.", data
    if not email and not phone:
        return "Please provide at least email or phone.", data
    
    # Load company team for duplicate/update checks
    team = load_team(company_id)
    name_lower = name_key.lower()
    matches = [m for m in team if name_lower in m["name"].lower()]
    
    if matches:
        state = load_state(company_id)
        state[sender_phone] = {
            "pending": {
                "action": "confirm_update",
                "data": data,
                "context": {"existing_index": team.index(matches[0])}
            }
        }
        # Save state with company_id
        save_state(state, company_id)
        existing = matches[0]
        return (f"Found existing {name_key.title()} (Email: {existing.get('email','none')}, "
                f"Phone: {existing.get('phone','none')}).\nUpdate this profile? Reply yes/no"), data
    
    # ENFORCE HIERARCHY: Determine the role being assigned
    target_role = data.get("role", "employee").lower()
    if requester_role == "manager" and target_role == "manager":
        return "❌ Error: Managers cannot add other Managers. Only the company Chairman has this authority.", data
    
    # Proceed to add the new member to this company
    return add_employee(data, sender_phone, company_id)

def add_employee(data, sender_phone, company_id):
    team = load_team(company_id)
    
    # Get the phone number and remove any extra spaces
    phone = data.get("phone", "").strip()
    
    # Normalize phone: Add 91 if it is a 10-digit number missing the country code
    if len(phone) == 10 and not phone.startswith('91'):
        phone = f"91{phone}"
    
    # --- NEW DUPLICATE CHECK ---
    # Check if this phone number is already assigned to someone in the team list
    existing_member = next((e for e in team if e.get("phone") == phone), None)
    
    if existing_member:
        return (f"❌ Error: A user with the phone number {phone} already exists "
                f"({existing_member['name'].title()}). Duplicate entries are not allowed."), data

    email = data.get("email", "").strip()
    
    new_member = {
        "name": data["name"].lower(),
        "email": email,
        "phone": phone,
        "role": data.get("role", "employee"), # AI determines if Manager or Employee
        "company_id": company_id, 
        "manager_phone": sender_phone
    }
    
    team.append(new_member)
    save_team(team, company_id)
    
    reply = f" New employee added: {data['name'].title()}\n"
    
    # 1. Generate the authorization link
    auth_link = get_authorization_url(phone) if phone else None
    
    if auth_link:
        welcome_msg = (f"Hello {data['name'].title()}! 🚀\n\n"
                       f"You've been added to the Task Manager. To sync tasks to your Google Calendar, "
                       f"please authorize here: {auth_link}")
        # 2. Send via WhatsApp
        if phone:
            try:
                send_whatsapp_message(phone, welcome_msg, PHONE_NUMBER_ID)
                reply += f"📩 Authorization link sent via WhatsApp to {phone}.\n"
            except Exception as e:
                print(f"WhatsApp Auth Send Failed: {e}")
        # 3. Send via Email (Using Manager's Gmail)
        if email and MANAGER_CREDS:
            try:
                gmail_service = build('gmail', 'v1', credentials=MANAGER_CREDS)
                msg = EmailMessage()
                msg.set_content(welcome_msg)
                msg['Subject'] = 'Action Required: Authorize Task Manager Calendar'
                msg['From'] = 'me'
                msg['To'] = email
                gmail_service.users().messages().send(
                    userId="me",
                    body={'raw': base64.urlsafe_b64encode(msg.as_bytes()).decode()}
                ).execute()
                reply += f" Authorization link sent via Email to {email}."
            except Exception as e:
                print(f"Email Auth Send Failed: {e}")
                reply += "\n Email sending failed. Check your Gmail connection."
    
    return reply, data

def handle_assign_task(data, sender_phone, company_id, message):
    # Pass company_id to load only the company's team
    team = load_team(company_id)
    name_key = data.get("name", "").strip()
    if not name_key:
        return "Please specify a person's name in the task.", data
    name_lower = name_key.lower()
    
    # Partial match within the company-specific team
    matches = [
        member for member in team
        if name_lower in member["name"].lower()
    ]
    
    # No one found in this specific company
    if not matches:
        return f"No one found with name containing '{name_key}'. Add them first with 'Add employee...'", data
    
    # Exactly one match → assign directly
    if len(matches) == 1:
        selected = matches[0]
        # Pass company_id to final assignment function
        return assign_task(data, selected, message, sender_phone, company_id)
    
    # Multiple matches → disambiguate within the company context
    state = load_state(company_id)
    state[sender_phone] = {
        "pending": {
            "action": "disambiguate_task",
            "data": data,
            "context": {"matches": matches}
        }
    }
    # Save partitioned state
    save_state(state, company_id)
    
    # Build user-friendly list from company matches
    options = "\n".join([
        f"{i+1}. {m['name'].title()} — Email: {m.get('email', 'none')}, Phone: {m.get('phone', 'none')}"
        for i, m in enumerate(matches)
    ])
    return (
        f"Multiple people found with name containing '{name_key}':\n{options}\n\n"
        f"Which one do you mean? Reply with the number (1, 2, ...)"
    ), data

def assign_task(data, selected, message, sender_phone, company_id):
    today = datetime.datetime.now()
    deadline = data.get('deadline')
    if not deadline:
        start = today.replace(hour=9, minute=0, second=0, microsecond=0)
        # Removed "Z" to prevent UTC override
        deadline = start.isoformat()
        end_time = (start + datetime.timedelta(hours=1)).isoformat()
    else:
        # Remove "Z" and treat as local IST time
        start_dt = datetime.datetime.fromisoformat(deadline.replace("Z", ""))
        deadline = start_dt.isoformat()
        end_time = (start_dt + datetime.timedelta(hours=1)).isoformat()
    assignee_name = data['name'].title()
    assignee_phone = selected.get('phone', "")
    assignee_email = selected.get('email', "")
    if not assignee_email:
        return f"Task assigned to {assignee_name}, but no email found in team — email not sent.", data
    # 1. Calendar: Only in employee's calendar if they connected
    # Updated: Passed company_id to ensure correct token retrieval for multi-tenancy
    assignee_creds = get_creds_for_user(assignee_phone, company_id) if assignee_phone else None
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
                    # Changed timeZone to Asia/Kolkata
                    'start': {'dateTime': deadline, 'timeZone': 'Asia/Kolkata'},
                    'end': {'dateTime': end_time, 'timeZone': 'Asia/Kolkata'}
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
            msg.set_content(f"New task assigned to you:\n\nTask: {data['task']}\nDue: {data.get('deadline') or 'ASAP'}\n\n— Assigned via WhatsApp AI Task Bot")
            msg['Subject'] = 'New Task Assignment'
            msg['From'] = 'me'
            msg['To'] = assignee_email
            file_path = None
            if message and "document" in message:
                doc = message["document"]
                downloaded = download_document(doc["id"], doc["mime_type"], doc.get("filename", "document"))
                if downloaded:
                    file_path, mime_type, filename = downloaded
                    with open(file_path, 'rb') as f:
                        msg.add_attachment(f.read(), maintype=mime_type.split('/')[0], subtype=mime_type.split('/')[1], filename=filename)
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
    # 3. WhatsApp to employee
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
          
    tasks = load_tasks(company_id)
    # Fix: Correctly define max_id by finding the highest ID within the company's task list
    max_id = max([t.get('task_id', 0) for t in tasks] or [0])
    new_task = {
        "task_id": max_id + 1,
        "task": data['task'],
        "company_id": company_id, # CRITICAL for partitioning data
        "assignee_name": selected.get('name'),
        "assignee_phone": selected.get('phone'),
        "manager_phone": sender_phone,
        "deadline": deadline,
        "status": "pending",
        "remarks": ""
    }
    tasks.append(new_task)
    save_tasks(tasks, company_id)
    reply = f" Task assigned to {assignee_name} (Due: {data.get('deadline', 'ASAP')})"
    reply += "\n Event created in their calendar" if calendar_created else f"\n {calendar_note}"
    reply += "\n Email sent from your account" if email_sent else "\n Email not sent"
    reply += "\n WhatsApp notification sent" if whatsapp_sent else "\n WhatsApp not sent"
    return reply, data

def handle_message(user_command, sender_phone, phone_number_id, message=None, full_message=None):
    # 1. Standardize sender_phone
    if len(sender_phone) == 10 and not sender_phone.startswith('91'):
        sender_phone = f"91{sender_phone}"
    
    # Look up user in the database
    user = team_col.find_one({"phone": sender_phone})
    
    # --- AUTHORIZATION FEATURE REMOVED ---
    # Instead of blocking unknown users, we assign them a default setup role
    if not user:
        # Defaulting to 'MASTER_CO' and 'chairman' role for initial setup/testing
        company_id = "MASTER_CO"
        role = "chairman" 
    else:
        company_id = user.get("company_id")
        role = user.get("role", "employee") 
    # ------------------------------------------

    state = load_state(company_id) 
    processed = load_processed_messages()
  
    # 2. De-duplication check
    msg_id = full_message.get("id") if full_message else (message["document"].get("id") if message and "document" in message else None)
    if msg_id and msg_id in processed:
        return

    # 4. Handle Incoming Documents (Assignment Flow)
    if not user_command and message and "document" in message:
        state[sender_phone] = {"pending_document": message["document"]}
        save_state(state, company_id) 
        
        doc_reply = " Document received! Who should I assign this to? (e.g., 'Assign this to Adi by Friday')"
        send_whatsapp_message(sender_phone, doc_reply, phone_number_id)
        
        if msg_id:
            processed.add(msg_id)
            save_processed_messages(processed)
        return

    # 5. Process Commands via Gemini
    if user_command:
        # Passes the company_id and role (either from DB or default) to the AI
        status, _ = process_task(user_command.strip(), sender_phone, company_id, message, role=role)
        
        # Send the final response back to WhatsApp
        try:
            send_whatsapp_message(sender_phone, str(status), phone_number_id)
        except Exception as e:
            print(f"Critical WhatsApp Send Failure: {e}")

        # Reload and cleanup state
        state = load_state(company_id) 
        if sender_phone in state:
            state[sender_phone].pop("pending_document", None)
            save_state(state, company_id)

    # 6. Save message ID to prevent double-processing
    if msg_id:
        processed.add(msg_id)
        save_processed_messages(processed)