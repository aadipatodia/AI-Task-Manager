import os
from pymongo import MongoClient
import certifi
import json
import datetime
import base64
import requests
import logging
import re
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
import asyncio
from send_message import send_registration_template

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.send']



REDIRECT_URI = os.getenv("REDIRECT_URI", "https://ai-task-manager-1-ugb8.onrender.com/oauth2callback")
MANAGER_EMAIL = "ankita.mishra@mobineers.com"

# Initialize MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where()) if MONGO_URI else None
db = client['ai_task_manager'] if client is not None else None
users_collection = db['users'] if db is not None else None
conversation_history: Dict[str, List[Any]] = {}

APPSAVY_BASE_URL = "https://configapps.appsavy.com/api/AppsavyRestService"

API_CONFIGS = {
    "ADD_DELETE_USER":{
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient",
        "headers": {
            "sid": "629",
            "pid": "309",
            "fid": "13580",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "799f57e5-af33-4341-9c0f-4c0f42ac9f79"
        
        }
    },
      
    "CREATE_TASK": {
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient",
        "headers": {
            "sid": "604",
            "pid": "309",
            "fid": "10344",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "17bce718-18fb-43c4-90bb-910b19ffb34b"
        }
    },
    "GET_ASSIGNEE": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient",
        "headers": {
            "sid": "606",
            "pid": "309",
            "fid": "10344",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "d23e5874-ba53-4490-941f-0c70b25f6f56"
        }
    },
    "GET_TASKS": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient",
        "headers": {
            "sid": "610",
            "pid": "309",
            "fid": "10349",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "e5b4e098-f8b9-47bf-83f1-751582bfe147"
        }
    },
    # Updated API_CONFIGS entry for UPDATE_STATUS

    "UPDATE_STATUS": {
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient", # [cite: 1]
        "headers": {
            "sid": "607",        # Session ID [cite: 2, 8]
            "pid": "309",        # Project ID [cite: 3]
            "fid": "10345",      # Feature ID [cite: 4]
            "cid": "64",         # Client ID [cite: 4]
            "uid": "TM_API",     # User ID [cite: 5]
            "roleid": "1627",    # Role ID [cite: 6]
            "TokenKey": "7bf28d4d-c14f-483d-872a-78c9c16bd982" # [cite: 6]
        }
    },

    "GET_COUNT": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient",
        "headers": {
            "sid": "616",
            "pid": "309",
            "fid": "10408",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "75c6ec2e-9f9c-48fa-be24-d8eb612f4c03"
        }
    },
    "GET_USERS_BY_ID": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient",
        "headers": {
            "sid": "609",
            "pid": "309",
            "fid": "10344",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "d23e5874-ba53-4490-941f-0c70b25f6f56"
        }
    },
    "WHATSAPP_PDF_REPORT": {
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient",
        "headers": {
            "sid": "627",
            "pid": "309",
            "fid": "13574",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "dea16c4c-bf19-423f-a567-c2c265c7dd22"
        }
    }
}

ai_model = GeminiModel('gemini-2.0-flash-exp')

class ManagerContext(BaseModel):
    sender_phone: str
    role: str
    current_time: datetime.datetime = Field(default_factory=datetime.datetime.now)
    document_data: Optional[Dict] = None
    
class WhatsAppPdfReportRequest(BaseModel):
    SID: str = "627"
    ASSIGNED_TO: str
    REPORT_TYPE: str  # Count / Detail
    STATUS: str
    MOBILE_NUMBER: str
    FROM_DATE: str = ""
    TO_DATE: str = ""
    ASSIGNED_BY: str = ""
    REFERENCE: str = ""


