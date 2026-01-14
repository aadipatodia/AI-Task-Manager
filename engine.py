import os
import json
import datetime
import base64
import requests
import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.messages import ModelResponse, ModelRequest, TextPart, UserPromptPart
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from send_message import send_whatsapp_message, send_whatsapp_document
from google_auth_oauthlib.flow import Flow
import difflib

# Load environment variables from .env file
load_dotenv()

# --- LOGGING CONFIGURATION ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- GMAIL & OAUTH CONSTANTS ---
SCOPES = ['https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://ai-task-manager-38w7.onrender.com/oauth2callback")
MANAGER_EMAIL = "patodiaaadi@gmail.com"
conversation_history: Dict[str, List[Any]] = {}

# --- API CONFIGURATION (100% Dependency) ---
APPSAVY_BASE_URL = "https://configapps.appsavy.com/api/AppsavyRestService"
API_CONFIGS = {
    "CREATE_TASK": {
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient",
        "headers": {
            "sid": "604", "pid": "309", "fid": "10344", "cid": "64",
            "uid": "TM_API", "roleid": "1627",
            "TokenKey": "17bce718-18fb-43c4-90bb-910b19ffb34b"
        }
    },
    "GET_ASSIGNEE": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient",
        "headers": {
            "sid": "606", "pid": "309", "fid": "10344", "cid": "64",
            "uid": "TM_API", "roleid": "1627",
            "TokenKey": "d23e5874-ba53-4490-941f-0c70b25f6f56"
        }
    },
    "GET_TASKS": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient",
        "headers": {
            "sid": "610", "pid": "309", "fid": "10349", "cid": "64",
            "uid": "TM_API", "roleid": "1627",
            "TokenKey": "e5b4e098-f8b9-47bf-83f1-751582bfe147"
        }
    },
    "UPDATE_STATUS": {
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient",
        "headers": {
            "sid": "607", "pid": "309", "fid": "10349", "cid": "64",
            "uid": "TM_API", "roleid": "1627",
            "TokenKey": "e5b4e098-f8b9-47bf-83f1-751582bfe147"
        }
    },
    "GET_COUNT": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient",
        "headers": {
            "sid": "616", "pid": "309", "fid": "10408", "cid": "64",
            "uid": "TM_API", "roleid": "1627",
            "TokenKey": "75c6ec2e-9f9c-48fa-be24-d8eb612f4c03"
        }
    }
}

# --- PYDANTIC AI AGENT INITIALIZATION ---
ai_model = GeminiModel('gemini-2.0-flash-exp')

class ManagerContext(BaseModel):
    sender_phone: str
    role: str
    current_time: datetime.datetime = Field(default_factory=datetime.datetime.now)

