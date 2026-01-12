import os
import datetime
import requests
import json
import base64
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pymongo import MongoClient
import certifi
from dotenv import load_dotenv
from email.message import EmailMessage

# Google Auth imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================
MONGO_URI = os.getenv("MONGO_URI")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
CLIENT_SECRETS_FILE = os.getenv("CLIENT_SECRETS_FILE")
SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/gmail.send"]
REDIRECT_URI = os.getenv("REDIRECT_URI")

# Appsavy API Configuration
APPSAVY_BASE_URL = "https://configapps.appsavy.com/api/AppsavyRestService"
APPSAVY_HEADERS = {
    "sid": os.getenv("APPSAVY_SID", "607"),
    "pid": os.getenv("APPSAVY_PID", "309"),
    "fid": os.getenv("APPSAVY_FID", "10344"),
    "cid": os.getenv("APPSAVY_CID", "64"),
    "uid": os.getenv("APPSAVY_UID", "TM_API"),
    "roleid": os.getenv("APPSAVY_ROLEID", "1627"),
    "TokenKey": os.getenv("APPSAVY_TOKEN_KEY")
}

# ============================================================================
# PYDANTIC MODELS
# ============================================================================
class Task(BaseModel):
    task_id: int
    task: str
    assignee_name: str
    assignee_phone: str
    manager_phone: str
    deadline: str
    status: str = "pending"
    remarks: str = ""

class UserProfile(BaseModel):
    name: str
    role: str
    phone_id: str
    email: Optional[str] = None
    supervisor_id: Optional[str] = None
    subordinates: List[str] = []

class TeamMember(BaseModel):
    name: str
    email: Optional[str] = None
    phone: str
    manager_phone: str

class AssigneeInfo(BaseModel):
    login: str
    name: str

class TaskDetail(BaseModel):
    task_id: str
    task_name: str
    description: str
    status: str
    assignee: str
    deadline: str

# ============================================================================
# DATABASE SETUP
# ============================================================================
db_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = db_client['ai_task_manager']

users_col = db['users']
tasks_col = db['tasks']
team_col = db['team']
state_col = db['state']
processed_col = db['processed_messages']
tokens_col = db['tokens']

# ============================================================================
# MANAGER CREDENTIALS (for email sending)
# ============================================================================
MANAGER_CREDS = None
manager_token_data = tokens_col.find_one({"phone": os.getenv("MANAGER_PHONE")})
if manager_token_data and "google_credentials" in manager_token_data:
    MANAGER_CREDS = Credentials.from_authorized_user_info(
        manager_token_data["google_credentials"], SCOPES
    )

# ============================================================================
# PYDANTIC AI AGENT SETUP
# ============================================================================
agent = Agent(
    'google-gla:gemini-1.5-flash',
    system_prompt=(
        "You are a Task Manager Assistant. Use the provided tools to manage tasks, users, and teams. "
        "When asked for reports, categorize tasks into OVERDUE, DUE TODAY, UPCOMING, and COMPLETED. "
        "Always format output clearly using bullet points when appropriate. "
        "You can create tasks, update task status, fetch assignees, and get task details from external APIs."
    )
)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================
def load_processed_messages():
    return {d["msg_id"] for d in processed_col.find({}, {"msg_id": 1})}

def save_processed_messages(processed_set):
    for msg_id in processed_set:
        processed_col.update_one({"msg_id": msg_id}, {"$set": {"msg_id": msg_id}}, upsert=True)

def save_team(team_list):
    if not team_list:
        return
    team_col.delete_many({})
    team_col.insert_many(team_list)

def save_tasks(tasks_list):
    tasks_col.delete_many({})
    if tasks_list:
        tasks_col.insert_many(tasks_list)

def get_creds_for_user(phone_number):
    user_data = tokens_col.find_one({"phone": phone_number})
    if user_data and "google_credentials" in user_data:
        creds_data = user_data["google_credentials"]
        creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            tokens_col.update_one(
                {"phone": phone_number},
                {"$set": {"google_credentials": json.loads(creds.to_json())}}
            )
        return creds
    return None