def get_system_prompt(current_time: datetime.datetime) -> str:
    team = load_team()
    team_description = "\n".join([f"- {u['name']} (Login: {u['login_code']})" for u in team])
    current_date_str = current_time.strftime("%Y-%m-%d")
    current_time_str = current_time.strftime("%I:%M %p")
    day_of_week = current_time.strftime("%A")
    
    return f"""
### AUTHORIZED TEAM MEMBERS:
{team_description}

You are the Official AI Task Manager Bot for the organization.
Identity: TM_API (Manager).
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
* **Name Resolution**: Map names to login IDs from team directory

### TASK STATUS RULES (API SID 607):
You must determine the correct 'new_status' string by interpreting the user's intent and role within the conversation context. Do not look for specific keywords; understand the "state" the user is describing.


### USER MANAGEMENT RULES (ADD / DELETE USERS):

- Any authorized user can ADD a new user.
- A user can DELETE a user ONLY IF:
  - The same user originally added that user.

- Deletion is ownership-based, NOT role-based.
- Managers do NOT have special override permissions for deleting users.

### DELETION OWNERSHIP ENFORCEMENT:
- Before deleting a user, always verify ownership.
- Ownership means: the requester is the same user who added the target user.
- If the requester did NOT add the user:
  - Deny the request.
  - Respond with:
    "Permission Denied: Only the user who added this account can delete it."
- Do NOT call the delete user API if ownership does not match.
- If ownership information is missing or unclear, ask for clarification instead of deleting.

### TOOL USAGE CONSTRAINTS:
- Use 'delete_user_tool' ONLY after confirming ownership.
- Ownership means: requester mobile number == creator mobile number.
- Never assume ownership.
- If ownership information is unavailable, ask for clarification instead of deleting.

This is the completed and corrected **TASK STATUS RULES** section for your system prompt. It is designed to ensure I (as the AI) act as a smart interpreter between natural conversational language and your specific API status requirements.

---

### ### TASK STATUS RULES (API SID 607)

You must determine the correct `new_status` string by first identifying the **User Role** (Manager or Employee) and then interpreting the **Intent** of their message. Do not look for specific keywords; understand the state the user is describing.
DO NOT ask the user if they are a manager or employee. Use the following logic to determine the role and status automatically:
Identify Role by Task ID:
- If the user is the Assignee of the requested Task ID, they are acting as the Employee.
- If the user was the Creator/Reporter of the requested Task ID, they are acting as the Manager.
**Managers:** Authorized to provide final approval or reject work.
**Employees:** Authorized to update progress or submit work for review.

MAP INTENT TO SYSTEM STATUS
Employee Intents (The Assignees)
Status: Open
Intent: The user acknowledges they have seen the task or added it to their queue.
Examples: "Acknowledged," "I see it," "Got the task."

Status: Work In Progress
Intent: The user indicates they have started the action, the task is currently "pending," or they are in the middle of the process.
Examples: "I'm starting this," "Still working on it," "Task <task_id> is pending," "I've done the first part."

Status: Close
Intent: The user indicates they have finished their portion of the work and are submitting it for the manager's review.
Examples: "Task 101 closed," "Task 102 completed," "Here is the final file."

**Manager Intents (The Approvers)**

Status: Closed
Intent: The manager expresses final satisfaction, gives formal approval, or marks the task as officially finished.
Examples: "Approved," "Task 102 is finished," "Great job, close this," "Task 102 is finally done."

Status: Reopened
Intent: The manager expresses dissatisfaction, rejects the work, or indicates more work is required on a task the employee previously tried to "Close".
Examples: "Redo this," "Task 101 is rejected," "Need more details," "Reopen task 101."

**CRITICAL LOGIC:**
**Role-Based Mapping:** If an employee says "closed," you must map it to `Close` (submission). If a manager says "close," you must map it to `Closed` (finality).
**Natural Language Interpretation:** Understand that "completed" and "finished" by an employee always mean they are submitting work for approval, not ending the lifecycle of the task.
**Remark Extraction:** Always extract the conversational part of the message (e.g., "I found the bug") and pass it into the `COMMENTS` field for the API.
**Permission Enforcement:** Never allow an Employee to use the status `Closed` or `Reopen`.
Never allow a Manager to use the status `Work In Progress` or `Close`.

**DOCUMENT HANDLING:**
**Case 1 (Manager):** If a document/image is sent while creating a task, use `assign_new_task_tool`. 
**Case 2 (Employee):** If a document/image is sent with a "completed" or "closed" message, use `update_task_status_tool` with status `Close` .
**Case 3 (Update):** If a document is sent during work, use `update_task_status_tool` with status `Work In Progress`.

### PERFORMANCE REPORTING:
When user asks for performance, statistics, or counts (or chooses Performance Report) or says "show pending tasks for ...":
- Use 'get_performance_report_tool'
- Without name → Report for ALL employees (Managers only)
- With name → Report for specific employee

### TASK LISTING:
When user asks to see tasks, list tasks, pending work:
- Use 'get_task_list_tool'
- Without name → Show tasks for the requesting user
- With name (managers only) → Show tasks for specified employee
- Show the tasks exactly as returned by the API without applying additional sorting
- IMPORTANT:
When responding with task lists, return the tool output EXACTLY as-is.
Do not summarize, rephrase, or omit any fields.

### TASK ASSIGNMENT BY PHONE:
Support assignment using phone numbers:
- Extract 10-digit number or full format
- Use 'assign_task_by_phone_tool'

### USER LOOKUP:
When asked about users in a group or specific user details:
- Use 'get_users_by_id_tool' with group ID or user ID
- Group IDs start with 'G-' (e.g., G-10343-41)
- User IDs start with 'D-' (e.g., D-3514-1001)

### ASSIGNEE LOOKUP:
When needing to list all available assignees:
- Use 'get_assignee_list_tool'
- Returns all users who can be assigned tasks

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

### WHATSAPP PDF REPORTS:
When user asks to send, share, or receive a report on WhatsApp:
- Use 'send_whatsapp_report_tool'
- REPORT_TYPE: "Count" or "Detail"
- STATUS examples: Open, Closed, Reported Closed
- If no assignee specified, send report for requesting user

### IMPORTANT:
- Ignore WhatsApp headers like '[7:03 pm, 13/1/2026] ABC:' and focus only on the text after the colon.
"""

def load_team():
    """Ab ye function 100% dynamic hai, sirf MongoDB se users fetch karega."""
    if users_collection is None:
        logger.error("MongoDB connection cant be initialized")
        return []

    try:
        # Database se saare users fetch karein
        # {"_id": 0} se MongoDB ki default ID hat jati hai
        db_users = list(users_collection.find({}, {"_id": 0}))
        
        logger.info(f"Successfully loaded {len(db_users)} users from MongoDB.")
        return db_users
        
    except Exception as e:
        logger.error(f"Failed to fetch users from MongoDB: {e}")
        return []

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
    EXPECTED_END_DATE: str
    TASK_NAME: str
    MOBILE_NUMBER: str              
    TASK_SOURCE: str = "Whatsapp"   
    REFERENCE: str = "WHATSAPP_TASK" 
    MANUAL_DIARY_NUMBER: str = "121"
    NATURE_OF_COMPLAINT: str = "1"
    NOTICE_BEFORE: str = "4"
    NOTIFICATION: str = ""
    ORIGINAL_LETTER_NUMBER: str = "22"
    PRIORTY_TASK: str = "N"
    REFERENCE_LETTER_NUMBER: str = "001"
    TYPE: str = "Days"
    DETAILS: Details = Details(CHILD=[])
    DOCUMENTS: Documents = Documents(CHILD=[])


class GetTasksRequest(BaseModel):
    Event: str = "106830"
    Child: List[Dict]