# --- ENHANCED SYSTEM PROMPT FOR NATURAL CONVERSATION ---
def get_system_prompt(current_time: datetime.datetime) -> str:
    team = load_team()
    # 2. Create a string describing the team for the AI
    team_description = "\n".join([f"- {u['name']} (Login: {u['login_code']})" for u in team])

    current_date_str = current_time.strftime("%Y-%m-%d")
    current_time_str = current_time.strftime("%I:%M %p")
    day_of_week = current_time.strftime("%A")
    
    return f"""

### AUTHORIZED TEAM MEMBERS:
{team_description}
    
You are the Official AI Task Manager Bot for the organization. Identity: TM_API (Manager).
You are a precise, professional assistant with natural language understanding capabilities.

Current Date: {current_date_str} ({day_of_week})
Current Time: {current_time_str}

### CORE PRINCIPLES:
1. **Natural Language Understanding**: Understand user intent from conversational language
2. **Context Awareness**: Use conversation history to understand references
3. **Proactive Clarification**: Ask for missing information naturally
4. **Professional Communication**: Clear, concise, no emojis

### TASK ASSIGNMENT:
* When user wants to assign a task, extract: assignee name, task description, deadline
* Use 'assign_new_task_tool'
  
* **Deadline Logic:**
  - If time mentioned is later than current time → Use today's date
  - If time has already passed today → Use tomorrow's date
  - "tomorrow" → Next day
  - "next week" → 7 days from now
  - No time specified → default to end of current day (23:59)
  - Always format as ISO: YYYY-MM-DDTHH:MM:SS

* **Name Resolution**: Map names to login IDs from team directory. Use fuzzy matching for typos (e.g., 'mddvnl' might match 'mddvvnl').

### TASK STATUS WORKFLOW:
1. **Pending** - Initial state when task is created
2. **Work Done** - Employee uses 'reported' action
3. **Completed** - Manager uses 'close' action to approve

**Status Actions:**
- 'open' → "Open" (employee marks task as acknowledged/started)
- 'partial' → "Partially Closed" (work in progress)
- 'reported' → "Reported Closed" (employee marks as done, awaits approval)

**Role Permissions:**
- Employees: Can mark tasks as 'partial' or 'reported' only
- Managers: Can 'close' (approve) or 'reopen' (reject) tasks

### PERFORMANCE REPORTING:
When user asks about performance, pending tasks, statistics, reports, or task counts:
- Use 'get_performance_report_tool'
- Without name → Report for ALL employees
- With name → Report for specific employee
- Format strictly as:
  Name- [Name]
  Task Assigned- Count of Task [Total] Nos
  Task Completed- Count of task [Closed Status Only] Nos
  Task Pending -
  Within time: [Count]
  Beyond time: [Count]

### TASK LISTING:
When user asks to see tasks, list tasks, pending work:
- Use 'get_task_list_tool'
- Without name → Show tasks for the requesting user
- With name (managers only) → Show tasks for specified employee
- Sort by due date (oldest first)

### TASK ASSIGNMENT BY PHONE:
Support assignment using phone numbers:
- Extract 10-digit number or full format
- Use 'assign_task_by_phone_tool'

### DOCUMENT HANDLING:
- When file received without task details: Ask for assignee name, task description, and deadline
- When file received with partial info: Ask for missing details
- Attach stored file to next task assignment automatically

### MANAGER TASK APPROVAL:
When manager wants to approve/reject completed work:
- Understand approval/rejection phrases
- Use 'update_task_status_tool' with appropriate action

### EMPLOYEES VIEWING TASKS:
Employees can always view their own tasks

### COMMUNICATION STYLE:
- Professional and concise
- No emojis or casual language
- Don't mention internal tool names
- Ask clarifying questions when needed
- Confirm critical actions before executing

### IMPORTANT:
- Ignore WhatsApp headers like '[7:03 pm, 13/1/2026] ABC:' and focus only on the text after the colon.
"""

# --- AUTHORIZED TEAM CONFIGURATION ---
def load_team() -> List[Dict[str, str]]:
    """Load team directory with corrected login codes and participant names based on API docs."""
    return [
        {"name": "mdpvvnl", "phone": "919650523477", "email": "varun.verma@mobineers.com", "login_code": "D-3514-1001", "participant": "MD-PVVNL"},
        {"name": "chairman", "phone": "919310104458", "email": "abhilasha1333@gmail.com", "login_code": "D-3514-1003", "participant": "CHAIRMAN"},
        {"name": "mddvvnl", "phone": "917428134319", "email": "patodiaaadi@gmail.com.com", "login_code": "D-3514-1002", "participant": "MD-DVVNL"},
        {"name": "ce_ghaziabad", "phone": "91XXXXXXXXXX", "email": "ce@example.com", "login_code": "D-3514-1004", "participant": "CE-GHAZIABAD"}
    ]

def get_team_member(name: str) -> Optional[Dict[str, str]]:
    """Fuzzy match name to team member."""
    team = load_team()
    names = [u['name'].lower() for u in team]
    closest = difflib.get_close_matches(name.lower(), names, n=1, cutoff=0.6)
    if closest:
        return next(u for u in team if u['name'].lower() == closest[0])
    return None

class DetailChild(BaseModel):
    SEL: str = "Y"
    LOGIN: str
    PARTICIPANTS: str

class Details(BaseModel):
    CHILD: List[DetailChild]

class DocumentInfo(BaseModel):
    VALUE: str
    BASE64: str

class DocumentItem(BaseModel):
    DOCUMENT: DocumentInfo
    DOCUMENT_NAME: str

class Documents(BaseModel):
    CHILD: List[DocumentItem]

class CreateTaskRequest(BaseModel):
    SID: str = "604"
    ASSIGNEE: str
    DESCRIPTION: str
    EXPECTED_END_DATE: str  # ISO format
    TASK_NAME: str
    DETAILS: Details
    DOCUMENTS: Documents
    
    # Corrected default values based on docs; make dynamic if possible
    MANUAL_DIARY_NUMBER: str = ""  # Generate or ask if needed
    NATURE_OF_COMPLAINT: str = "1"
    NOTICE_BEFORE: str = "4"
    NOTIFICATION: str = ""
    ORIGINAL_LETTER_NUMBER: str = ""
    REFERENCE_LETTER_NUMBER: str = ""
    TYPE: str = "TYPE"
    PRIORTY_TASK: str = "N"  # 'Y' for priority