def get_authorization_url(phone_number):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        state=phone_number,
        prompt='consent'
    )
    return auth_url

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

def send_whatsapp_message(phone, message, phone_number_id):
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.json()

def send_whatsapp_document(phone, file_path, filename, mime_type, phone_number_id):
    """Send document via WhatsApp"""
    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    
    with open(file_path, 'rb') as f:
        files = {'file': (filename, f, mime_type)}
        response = requests.post(url, headers=headers, files=files)
    return response.json()

# ============================================================================
# APPSAVY API INTEGRATION TOOLS
# ============================================================================

@agent.tool
def get_assignees_from_api(ctx: RunContext[None]) -> List[AssigneeInfo]:
    """Fetch list of assignees from Appsavy API."""
    url = f"{APPSAVY_BASE_URL}/GetDataJSONClient"
    payload = {
        "Event": "0",
        "Child": [{"Control_Id": "106771", "AC_ID": "111057"}]
    }
    
    try:
        response = requests.post(url, headers=APPSAVY_HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()
        
        assignees = []
        if "data" in data:
            for item in data["data"]:
                assignees.append(AssigneeInfo(
                    login=item.get("LOGIN", ""),
                    name=item.get("PARTICIPANTS", "")
                ))
        return assignees
    except Exception as e:
        print(f"Error fetching assignees: {e}")
        return []

@agent.tool
def create_task_in_appsavy(
    ctx: RunContext[None],
    task_name: str,
    description: str,
    assignee_logins: List[str],
    expected_end_date: str,
    priority: str = "N",
    documents: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """Create a new task in Appsavy system."""
    url = f"{APPSAVY_BASE_URL}/PushdataJSONClient"
    
    details_child = [{"SEL": "Y", "LOGIN": login, "PARTICIPANTS": login.split("-")[-1] if "-" in login else login} 
                     for login in assignee_logins]
    
    docs_child = []
    if documents:
        for doc in documents:
            docs_child.append({
                "DOCUMENT": {"VALUE": doc.get("filename", "document.pdf"), "BASE64": doc.get("base64", "")},
                "DOCUMENT_NAME": doc.get("name", "Task Document")
            })
    
    payload = {
        "SID": APPSAVY_HEADERS["sid"],
        "DESCRIPTION": description,
        "EXPECTED_END_DATE": expected_end_date,
        "TASK_NAME": task_name,
        "PRIORTY_TASK": priority,
        "TYPE": "TYPE",
        "DETAILS": {"CHILD": details_child},
        "DOCUMENTS": {"CHILD": docs_child}
    }
    
    try:
        response = requests.post(url, headers=APPSAVY_HEADERS, json=payload)
        response.raise_for_status()
        return {"success": True, "message": f"Task '{task_name}' created successfully", "response": response.json()}
    except Exception as e:
        return {"success": False, "message": f"Failed to create task: {str(e)}"}

@agent.tool
def update_task_status_in_appsavy(
    ctx: RunContext[None],
    task_id: str,
    status: str,
    comments: str = "",
    document_base64: str = "",
    document_filename: str = ""
) -> Dict[str, Any]:
    """Update task status in Appsavy system."""
    url = f"{APPSAVY_BASE_URL}/PushdataJSONClient"
    
    payload = {
        "SID": APPSAVY_HEADERS["sid"],
        "COMMENTS": comments,
        "STATUS": status,
        "TASK_ID": task_id,
        "UPLOAD_DOCUMENT": document_filename,
        "BASE64": document_base64
    }
    
    try:
        response = requests.post(url, headers=APPSAVY_HEADERS, json=payload)
        response.raise_for_status()
        return {"success": True, "message": f"Task {task_id} updated to {status}", "response": response.json()}
    except Exception as e:
        return {"success": False, "message": f"Failed to update task: {str(e)}"}

@agent.tool
def get_tasks_from_appsavy(
    ctx: RunContext[None],
    status_filter: Optional[str] = None,
    user_login: Optional[str] = None,
    assignment_type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
) -> List[TaskDetail]:
    """Fetch tasks from Appsavy system with filters."""
    url = f"{APPSAVY_BASE_URL}/GetDataJSONClient"
    
    headers = APPSAVY_HEADERS.copy()
    headers["fid"] = "10349"
    
    parent_filters = [
        {"Control_Id": "106825", "Value": status_filter or "", "Data_Form_Id": ""},
        {"Control_Id": "106824", "Value": from_date or "", "Data_Form_Id": ""},
        {"Control_Id": "106827", "Value": user_login or "", "Data_Form_Id": ""},
        {"Control_Id": "106829", "Value": to_date or "", "Data_Form_Id": ""},
        {"Control_Id": "107046", "Value": assignment_type or "", "Data_Form_Id": ""},
        {"Control_Id": "107809", "Value": "0", "Data_Form_Id": ""}
    ]
    
    payload = {
        "Event": "106830",
        "Child": [{"Control_Id": "106831", "AC_ID": "110803", "Parent": parent_filters}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        tasks = []
        if "data" in data:
            for item in data["data"]:
                tasks.append(TaskDetail(
                    task_id=item.get("TASK_ID", ""),
                    task_name=item.get("TASK_NAME", ""),
                    description=item.get("DESCRIPTION", ""),
                    status=item.get("STATUS", ""),
                    assignee=item.get("ASSIGNEE", ""),
                    deadline=item.get("DEADLINE", "")
                ))
        return tasks
    except Exception as e:
        print(f"Error fetching tasks: {e}")
        return []

# ============================================================================
# DATABASE TOOLS
# ============================================================================

@agent.tool
def load_tasks(ctx: RunContext[None]) -> List[Dict]:
    """Returns list of tasks sorted by deadline."""
    return list(tasks_col.find({}, {"_id": 0}).sort("deadline", 1))

@agent.tool
def load_team(ctx: RunContext[None]) -> List[Dict]:
    """Loads team from DB."""
    team_list = list(team_col.find({}, {"_id": 0}))
    if not team_list:
        team_env = os.getenv("TEAM_JSON")
        if team_env:
            try:
                team_list = json.loads(team_env)
                if team_list:
                    team_col.insert_many(team_list)
            except:
                pass
    return team_list

@agent.tool
def load_state(ctx: RunContext[None]) -> Dict[str, Any]:
    """Fetches global application state."""
    doc = state_col.find_one({"id": "global_state"})
    return doc.get("data", {}) if doc else {}

@agent.tool
def save_state(ctx: RunContext[None], state_dict: Dict[str, Any]) -> str:
    """Updates global application state."""
    state_col.update_one({"id": "global_state"}, {"$set": {"data": state_dict}}, upsert=True)
    return "State saved successfully."

@agent.tool
def add_employee(ctx: RunContext[None], name: str, email: str, phone: str, manager_phone: str) -> str:
    """Add new employee to team."""
    team = load_team(ctx)
    
    if len(phone) == 10 and not phone.startswith('91'):
        phone = f"91{phone}"
    
    existing = next((e for e in team if e.get("phone") == phone), None)
    if existing:
        return f"❌ Employee with phone {phone} already exists ({existing['name'].title()})."
    
    new_member = {"name": name.lower(), "email": email, "phone": phone, "manager_phone": manager_phone}
    team.append(new_member)
    save_team(team)
    
    auth_link = get_authorization_url(phone) if phone else None
    reply = f"✅ New employee added: {name.title()}\n"
    
    if auth_link:
        welcome_msg = f"Hello {name.title()}! 🚀\n\nYou've been added to Task Manager. Authorize here: {auth_link}"
        if phone:
            try:
                send_whatsapp_message(phone, welcome_msg, PHONE_NUMBER_ID)
                reply += f"📩 Authorization link sent via WhatsApp.\n"
            except Exception as e:
                print(f"WhatsApp failed: {e}")
    
    return reply

@agent.tool
def delete_employee(ctx: RunContext[None], target_name: str, manager_phone: str) -> str:
    """Delete an employee from team."""
    team = load_team(ctx)
    employee = next((e for e in team if target_name.lower() in e.get("name", "").lower()), None)
    
    if not employee:
        return f"❌ Could not find employee '{target_name.title()}'."
    
    if employee['phone'] == manager_phone:
        return "❌ You cannot delete your own profile."
    
    result = team_col.delete_one({"phone": employee['phone']})
    
    if result.deleted_count > 0:
        return f"✅ Successfully removed {employee['name'].title()}."
    else:
        return f"⚠️ Error removing {employee['name'].title()} from database."

# ============================================================================
# TASK FORMATTING TOOLS
# ============================================================================

@agent.tool
def format_task_list(ctx: RunContext[None], task_list: List[Dict], title: str, is_assigned: bool = False) -> str:
    """Groups tasks into OVERDUE, DUE TODAY, UPCOMING, COMPLETED."""
    if not task_list:
        return f"*{title}*\nNo tasks found.\n"
    
    now = datetime.datetime.now()
    overdue, due_today, upcoming, completed = [], [], [], []
    team_counts = {}

    for t in task_list:
        assignee_name = t.get('assignee_name', 'Unknown').title()
        if t['status'] != 'done':
            team_counts[assignee_name] = team_counts.get(assignee_name, 0) + 1

        dt = datetime.datetime.fromisoformat(t['deadline'].replace("Z", ""))
        is_today = dt.date() == now.date()
        time_str = f"{dt.strftime('%I:%M %p')} Today" if is_today else dt.strftime("%d %b")
        assignee_ctx = f" (to {assignee_name})" if is_assigned else ""
        status_note = f" (Done: {t.get('remarks', 'closed')})" if t['status'] == 'done' else ""
        
        task_line = f"{t['task']}{assignee_ctx}    task id: {t['task_id']}\n   Due: {time_str}{status_note}"

        if t['status'] == 'done':
            completed.append(task_line)
        elif dt < now:
            overdue.append(task_line)
        elif is_today:
            due_today.append(task_line)
        else:
            upcoming.append(task_line)

    report = f"*{title}*\n"
    if overdue:
        report += "\n*🔴 OVERDUE*\n" + "\n".join([f"{i+1}. {l}" for i, l in enumerate(overdue)]) + "\n"
    if due_today:
        report += "\n*🟡 DUE TODAY*\n" + "\n".join([f"{i+1}. {l}" for i, l in enumerate(due_today)]) + "\n"
    if upcoming:
        report += "\n*🟢 UPCOMING*\n" + "\n".join([f"{i+1}. {l}" for i, l in enumerate(upcoming)]) + "\n"
    if completed:
        report += "\n*✅ COMPLETED*\n" + "\n".join([f"{i+1}. {l}" for i, l in enumerate(completed)]) + "\n"

    if is_assigned and team_counts:
        report += "\n*Team Pending Task Count*\n"
        for name, count in team_counts.items():
            report += f"{name}: {count}\n"

    return report

@agent.tool
def get_pending_tasks(ctx: RunContext[None], phone: str, limit: int = 5) -> str:
    """Fetch and format pending tasks for user."""
    tasks = load_tasks(ctx)
    my_tasks = [t for t in tasks if t['assignee_phone'] == phone and t['status'] == 'pending']
    return format_task_list(ctx, my_tasks[:limit], "Your Pending Tasks", is_assigned=False)

@agent.tool
def get_assigned_by_me_tasks(ctx: RunContext[None], phone: str) -> str:
    """Get tasks assigned by manager."""
    tasks = load_tasks(ctx)
    my_tasks = [t for t in tasks if t.get('manager_phone') == phone]
    
    if not my_tasks:
        return "You haven't assigned any tasks yet."

    return format_task_list(ctx, my_tasks, "Task Assignment Report", is_assigned=True)

@agent.tool
def get_performance_stats(ctx: RunContext[None], target_phone: Optional[str] = None) -> str:
    """Generate performance report."""
    tasks = load_tasks(ctx)
    team = load_team(ctx)
    now = datetime.datetime.now()
    
    if target_phone:
        display_team = [e for e in team if e.get('phone') == target_phone]
    else:
        display_team = team

    if not display_team:
        return "No employees found."

    report = "*Performance Report*\n" + "="*20 + "\n"

    for member in display_team:
        phone = member.get('phone')
        name = member.get('name', 'Unknown').title()
        member_tasks = [t for t in tasks if t.get('assignee_phone') == phone]
        
        assigned = len(member_tasks)
        completed = len([t for t in member_tasks if t.get('status') == 'done'])
        pending_tasks = [t for t in member_tasks if t.get('status') == 'pending']
        
        within_time = sum(1 for t in pending_tasks 
                         if datetime.datetime.fromisoformat(t['deadline'].replace("Z", "")) > now)
        beyond_time = len(pending_tasks) - within_time

        report += f"\n*Name:* {name}\n"
        report += f"Task Assigned: {assigned}\n"
        report += f"Task Completed: {completed}\n"
        report += f"Task Pending: {len(pending_tasks)}\n"
        report += f"  - Within time: {within_time}\n"
        report += f"  - Beyond time: {beyond_time}\n"
        report += "-"*15 + "\n"

    return report

# ============================================================================
# TASK MANAGEMENT TOOLS
# ============================================================================

@agent.tool
def close_task(ctx: RunContext[None], task_id: str, phone: str, remarks: str = "Task completed") -> str:
    """Close a task and notify manager."""
    tasks = load_tasks(ctx)
    task_index = next((i for i, t in enumerate(tasks) 
                      if str(t.get("task_id")) == task_id and t.get("assignee_phone") == phone), None)
    
    if task_index is None:
        return f"❌ Could not find pending task #{task_id} assigned to you."
    
    tasks[task_index]["status"] = "done"
    tasks[task_index]["remarks"] = remarks
    save_tasks(tasks)
    
    task_name = tasks[task_index]["task"]
    manager_phone = tasks[task_index].get("manager_phone")
    assignee_name = tasks[task_index].get("assignee_name", "Employee").title()
    
    if manager_phone:
        manager_msg = f"✅ *Task Completed*\n\nEmployee: {assignee_name}\nTask: {task_name}\nRemarks: {remarks}"
        try:
            send_whatsapp_message(manager_phone, manager_msg, PHONE_NUMBER_ID)
        except Exception as e:
            print(f"Failed to notify manager: {e}")
    
    try:
        update_task_status_in_appsavy(ctx, task_id, "Closed", remarks)
    except:
        pass
    
    return f"✅ Task #{task_id} marked as completed. Manager notified."

@agent.tool
def assign_task(
    ctx: RunContext[None],
    task_description: str,
    assignee_name: str,
    deadline: Optional[str],
    manager_phone: str
) -> str:
    """Assign a task to a user."""
    team = load_team(ctx)
    name_lower = assignee_name.lower()
    
    matches = [m for m in team if name_lower in m["name"].lower()]
    
    if not matches:
        return f"❌ No one found with name '{assignee_name}'. Add them first."
    
    if len(matches) > 1:
        options = "\n".join([f"{i+1}. {m['name'].title()} — {m.get('phone', 'no phone')}" 
                            for i, m in enumerate(matches)])
        return f"Multiple people found:\n{options}\n\nBe more specific."
    
    selected = matches[0]
    tasks = load_tasks(ctx)
    max_id = max([t.get('task_id', 0) for t in tasks] or [0])
    
    today = datetime.datetime.now()
    if not deadline:
        start = today.replace(hour=9, minute=0, second=0, microsecond=0)
        deadline_iso = start.isoformat()
    else:
        start_dt = datetime.datetime.fromisoformat(deadline.replace("Z", ""))
        deadline_iso = start_dt.isoformat()
    
    new_task = {
        "task_id": max_id + 1,
        "task": task_description,
        "assignee_name": selected.get('name'),
        "assignee_phone": selected.get('phone'),
        "manager_phone": manager_phone,
        "deadline": deadline_iso,
        "status": "pending",
        "remarks": ""
    }
    tasks.append(new_task)
    save_tasks(tasks)
    
    assignee_phone = selected.get('phone')
    if assignee_phone:
        try:
            msg = f"🚀 *New Task Assigned*\n\nTask: {task_description}\nDue: {deadline or 'ASAP'}"
            send_whatsapp_message(assignee_phone, msg, PHONE_NUMBER_ID)
        except Exception as e:
            print(f"WhatsApp failed: {e}")
    
    return f"✅ Task assigned to {selected['name'].title()} (Due: {deadline or 'ASAP'})"

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def handle_message(user_command: str, sender_phone: str, phone_number_id: str, 
                  message: Any = None, full_message: Any = None):
    """Main entry point for handling WhatsApp messages."""
    
    if len(sender_phone) == 10 and not sender_phone.startswith('91'):
        sender_phone = f"91{sender_phone}"
    
    processed = load_processed_messages()
    msg_id = full_message.get("id") if full_message else (
        message.get("document", {}).get("id") if message and "document" in message else None
    )
    
    if msg_id and msg_id in processed:
        return
    
    # Determine role
    team_list = list(team_col.find({}, {"_id": 0}))
    tasks_list = list(tasks_col.find({}, {"_id": 0}))
    
    has_subordinates = any(m.get("manager_phone") == sender_phone for m in team_list)
    has_assigned_tasks = any(t.get("manager_phone") == sender_phone for t in tasks_list)
    is_listed_as_employee = any(m.get("phone") == sender_phone for m in team_list)
    
    if has_subordinates or has_assigned_tasks or not is_listed_as_employee:
        role = "manager"
    else:
        role = "employee"
    
    # Handle document uploads
    if not user_command and message and "document" in message:
        state = load_state(None)
        state[sender_phone] = {"pending_document": message["document"]}
        save_state(None, state)
        
        doc_reply = "📄 Document received! Who should I assign this to? (e.g., 'Assign to John by Friday')"
        send_whatsapp_message(sender_phone, doc_reply, phone_number_id)
        
        if msg_id:
            processed.add(msg_id)
            save_processed_messages(processed)
        return
    
    # Process command via AI
    if user_command:
        today = datetime.datetime.now()
        
        prompt = f"""
Today's date is {today.strftime('%A, %b %d, %Y')}.
User Role: {role.title()}
User Command: "{user_command}"
Sender Phone: {sender_phone}

Analyze the command and use the appropriate tools to respond. Common tasks:
- Fetch tasks: use get_pending_tasks, get_assigned_by_me_tasks, get_tasks_from_appsavy
- Assign task: use assign_task
- Close task: use close_task
- Add employee: use add_employee
- Delete employee: use delete_employee
- Performance: use get_performance_stats
- Fetch assignees from Appsavy: use get_assignees_from_api

Provide a clear, helpful response.
"""
        
        try:
            result = agent.run_sync(prompt)
            response_text = str(result.data) if hasattr(result, 'data') else str(result)
            
            send_whatsapp_message(sender_phone, response_text, phone_number_id)
            
            # Cleanup state
            state = load_state(None)
            if sender_phone in state:
                state[sender_phone].pop("pending_document", None)
                save_state(None, state)
                
        except Exception as e:
            error_msg = f"Sorry, I encountered an error: {str(e)}\nPlease try again or rephrase your request."
            send_whatsapp_message(sender_phone, error_msg, phone_number_id)
            print(f"Error processing command: {e}")
    
    # Save message ID to prevent reprocessing
    if msg_id:
        processed.add(msg_id)
        save_processed_messages(processed)


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Example: Process a message
    handle_message(
        user_command="Show me my pending tasks",
        sender_phone="919876543210",
        phone_number_id=PHONE_NUMBER_ID,
        message=None,
        full_message={"id": "test_msg_123"}
    )