class UpdateTaskRequest(BaseModel):
    SID: str = "607"
    TASK_ID: str
    STATUS: str
    COMMENTS: str = "STATUS_UPDATE"
    UPLOAD_DOCUMENT: str = ""
    BASE64: str = ""

class GetCountRequest(BaseModel):
    Event: str = "107567"
    Child: List[Dict]

class GetAssigneeRequest(BaseModel):
    Event: str = "0"
    Child: List[Dict]

class GetUsersByIdRequest(BaseModel):
    Event: str = "107018"
    Child: List[Dict]

class AddDeleteUserRequest(BaseModel):
    SID: str = "629"
    ACTION: str            # "Add" or "Delete"
    CREATOR_MOBILE_NUMBER: str
    EMAIL: str
    MOBILE_NUMBER: str
    NAME: str

async def add_user_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    email: str,
    mobile: str
) -> str:
    # 1. Attempt to add the user to Appsavy
    req = AddDeleteUserRequest(
        ACTION="Add",
        CREATOR_MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
        NAME=name,
        EMAIL=email,
        MOBILE_NUMBER=mobile[-10:]
    )

    res = await call_appsavy_api("ADD_DELETE_USER", req)
    if not isinstance(res, dict): return f"Failed to add user: {res}"
    
    msg = res.get("resultmessage", "")
    login_code = None
    status_note = ""

    # Check for Success (1) or Already Exists
    is_success = str(res.get("result")) == "1" or str(res.get("RESULT")) == "1"
    is_existing = "already exists" in msg.lower()

    if is_success or is_existing:
        # STEP 1: Try to extract Login ID from the message text (Regex)
        match = re.search(r"login Code:\s*([A-Z0-9-]+)", msg, re.IGNORECASE)
        login_code = match.group(1) if match else None
        
        if login_code:
            status_note = "ID extracted from API message"
        
        # STEP 2: BACKUP - If ID is missing from the message, ALWAYS check the list
        if not login_code:
            logger.info(f"ID missing from message. Fetching list to find: '{name}'")
            assignee_res = await call_appsavy_api("GET_ASSIGNEE", GetAssigneeRequest(Event="0", Child=[{"Control_Id": "106771", "AC_ID": "111057"}]))
            
            result_list = []
            if isinstance(assignee_res, dict):
                result_list = assignee_res.get("data", {}).get("Result", [])
            elif isinstance(assignee_res, list):
                result_list = assignee_res

            if result_list:
                target_name = name.lower().strip()
                for item in result_list:
                    item_name = str(item.get("NAME", "")).lower().strip()
                    if target_name == item_name:
                        login_code = item.get("ID") or item.get("LOGIN_ID")
                        status_note = "ID fetched from system list"
                        break

        # STEP 3: If we have an ID, save to MongoDB
        if login_code:
            new_user = {
                "name": name.lower().strip(),
                "phone": "91" + mobile[-10:],
                "email": email,
                "login_code": login_code
            }
            
            if users_collection is not None:
                users_collection.update_one(
                    {"phone": new_user["phone"]},
                    {"$set": new_user},
                    upsert=True
                )
                logger.info(f"Successfully synced {name} to MongoDB with ID {login_code}")
                
                type_str = "Created" if is_success else "Synced"
                return (f" Success: {type_str}!\n\n"
                        f"Name: {name}\n"
                        f"Login ID: {login_code}\n"
                        f"Source: {status_note}")

    return f"Failed: I could not find a Login ID for '{name}' in the message or the system list. Please check if the name matches exactly."
async def delete_user_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    email: str,
    mobile: str
) -> str:
    req = AddDeleteUserRequest(
        ACTION="Delete",
        CREATOR_MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
        NAME=name,
        EMAIL=email,
        MOBILE_NUMBER=mobile[-10:]
    )

    res = await call_appsavy_api("ADD_DELETE_USER", req)

    if not isinstance(res, dict):
        return f"Failed to delete user: {res}"

    msg = res.get("resultmessage", "").lower()

    if "permission denied" in msg:
        return " Permission denied. You did not add this user."

    if str(res.get("result")) == "1" or str(res.get("RESULT")) == "1":
        
        # --- MongoDB se bhi hatane ka logic ---
        if users_collection is not None:
            # Phone number ke base par document delete karein
            users_collection.delete_one({"phone": "91" + mobile[-10:]})
            logger.info(f"User with mobile {mobile[-10:]} removed from MongoDB.")

        return "User deleted successfully from system and database."
    
    return f"Failed to delete user: {res.get('resultmessage')}"


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

def build_status_filter(role: str) -> str:
    if role == "manager":
        return "Open,Closed,Reopened"
    else:
        return "Open,Partially Closed,Reported Closed"

def normalize_status_for_report(status: str) -> str:
    report_status_map = {
        "open": "Open",
        "pending": "Open",

        "partial": "Partially Closed",
        "in progress": "Partially Closed",

        "reported": "Reported Closed",

        # user usually means final completion
        "completed": "Closed",
        "done": "Closed",
        "closed": "Closed"
    }

    return report_status_map.get(status.lower(), status)

def to_appsavy_datetime(iso_dt: str) -> str:
    dt = datetime.datetime.fromisoformat(iso_dt)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

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

def normalize_tasks_response(tasks_data):
    """Normalize Appsavy GET_TASKS response to always return a list"""
    if not isinstance(tasks_data, dict):
        return []

    data = tasks_data.get("data")

    if not isinstance(data, dict):
        return []

    return data.get("Result", [])