class GetTasksRequest(BaseModel):
    Event: str = "106830"
    Child: List[Dict[str, Any]]

class UpdateTaskRequest(BaseModel):
    SID: str = "607"
    TASK_ID: str
    STATUS: str
    ASSIGNEE: str
    COMMENTS: str = "STATUS_UPDATE"

class GetCountRequest(BaseModel):
    Event: str = "107567"
    Child: List[Dict[str, Any]]

def get_gmail_service():
    """Initialize Gmail API service with OAuth2 credentials from environment variables."""
    try:
        token_json_str = os.getenv("TOKEN_JSON")
        if not token_json_str:
            logger.error("TOKEN_JSON environment variable not found.")
            return None
            
        token_data = json.loads(token_json_str)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        logger.error(f"Gmail service initialization failed: {str(e)}")
        return None

def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send email via Gmail API."""
    try:
        service = get_gmail_service()
        if not service:
            logger.warning("Gmail service unavailable, skipping email")
            return False
        
        message = MIMEMultipart()
        message['to'] = to_email
        message['subject'] = subject
        message.attach(MIMEText(body, 'plain'))
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        send_message = service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        
        logger.info(f"Email sent successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Email sending failed: {str(e)}")
        return False

# --- REST API HELPERS ---
async def call_appsavy_api(key: str, payload: Dict[str, Any]) -> Optional[Dict]:
    """Universal wrapper for Appsavy POST requests - 100% API dependency."""
    config = API_CONFIGS[key]
    try:
        res = requests.post(
            config["url"],
            headers=config["headers"],
            json=payload,
            timeout=15
        )
        if res.status_code == 200:
            logger.info(f"API {key} success")
            return res.json()
        logger.error(f"API {key} failed with status {res.status_code}: {res.text}")
        return {"error": res.text}
    except Exception as e:
        logger.error(f"Exception calling API {key}: {str(e)}")
        return None

async def fetch_assignees() -> List[Dict[str, str]]:
    """Fetch assignees dynamically using GET_ASSIGNEE API."""
    payload = {
        "Event": "0",
        "Child": [{"Control_Id": "106771", "AC_ID": "111057"}]
    }
    res = await call_appsavy_api("GET_ASSIGNEE", payload)
    if res and "error" not in res:
        # Assuming response format: {"data": [{"ID": "D-3514-1001", "Name": "MD-PVVNL"}, ...]}
        # Adjust parsing based on actual response structure
        return [{"name": item["Name"].lower(), "login_code": item["ID"], "participant": item["Name"]} for item in res.get("data", [])]
    return []

# Optionally, call fetch_assignees() in load_team() if dynamic fetch is preferred
# For now, keeping static with corrections

async def fetch_task_counts_api(login_code: str, assignment_type: str = "Assigned To Me") -> Optional[Dict]:
    """Retrieves aggregate counts via SID 616 with dynamic filters."""
    child = [{
        "Control_Id": "108118",
        "AC_ID": "113229",  # Keep as per doc; if invalid, replace with correct AC_ID from your environment
        "Parent": [
            {"Control_Id": "111548", "Value": "1", "Data_Form_Id": ""},
            {"Control_Id": "107566", "Value": login_code, "Data_Form_Id": ""},  # Assignee filter
            {"Control_Id": "107568", "Value": "", "Data_Form_Id": ""},  # To Date
            {"Control_Id": "107569", "Value": "", "Data_Form_Id": ""},  # From Date
            {"Control_Id": "107599", "Value": assignment_type, "Data_Form_Id": ""},  # Assignment type
            {"Control_Id": "109599", "Value": "", "Data_Form_Id": ""},  # Manual Diary
            {"Control_Id": "108512", "Value": "", "Data_Form_Id": ""}   # System Diary
        ]
    }]
    payload = {"Event": "107567", "Child": child}
    return await call_appsavy_api("GET_COUNT", payload)

async def fetch_api_tasks(login_code: str, assignment_type: str = "Assigned To Me", status_filter: str = "Open,Closed") -> Optional[Dict]:
    """Fetch task details with dynamic filters and short status value to avoid length errors."""
    # Use short status filter (<=50 chars) to fix "value cannot be greater than 50" error
    parent = [
        {"Control_Id": "106825", "Value": status_filter, "Data_Form_Id": ""},  # Status filter (shortened)
        {"Control_Id": "106824", "Value": "", "Data_Form_Id": ""},  # From Date
        {"Control_Id": "106827", "Value": login_code, "Data_Form_Id": ""},  # User/Assignee
        {"Control_Id": "106829", "Value": "", "Data_Form_Id": ""},  # To Date
        {"Control_Id": "107046", "Value": assignment_type, "Data_Form_Id": ""},  # Assignment
        {"Control_Id": "107809", "Value": "0", "Data_Form_Id": ""}   # BTN_LBL
    ]
    child = [{"Control_Id": "106831", "AC_ID": "110803", "Parent": parent}]
    payload = {"Event": "106830", "Child": child}
    return await call_appsavy_api("GET_TASKS", payload)

async def assign_new_task_tool(assignee_name: str, description: str, deadline: str, task_name: str, documents: Optional[Documents] = None) -> Dict:
    """Tool to assign new task."""
    member = get_team_member(assignee_name)
    if not member:
        return {"error": f"Assignee {assignee_name} not found. Did you mean a similar name?"}
    
    details = Details(CHILD=[DetailChild(LOGIN=member["login_code"], PARTICIPANTS=member["participant"])])
    docs = documents or Documents(CHILD=[])
    
    req = CreateTaskRequest(
        ASSIGNEE=member["login_code"],
        DESCRIPTION=description,
        EXPECTED_END_DATE=deadline,
        TASK_NAME=task_name,
        DETAILS=details,
        DOCUMENTS=docs
    )
    res = await call_appsavy_api("CREATE_TASK", req.model_dump())
    if res and "error" not in res:
        # Notify via WhatsApp/Email
        send_whatsapp_message(member["phone"], f"New task assigned: {task_name}. Deadline: {deadline}")
        send_email(member["email"], f"New Task: {task_name}", description)
    return res or {"error": "Assignment failed"}

async def update_task_status_tool(task_id: str, status: str, assignee_name: str, comments: Optional[str] = "") -> Dict:
    """Tool to update task status."""
    member = get_team_member(assignee_name)
    if not member:
        return {"error": f"Assignee {assignee_name} not found."}
    
    req = UpdateTaskRequest(
        TASK_ID=task_id,
        STATUS=status,
        ASSIGNEE=member["login_code"],
        COMMENTS=comments or "STATUS_UPDATE"
    )
    return await call_appsavy_api("UPDATE_STATUS", req.model_dump())

async def get_task_list_tool(assignee_name: Optional[str] = None, assignment_type: str = "Assigned To Me") -> Dict:
    """Tool to get task list."""
    if assignee_name:
        member = get_team_member(assignee_name)
        if not member:
            return {"error": f"Assignee {assignee_name} not found."}
        login_code = member["login_code"]
    else:
        # Default to current user; assume manager or implement
        login_code = "TM_API"  # Placeholder; adjust based on context
    
    res = await fetch_api_tasks(login_code, assignment_type, status_filter="Open,Closed,Pending")  # Short filter
    # Parse and sort by due date if needed
    return res or {"error": "Failed to fetch tasks"}

async def get_performance_report_tool(assignee_name: Optional[str] = None) -> Dict:
    """Tool to get performance report."""
    if assignee_name:
        member = get_team_member(assignee_name)
        if not member:
            return {"error": f"Assignee {assignee_name} not found."}
        login_code = member["login_code"]
        res = await fetch_task_counts_api(login_code)
    else:
        # For all; aggregate calls
        team = load_team()
        res = {}
        for member in team:
            counts = await fetch_task_counts_api(member["login_code"])
            res[member["name"]] = counts
    return res or {"error": "Failed to fetch report"}

async def assign_task_by_phone_tool(phone: str, description: str, deadline: str, task_name: str) -> Dict:
    """Tool to assign task by phone."""
    team = load_team()
    member = next((u for u in team if u["phone"] == phone or u["phone"].endswith(phone[-10:])), None)
    if not member:
        return {"error": f"No team member found with phone {phone}"}
    return await assign_new_task_tool(member["name"], description, deadline, task_name)

# Add main/agent run logic if needed; assuming this is integrated in webhook.py or elsewhere