def normalize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize Appsavy task object to internal standard keys"""
    return {
        "task_id": task.get("TID"),
        "task_name": task.get("COMMENTS"),
        "assigned_by": task.get("REPORTER"),
        "assign_date": task.get("ASSIGN_DATE"),
        "status": task.get("STS"),
        "task_type": task.get("TASK_TYPE")
    }

async def call_appsavy_api(key: str, payload: BaseModel) -> Optional[Dict]:
    """Universal wrapper for Appsavy POST requests - 100% API dependency."""
    config = API_CONFIGS[key]
    try:
        logger.info(f"Calling API {key} with payload: {payload.model_dump()}")
        
        res = await asyncio.to_thread(
            requests.post,
            config["url"],
            headers=config["headers"],
            json=payload.model_dump(),
            timeout=15
        )
        
        logger.info(f"API {key} response status: {res.status_code}")
        logger.info(f"API {key} response body: {res.text}")
        
        if res.status_code == 200:
            try:
                return res.json()
            except json.JSONDecodeError:
                logger.error(f"API {key} returned non-JSON response: {res.text}")
                return {"error": "Invalid JSON response"}
        else:
            logger.error(f"API {key} failed with status {res.status_code}: {res.text}")
            return {"error": res.text}
    except Exception as e:
        logger.error(f"Exception calling API {key}: {str(e)}")
        return None

async def fetch_task_counts_api(login_code: str, ctx_role: str):

    req = GetCountRequest(Child=[{
        "Control_Id": "108118",
        "AC_ID": "113229", # Updated from YAML source [cite: 13]
        "Parent": [
            {"Control_Id": "111548", "Value": "1", "Data_Form_Id": ""},
            {"Control_Id": "107566", "Value": login_code, "Data_Form_Id": ""},
            {"Control_Id": "107568", "Value": "", "Data_Form_Id": ""},
            {"Control_Id": "107569", "Value": "", "Data_Form_Id": ""},
            {"Control_Id": "107599", "Value": "Assigned To Me", "Data_Form_Id": ""},
            {"Control_Id": "109599", "Value": "", "Data_Form_Id": ""},
            {"Control_Id": "108512", "Value": "", "Data_Form_Id": ""}
        ]
    }])
    
    try:
        res = await call_appsavy_api("GET_COUNT", req)
        logger.info(f"API Count Response for {login_code}: {res}")
        
        if not res:
            logger.warning(f"GET_COUNT returned None for {login_code}")
            return {"ASSIGNED_TASK": "0", "CLOSED_TASK": "0"}
        
        if isinstance(res, dict) and "error" in res:
            logger.error(f"GET_COUNT API error for {login_code}: {res['error']}")
            return {"ASSIGNED_TASK": "0", "CLOSED_TASK": "0"}
        
        if isinstance(res, list) and len(res) > 0:
            logger.info(f"GET_COUNT returned list with {len(res)} items for {login_code}")
            return res[0]
        elif isinstance(res, dict):
            logger.info(f"GET_COUNT returned dict for {login_code}")
            return res
        else:
            logger.warning(f"GET_COUNT returned unexpected format for {login_code}: {type(res)}")
            return {"ASSIGNED_TASK": "0", "CLOSED_TASK": "0"}
            
    except Exception as e:
        logger.error(f"fetch_task_counts_api error for {login_code}: {str(e)}", exc_info=True)
        return {"ASSIGNED_TASK": "0", "CLOSED_TASK": "0"}

def download_and_encode_document(document_data: Dict):
    """Downloads media from Meta and returns base64 string."""
    try:
        access_token = os.getenv("ACCESS_TOKEN")
        media_id = document_data.get("id")
        
        headers = {"Authorization": f"Bearer {access_token}"}
        r = requests.get(f"https://graph.facebook.com/v20.0/{media_id}/", headers=headers)
        
        if r.status_code != 200:
            logger.error("Failed to get media URL")
            return None
        
        download_url = r.json().get("url")
        dr = requests.get(download_url, headers=headers)
        
        if dr.status_code == 200:
            return base64.b64encode(dr.content).decode("utf-8")
        
        return None
    except Exception as e:
        logger.error(f"Document download failed: {str(e)}")
        return None

# --- NEW TOOLS ---

async def send_whatsapp_report_tool(
    ctx: RunContext[ManagerContext],
    report_type: str,
    status: str,
    assigned_to: Optional[str] = None
) -> str:
    """
    Sends WhatsApp PDF report using SID 627.
    """
    try:
        team = load_team()

        # Resolve user
        if assigned_to:
            user = next(
                (u for u in team if assigned_to.lower() in u["name"].lower()
                 or assigned_to == u["login_code"]),
                None
            )
            if not user:
                return f"User '{assigned_to}' not found."
        else:
            user = next((u for u in team if u["phone"] == ctx.deps.sender_phone), None)

        if not user:
            return "Unable to resolve user for report."

        req = WhatsAppPdfReportRequest(
            ASSIGNED_TO=user["login_code"],
            REPORT_TYPE=report_type,
            STATUS=normalize_status_for_report(status),
            MOBILE_NUMBER=user["phone"][-10:],
            ASSIGNED_BY="Assigned By Me",
            REFERENCE="WHATSAPP"
        )


        api_response = await call_appsavy_api("WHATSAPP_PDF_REPORT", req)

        if not api_response:
            return "Failed to generate WhatsApp report."

        if isinstance(api_response, dict) and api_response.get("error"):
            return f"API Error: {api_response['error']}"

        return (
            f"WhatsApp PDF report sent successfully.\n"
            f"Report Type: {report_type}\n"
            f"Status: {status}"
        )

    except Exception as e:
        logger.error("send_whatsapp_report_tool error", exc_info=True)
        return f"Error sending WhatsApp report: {str(e)}"


async def get_assignee_list_tool(ctx: RunContext[ManagerContext]) -> str:
    """
    Retrieves list of all assignees/users available in the system using SID 606.
    Returns formatted list with Login IDs and Names.
    """
    try:
        req = GetAssigneeRequest(
            Event="0",
            Child=[{
                "Control_Id": "106771",
                "AC_ID": "111057"
            }]
        )
        
        api_response = await call_appsavy_api("GET_ASSIGNEE", req)
        
        if not api_response:
            return "Error: Unable to fetch assignee list from API."
        
        if isinstance(api_response, dict) and "error" in api_response:
            return f"API Error: {api_response['error']}"
        
        assignees = []
        if isinstance(api_response, list):
            for item in api_response:
                if isinstance(item, dict):
                    login_id = item.get("LOGIN_ID") or item.get("ID")
                    name = item.get("name") or item.get("PARTICIPANT_NAME")
                    if login_id and name:
                        assignees.append(f"{name} (ID: {login_id})")
        
        if not assignees:
            return "No assignees found in the system."
        
        return "Available Assignees:\n" + "\n".join(assignees)
        
    except Exception as e:
        logger.error(f"get_assignee_list_tool error: {str(e)}", exc_info=True)
        return f"Error fetching assignee list: {str(e)}"

async def get_users_by_id_tool(ctx: RunContext[ManagerContext], id_value: str) -> str:
    """
    Retrieves user information by Group ID (G-XXXX-XX) or User ID (D-XXXX-XXXX).
    
    Args:
        id_value: Group ID starting with 'G-' or User ID starting with 'D-'
    
    Returns:
        Formatted user information
    """
    try:
        if not (id_value.startswith('G-') or id_value.startswith('D-')):
            return "Error: ID must start with 'G-' (Group) or 'D-' (User). Example: G-10343-41 or D-3514-1001"
        
        req = GetUsersByIdRequest(
            Event="107018",
            Child=[{
                "Control_Id": "107019",
                "AC_ID": "111271",
                "Parent": [{
                    "Control_Id": "106771",
                    "Value": id_value,
                    "Data_Form_Id": ""
                }]
            }]
        )
        
        api_response = await call_appsavy_api("GET_USERS_BY_ID", req)
        
        if not api_response:
            return f"Error: Unable to fetch information for ID '{id_value}'."
        
        if isinstance(api_response, dict) and "error" in api_response:
            return f"API Error: {api_response['error']}"
        
        users = []
        if isinstance(api_response, list):
            for item in api_response:
                if isinstance(item, dict):
                    user_id = item.get("USER_ID") or item.get("LOGIN_ID") or item.get("ID")
                    name = item.get("name") or item.get("USER_NAME")
                    email = item.get("email")
                    phone = item.get("phone") or item.get("MOBILE")
                    
                    user_info = f"Name: {name}"
                    if user_id:
                        user_info += f"\nUser ID: {user_id}"
                    if email:
                        user_info += f"\nEmail: {email}"
                    if phone:
                        user_info += f"\nPhone: {phone}"
                    
                    users.append(user_info)
        elif isinstance(api_response, dict):
            user_id = api_response.get("USER_ID") or api_response.get("LOGIN_ID")
            name = api_response.get("name") or api_response.get("USER_NAME")
            email = api_response.get("email")
            phone = api_response.get("phone") or api_response.get("MOBILE")
            
            user_info = f"Name: {name}"
            if user_id:
                user_info += f"\nUser ID: {user_id}"
            if email:
                user_info += f"\nEmail: {email}"
            if phone:
                user_info += f"\nPhone: {phone}"
            
            users.append(user_info)
        
        if not users:
            return f"No users found for ID '{id_value}'."
        
        result = f"User Information for {id_value}:\n\n"
        result += "\n\n".join(users)
        return result
        
    except Exception as e:
        logger.error(f"get_users_by_id_tool error: {str(e)}", exc_info=True)
        return f"Error fetching user information: {str(e)}"

async def get_performance_report_tool(
    ctx: RunContext[ManagerContext],
    name: Optional[str] = None
) -> str:
    """
    Generate performance report using API data
    - SID 616 for counts
    - SID 610 for task details (PER USER)
    """
    try:
        team = load_team()
        now = ctx.deps.current_time

        # Role check
        if not name and ctx.deps.role != "manager":
            return "Permission Denied: Only managers can view the full team report."

        # Decide whose report to show
        if name:
            matched = next(
                (
                    u for u in team
                    if name.lower() in u["name"].lower()
                    or name.lower() == u["login_code"].lower()
                ),
                None
            )
            if not matched:
                return f"User '{name}' not found in directory."
            display_team = [matched]

        elif ctx.deps.role == "manager":
            display_team = team

        else:
            self_user = next(
                (u for u in team if u["phone"] == ctx.deps.sender_phone),
                None
            )
            if not self_user:
                return "Unable to identify your profile."
            display_team = [self_user]

        # 🔹 Status filter
        status_filter = build_status_filter(ctx.deps.role)

        results = []

        
        # FETCH DATA PER USER (THIS FIXES THE BUG)
      
        for member in display_team:
            member_login = member["login_code"]

            try:
                # 🔹 Fetch task list for THIS USER ONLY (SID 610)
                raw_tasks_data = await call_appsavy_api(
                    "GET_TASKS",
                    GetTasksRequest(
                        Child=[{
                            "Control_Id": "106831",
                            "AC_ID": "110803",
                            "Parent": [
                                {"Control_Id": "106825", "Value": status_filter, "Data_Form_Id": ""},
                                {"Control_Id": "106824", "Value": "", "Data_Form_Id": ""},
                                {"Control_Id": "106827", "Value": member_login, "Data_Form_Id": ""},
                                {"Control_Id": "106829", "Value": "", "Data_Form_Id": ""},
                                {"Control_Id": "107046", "Value": "", "Data_Form_Id": ""},
                                {"Control_Id": "107809", "Value": "0", "Data_Form_Id": ""}
                            ]
                        }]
                    )
                )

                member_tasks = normalize_tasks_response(raw_tasks_data)

                # 🔹 Fetch counts (SID 616)
                counts = await fetch_task_counts_api(member_login, ctx.deps.role)

                within_time = 0
                beyond_time = 0
                closed_count = 0

                # 🔹 Pending / completed logic
                for task in member_tasks:
                    status = str(task.get("STS", "")).lower()
                    expected_date = task.get("EXPECTED_END_DATE")

                    if status == "closed":
                        closed_count += 1
                        continue

                    if expected_date:
                        try:
                            expected = datetime.datetime.strptime(
                                expected_date,
                                "%m/%d/%Y %I:%M:%S %p"
                            )
                            if expected >= now:
                                within_time += 1
                            else:
                                beyond_time += 1
                        except Exception:
                            # fallback: treat as within time
                            within_time += 1

                assigned_count = counts.get(
                    "ASSIGNED_TASK",
                    str(len(member_tasks))
                )

                closed_from_api = counts.get(
                    "CLOSED_TASK",
                    str(closed_count)
                )

                results.append(
                    f"Tasks Report for User: {member['name'].title()}\n"
                    f"Assigned Tasks- {assigned_count} Nos\n"
                    f"Completed Tasks- {closed_from_api} Nos\n"
                    f"Pending Tasks-\n"
                    f"Within time: {within_time}\n"
                    f"Beyond time: {beyond_time}"
                )

            except Exception:
                logger.error(
                    f"Error processing report for {member['name']}",
                    exc_info=True
                )
                results.append(
                    f"Name- {member['name'].title()}\n"
                    f"Error: Unable to fetch report data"
                )

        if not results:
            return "No team members found for reporting."

        return "\n\n".join(results)

    except Exception as e:
        logger.error("get_performance_report_tool error", exc_info=True)
        return f"Error generating performance report: {str(e)}"

async def get_task_list_tool(ctx: RunContext[ManagerContext]) -> str:
    try:
        team = load_team()
        user = next((u for u in team if u["phone"] == ctx.deps.sender_phone), None)

        if not user:
            return "Unable to identify your profile."

        login_code = user["login_code"]

        raw_tasks_data = await call_appsavy_api(
            "GET_TASKS",
            GetTasksRequest(
                Event="106830",
                Child=[{
                    "Control_Id": "106831",
                    "AC_ID": "110803",
                    "Parent": [
                        {"Control_Id": "106825", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "106824", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "106827", "Value": login_code, "Data_Form_Id": ""},
                        {"Control_Id": "106829", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "107046", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "107809", "Value": "", "Data_Form_Id": ""}
                    ]
                }]
            )
        )

        tasks = normalize_tasks_response(raw_tasks_data)

        if not tasks:
            return "No tasks assigned to you."

        output = ""

        for task in tasks:
            deadline_raw = task.get("EXPECTED_END_DATE")
            deadline = ""

            if deadline_raw:
                try:
                    deadline = datetime.datetime.strptime(
                        deadline_raw, "%m/%d/%Y %I:%M:%S %p"
                    ).strftime("%d-%b-%Y %I:%M %p")
                except Exception:
                    deadline = deadline_raw

            output += (
                f"ID: {task.get('TID')}\n"
                f"Task: {task.get('COMMENTS')}\n"
                f"Assigned On: {task.get('ASSIGN_DATE')}\n"
                f"Deadline: {deadline}\n"
                f"Status: {task.get('STS')}\n\n"
            )

        return output.strip()
    except Exception as e:
        logger.error(f"get_task_list_tool error: {str(e)}", exc_info=True)
        return "Error fetching your tasks."

def extract_multiple_assignees(text: str, team: list) -> list[str]:
    text = text.lower()
    found = []
    for member in team:
        if member["name"].lower() in text:
            found.append(member["name"])
    return list(set(found))

async def get_task_description(task_id: str) -> str:
    """
    Fetch task description using GET_TASKS.
    Returns description or 'N/A' if not found.
    """
    try:
        res = await call_appsavy_api(
            "GET_TASKS",
            GetTasksRequest(
                Event="106830",
                Child=[{
                    "Control_Id": "106831",
                    "AC_ID": "110803",
                    "Parent": [
                        {"Control_Id": "106825", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "106824", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "106827", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "106829", "Value": task_id, "Data_Form_Id": ""},
                        {"Control_Id": "107046", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "107809", "Value": "0", "Data_Form_Id": ""}
                    ]
                }]
            )
        )

        tasks = normalize_tasks_response(res)
        if tasks:
            return tasks[0].get("COMMENTS", "N/A")

    except Exception as e:
        logger.error(f"Failed to fetch task description for {task_id}: {e}")

    return "N/A"

async def assign_new_task_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    task_name: str,
    deadline: str
) -> str:
    try:
        # 1. First, check MongoDB (Fast)
        team = load_team()
        matches = [u for u in team if name.lower() in u["name"].lower()]

        # 2. FALLBACK: If not in MongoDB, check Appsavy Database (SID 606)
        if not matches:
            logger.info(f"'{name}' not in MongoDB. Checking Appsavy DB...")
            # Reuse your existing logic for fetching the full list from Appsavy
            assignee_res = await call_appsavy_api("GET_ASSIGNEE", GetAssigneeRequest(Event="0", Child=[{"Control_Id": "106771", "AC_ID": "111057"}]))
            
            appsavy_users = assignee_res.get("data", {}).get("Result", []) if isinstance(assignee_res, dict) else []
            
            matches = [
                {"name": u["NAME"], "login_code": u["ID"], "phone": u.get("MOBILE", "N/A")} 
                for u in appsavy_users 
                if name.lower() in u["NAME"].lower()
            ]

        # 3. Handle matches as before
        if not matches:
            return f"Error: '{name}' was not found in MongoDB or Appsavy."
            
        if len(matches) > 1:
            options = "\n".join([f"- {u['name']} (Phone: {u['phone']})" for u in matches])
            return (
                f"I found multiple users named '{name}'. Who should I assign this to?\n\n"
                f"{options}\n\n"
                "Please provide the specific phone number or full name."
            )

        # Single Match Found - Proceed
        user = matches[0]
        login_code = user["login_code"]

        # 2. Handle Document Attachment (Case 1: Manager sends doc with task)
        documents_child = []
        if ctx.deps.document_data:
            media_type = ctx.deps.document_data.get("type")
            media_info = ctx.deps.document_data.get(media_type)
            
            if media_info:
                logger.info(f"Downloading attachment for new task: {media_type}")
                base64_data = download_and_encode_document(media_info)
                
                if base64_data:
                    fname = media_info.get("filename") or (
                        f"task_image_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png" 
                        if media_type == "image" else "task_document.pdf"
                    )
                    
                    documents_child.append(DocumentItem(
                        DOCUMENT=DocumentInfo(VALUE=fname, BASE64=base64_data),
                        DOCUMENT_NAME=fname
                    ))

        # 3. Prepare the CreateTaskRequest (SID 604)
        req = CreateTaskRequest(
            ASSIGNEE=login_code,
            DESCRIPTION=task_name,
            TASK_NAME=task_name,
            EXPECTED_END_DATE=to_appsavy_datetime(deadline),
            MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
            DETAILS=Details(
                CHILD=[DetailChild(
                    SEL="Y",
                    LOGIN=login_code,
                    PARTICIPANTS=user["name"].upper()
                )]
            ),
            DOCUMENTS=Documents(CHILD=documents_child)
        )
        
        # 4. Execute API Call
        api_response = await call_appsavy_api("CREATE_TASK", req)
        
        if not api_response:
            return "API failure: No response from server during task creation."
        
        if isinstance(api_response, dict):
            if api_response.get('error'):
                return f"API failure: {api_response.get('error')}"
            
            # Check for success (RESULT 1)
            if str(api_response.get('result')) == "1" or str(api_response.get('RESULT')) == "1":
                # --- Send Notifications ---
                phone_id = os.getenv("PHONE_NUMBER_ID")
                whatsapp_msg = f"New Task Assigned:\n\nTask: {task_name}\nDue Date: {deadline}\n\nPlease complete on time."

                if phone_id:
                    # STEP A: Send Registration/Utility Template to re-open 24h window
                    send_registration_template(
                        recipient_number=user["phone"],
                        user_identifier=user["name"].title(),
                        phone_number_id=phone_id
                    )
                    
                    # STEP B: Brief delay to ensure Meta registers the new session
                    await asyncio.sleep(1.5)
                    
                    # STEP C: Send free-form Task Details
                    send_whatsapp_message(user["phone"], whatsapp_msg, phone_id)

                # Send Emails
                email_subject = f"New Task Assigned: {task_name}"
                send_email(user["email"], email_subject, whatsapp_msg)
                send_email(MANAGER_EMAIL, f"Task Confirmed: {task_name}", f"Assigned to {user['name']}.")

                return f"Task successfully assigned to {user['name'].title()} (ID: {login_code})."

        return f"API Error: {api_response.get('resultmessage', 'Unexpected response format')}"
        
    except Exception as e:
        logger.error(f"assign_new_task_tool error: {str(e)}", exc_info=True)
        return f"System Error: Unable to assign task ({str(e)})"

async def assign_task_by_phone_tool(
    ctx: RunContext[ManagerContext],
    phone: str,
    task_name: str,
    deadline: str
) -> str:
    """
    Assigns task using phone number instead of name.
    Supports 10-digit and full formats.
    """
    try:
        team = load_team()
        
        if len(phone) == 10 and not phone.startswith('91'):
            phone = f"91{phone}"
        
        user = next((u for u in team if u['phone'] == phone), None)
        if not user:
            return f"Error: No employee found with phone number {phone}."
        
        return await assign_new_task_tool(ctx, user['name'], task_name, deadline)
        
    except Exception as e:
        logger.error(f"assign_task_by_phone_tool error: {str(e)}", exc_info=True)
        return f"Error assigning task by phone: {str(e)}"


EMPLOYEE_ALLOWED_STATUSES = {
    "open": "Open",
    "work in progress": "Work In Progress",
    "wip": "Work In Progress",
    "in progress": "Work In Progress",

    # submission for approval
    "close": "Close",
    "done": "Close",
    "completed": "Close",
    "submit": "Close"
}

MANAGER_ALLOWED_STATUSES = {
    # final approval
    "close":"Closed",
    "closed": "Closed",
    "final close": "Closed",
    "approve": "Closed",
    "approved": "Closed",

    # rejection
    "reopen": "Reopened",
    "reopened": "Reopened",
    "reject": "Reopened"
}

async def update_task_status_tool(
    ctx: RunContext[ManagerContext], 
    task_id: str, 
    status: str, 
    remark: Optional[str] = None
) -> str:
    """
    Updates task status. Gemini maps conversational intent to:
    'Open', 'Work In Progress', 'Close', 'Reopen', 'Closed'.
    """

    role = ctx.deps.role
    # Gemini provides the 'status' based on the mapping rules in the system prompt
    final_status = status.strip()

    doc_name = ""
    base64_data = ""

    # Document Handling logic [Maintained from your original]
    if ctx.deps.document_data:
        media_type = ctx.deps.document_data.get("type")
        media_info = ctx.deps.document_data.get(media_type, {})
        if media_info:
            logger.info(f"Processing attachment for Task {task_id}")
            base64_data = download_and_encode_document(media_info)
            if base64_data:
                doc_name = media_info.get(
                    "filename",
                    f"{media_type}_update.png" if media_type == "image" else "update.pdf"
                )

    try:
        # Prepare request using the mandatory fields from your YAML [cite: 8, 10, 12]
        req = UpdateTaskRequest(
            SID="607",           # Mandatory Service ID [cite: 8]
            TASK_ID=task_id,     # Mandatory Task ID [cite: 12]
            STATUS=final_status, # Interpreted status 
            COMMENTS=remark or f"Status updated to {final_status}", # [cite: 9]
            UPLOAD_DOCUMENT=doc_name, 
            BASE64=base64_data 
        )

        api_response = await call_appsavy_api("UPDATE_STATUS", req)

        if not api_response:
            return "API failure: No response from server."

        # Handle API Response [cite: 13, 14]
        if isinstance(api_response, dict):
            if api_response.get("error"):
                return f"API failure: {api_response.get('error')}"

            # Success check (RESULT 1)
            if str(api_response.get("RESULT")) == "1" or str(api_response.get("result")) == "1":
                
                # Notification logic for Manager when Employee submits work
                if role == "employee" and final_status == "Close":
                    team = load_team()
                    employee = next((u for u in team if u["phone"] == ctx.deps.sender_phone), None)
                    
                    manager_phone = os.getenv("MANAGER_PHONE")
                    phone_id = os.getenv("PHONE_NUMBER_ID")

                    if employee and manager_phone and phone_id:
                        notification_msg = (
                            f"Task Submitted for Approval\n\n"
                            f"Employee: {employee['name'].title()}\n"
                            f"Task ID: {task_id}\n"
                            f"Remark: {remark or 'N/A'}"
                        )
                        send_whatsapp_message(manager_phone, notification_msg, phone_id)

                return f"Success: Task {task_id} updated to '{final_status}'."
            
            return f"API Error: {api_response.get('resultmessage', 'Invalid Request')}"
        
        return "API failure: Unexpected response format."

    except Exception as e:
        logger.error(f"update_task_status_tool error: {str(e)}", exc_info=True)
        return f"Error updating task: {str(e)}"
    
async def handle_message(command, sender, pid, message=None, full_message=None):
    if command and command.strip().lower() == "delete & add":
        send_whatsapp_message(
            sender,
            "Please resend user details in this format:\n\n"
            "Add user\nName\nMobile\nEmail",
            pid
        )
        return

    try:
        if len(sender) == 10 and not sender.startswith('91'):
            sender = f"91{sender}"
    
        is_media = False
        if message:
            is_media = any(k in message for k in ["document", "image", "video", "audio", "type"])
    
        if is_media and not command:
            send_whatsapp_message(
                sender,
               "File received. Please provide the assignee name, task description, and deadline to complete the assignment.",
                pid
            )
            return
    
        manager_phone = os.getenv("MANAGER_PHONE", "919871536210")
        team = load_team()
    
        if sender == manager_phone:
            role = "manager"
        elif any(u['phone'] == sender for u in team):
            role = "employee"
        else:
            role = None
    
        if not role:
            send_whatsapp_message(sender, "Access Denied: Your number is not authorized to use this system.", pid)
            return
    
        if sender not in conversation_history:
            conversation_history[sender] = []
    
        if command:
            try:
                assignees = extract_multiple_assignees(command, team)
                if len(assignees) > 1:
                    for name in assignees:
                        await assign_new_task_tool(
                            ctx=ManagerContext(
                            sender_phone=sender,
                            role=role,
                            current_time=datetime.datetime.now()
                            ),
                            name=name,
                            task_name=command,
                            deadline=datetime.datetime.now().strftime("%Y-%m-%d")
                        )
                    send_whatsapp_message(
                           sender,
                          f"Task successfully assigned to:\n" + "\n".join(assignees),
                          pid
                            )
                    return  

                current_time = datetime.datetime.now()
                dynamic_prompt = get_system_prompt(current_time)
            
                current_agent = Agent(ai_model, deps_type=ManagerContext, system_prompt=dynamic_prompt)
                
                current_agent.tool(get_performance_report_tool)
                current_agent.tool(get_task_list_tool)
                current_agent.tool(assign_new_task_tool)
                current_agent.tool(assign_task_by_phone_tool)
                current_agent.tool(update_task_status_tool)
                current_agent.tool(get_assignee_list_tool)
                current_agent.tool(get_users_by_id_tool)
                current_agent.tool(send_whatsapp_report_tool)
                current_agent.tool(add_user_tool)
                current_agent.tool(delete_user_tool)
            
                result = await current_agent.run(
                    command,
                    message_history=conversation_history[sender],
                    deps=ManagerContext(
                        sender_phone=sender, 
                        role=role, 
                        current_time=current_time,
                        document_data=message  
                    )
                )
            
                conversation_history[sender] = result.all_messages()
            
                if len(conversation_history[sender]) > 10:
                    
                    conversation_history[sender] = conversation_history[sender][-10:]
            
                send_whatsapp_message(sender, result.output, pid)
            
            except Exception as e:
                logger.error(f"Agent execution failed: {str(e)}", exc_info=True)
                send_whatsapp_message(sender, f"System Error: Unable to process request. Please try again.", pid)
            
    except Exception as e:
        logger.error(f"handle_message error: {str(e)}", exc_info=True)
        send_whatsapp_message(sender, "An unexpected error occaurred. Please try again.", pid)