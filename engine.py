import os
from pymongo import MongoClient
import certifi
import json
from pydantic import RootModel
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
    
    "CHECK_OWNERSHIP": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient", # [cite: 3]
        "headers": {
            "sid": "632",         # Session ID [cite: 5]
            "pid": "309",         # Project ID [cite: 5]
            "fid": "13598",       # Form ID [cite: 6]
            "cid": "64",          # Client ID [cite: 7]
            "uid": "TM_API",      # User ID [cite: 8]
            "roleid": "1627",     # Role ID [cite: 9]
            "TokenKey": "d103e11f-3aff-4785-aae0-564facf33261" # [cite: 9]
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

    "UPDATE_STATUS": {
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient",
        "headers": {
            "sid": "607",
            "pid": "309",
            "fid": "10345",  # Updated to match Dak Management Form ID
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "7bf28d4d-c14f-483d-872a-78c9c16bd982"
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
            "sid": "609", # Verify if this SID should be different for detail lookup
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

ai_model = GeminiModel('gemini-2.5-pro')

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

class PerformanceCountResult(BaseModel):
    ASSIGNED_TASK: int = 0
    OPEN_TASK: int = 0
    DELAYED_OPEN_TASK: int = 0
    CLOSED_TASK: int = 0
    DELAYED_CLOSED_TASK: int = 0

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
### ADD USER TOOL (CRITICAL):
When the user wants to add a user
(e.g. "add user", "create user", "register user"):

You MUST:
1. Extract:
   - name
   - mobile number (10 digits)
   - email
2. Call the tool add_user_tool
3. Pass arguments exactly as:
   - name
   - email
   - mobile
4. Do NOT ask any follow-up questions if all values are present
5. Execute immediately

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

### TASK LISTING:
When user asks to see tasks, list tasks, pending work:
- Use 'get_task_list_tool'
- Without name → Show tasks for the requesting user
- With name (managers only) → Show tasks for specified employee
- Show the tasks exactly as returned by the API without applying additional sorting
- IMPORTANT:
When responding with task lists, return the tool output EXACTLY as-is.
Do not summarize, rephrase, or omit any fields.

### UPDATE TASK STATUS
You are a task workflow interpreter for a backend system.
Your job is to understand the user's intent and determine the correct
new_status value for API SID 607 based on:
- The user's role relative to the specific task
- The meaning of their message

You MUST follow these rules strictly:
1. Determine the user's role ONLY from the provided context.
   - Employee = Assignee of the task
   - Manager = Reporter/Creator of the task
2. Strictly distinguish between:
   - "Close"  → employee submission for approval
   - "Closed" → manager final closure
3. Never allow:
   - Employees to use: Closed, Reopened
   - Managers to use: Work In Progress, Close
4. Interpret natural language correctly:
   - "done", "finished", "completed", "close", "closed", "submit" by an employee means submission, not final closure, i.e close tag
   - "approve", "looks good", "final close", "close", "closed" by a manager means final closure, i.e closed tag
5. Do NOT ask the user any questions.
6. Do NOT explain rules.
7. Do NOT include anything outside valid JSON.

**DOCUMENT HANDLING:**
**Case 1 (Manager):** If a document/image is sent while creating a task, use `assign_new_task_tool`. 
**Case 2 (Employee):** If a document/image is sent with a "completed" or "closed" message, use `update_task_status_tool` with status `Close` .
**Case 3 (Update):** If a document is sent during work, use `update_task_status_tool` with status `Work In Progress`.

### PERFORMANCE REPORTING:
When the user asks for performance, statistics, counts, or a performance report:
Performance reporting rules:
- When no employee name is mentioned:
  - Use SID 627 with REPORT_TYPE = "Detail"
  - Send PDF on WhatsApp
- When a specific employee is mentioned:
  - Use GET_COUNT (SID 616)
  - Show text summary to the requester
  - Do NOT send WhatsApp to the employee

Interpretation rules:
1. If the user does not mention any employee name:
- Treat the request as a general performance report.
- Generate the report for all employees (Managers only).
- Use SID 627 with REPORT_TYPE = "Detail".
- Send the PDF report on WhatsApp.
- The user does not need to explicitly say “PDF”.

2. If the user mentions a specific employee name or login code:
- Use SID 627 with REPORT_TYPE = "Count".
- Show the count summary AND pending tasks in text format.
- Do not generate or send a PDF.

3. Do not infer PDF intent from keywords.
- PDF is implied automatically for general (no-name) performance requests.
- Text summary is implied automatically for named employee requests.

4. Employees may only view their own performance.
- Managers may view performance for all employees.

5. Return results exactly as provided by SID 627.
- Do not calculate, derive, or modify counts.
- Missing values must be treated as zero.

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

class UploadDocument(BaseModel):
    VALUE: str = ""
    BASE64: str = ""

class UpdateTaskRequest(BaseModel):
    SID: str = "607"
    TASK_ID: str
    STATUS: str
    COMMENTS: str
    UPLOAD_DOCUMENT: UploadDocument
    WHATSAPP_MOBILE_NUMBER: str


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
    ACTION: str            
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
                    if target_name in item_name or item_name in target_name:
                        login_code = item.get("ID") or item.get("LOGIN_ID")
                        status_note = "ID fetched from system list"
                        break

        # STEP 3: If we have an ID, save to MongoDB
        if login_code:
            new_user = {
                "name": name.lower().strip(),
                "phone": "+91" + mobile[-10:],
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
            users_collection.delete_one({"phone": "+91" + mobile[-10:]})
            logger.info(f"User with mobile {mobile[-10:]} removed from MongoDB.")

        return "User deleted successfully from system and database."
    
    return f"Failed to delete user: {res.get('resultmessage')}"

def get_gmail_service():
    try:
        token_json_str = os.getenv("TOKEN_JSON")
        if not token_json_str: return None
        
        cleaned_token = "".join(c for c in token_json_str if ord(c) >= 32)
        token_data = json.loads(cleaned_token)
        
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        logger.error(f"Gmail Error: {e}")
        return None

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

def is_authorized(task_owner) -> bool:
    try:
        return int(task_owner) > 0
    except (TypeError, ValueError):
        return False

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
                (u for u in team if assigned_to == u["login_code"]),
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
            ASSIGNED_BY="",
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

async def get_performance_count_via_627(
    ctx: RunContext[ManagerContext],
    login_code: str
) -> Dict[str, int]:
    """
    SID 627 (Count) is a TRIGGER-ONLY API.
    It does NOT return counts.
    This function only triggers the report and returns an empty dict.
    """

    req = WhatsAppPdfReportRequest(
        ASSIGNED_TO=login_code,
        REPORT_TYPE="Count",
        STATUS="",
        MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
        ASSIGNED_BY="",
        REFERENCE="WHATSAPP"
    )

    # Trigger Appsavy internal report
    await call_appsavy_api("WHATSAPP_PDF_REPORT", req)

    # IMPORTANT: Do NOT return fake zeros
    return {}

async def get_task_summary_from_tasks(login_code: str) -> Dict[str, int]:
    res = await call_appsavy_api(
        "GET_TASKS",
        GetTasksRequest(
            Event="106830",
            Child=[{
                "Control_Id": "106831",
                "AC_ID": "110803",
                "Parent": [
                    {"Control_Id": "106827", "Value": login_code, "Data_Form_Id": ""},
                    {"Control_Id": "106829", "Value": "", "Data_Form_Id": ""},
                ]
            }]
        )
    )

    tasks = normalize_tasks_response(res)

    summary = {
        "ASSIGNED_TASK": len(tasks),
        "OPEN_TASK": 0,
        "DELAYED_OPEN_TASK": 0,   # Appsavy does not expose delay flag here
        "CLOSED_TASK": 0,
        "DELAYED_CLOSED_TASK": 0
    }

    for t in tasks:
        sts = str(t.get("STS", "")).lower()
        if sts in ("open", "wip", "work in progress", "in progress"):
            summary["OPEN_TASK"] += 1
        elif sts == "closed":
            summary["CLOSED_TASK"] += 1
    return summary

async def get_pending_tasks(login_code: str) -> List[str]:
    """
    Returns titles of pending tasks (Open / Work In Progress)
    using GET_TASKS (SID 610).
    """

    res = await call_appsavy_api(
        "GET_TASKS",
        GetTasksRequest(
            Event="106830",
            Child=[{
                "Control_Id": "106831",
                "AC_ID": "110803",
                "Parent": [
                    {"Control_Id": "106825", "Value": login_code, "Data_Form_Id": ""},
                    {"Control_Id": "106829", "Value": "", "Data_Form_Id": ""},
                ]
            }]
        )
    )

    tasks = normalize_tasks_response(res)

    pending = []
    for t in tasks:
        sts = str(t.get("STS", "")).lower()
        if sts in (
            "open",
            "wip",
            "work in progress",
            "in progress"
        ):
            title = t.get("COMMENTS")
            if title:
                pending.append(title)

    return pending

async def get_performance_report_tool(
    ctx: RunContext[ManagerContext],
    name: Optional[str] = None
) -> str:
    team = load_team()

    # ---------- NO NAME → PDF ----------
    if not name:
        if ctx.deps.role != "manager":
            return "Permission Denied: Only managers can view full performance reports."

        await send_whatsapp_report_tool(
            ctx,
            report_type="Detail",
            status="",
            assigned_to=None
        )

        return "Performance report PDF has been sent on WhatsApp."

    # ---------- NAME PRESENT → TEXT ----------
    user = next(
        (u for u in team
         if name.lower() in u["name"].lower()
         or name.lower() == u["login_code"].lower()),
        None
    )

    if not user:
        return f"User '{name}' not found."

    # Trigger SID 627 (Count) — no data expected
    await get_performance_count_via_627(ctx, user["login_code"])

    # REAL data source
    counts = await get_task_summary_from_tasks(user["login_code"])
    pending_tasks = await get_pending_tasks(user["login_code"])

    output = (
        f"Performance Summary:\n\n"
        f"Assigned Tasks: {counts['ASSIGNED_TASK']}\n"
        f"Open Tasks: {counts['OPEN_TASK']}\n"
        f"Closed Tasks: {counts['CLOSED_TASK']}\n\n"
    )

    if pending_tasks:
        output += "Pending Tasks:\n"
        for i, t in enumerate(pending_tasks, 1):
            output += f"{i}. {t}\n"
    else:
        output += "No pending tasks "

    return output.strip()

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


def extract_task_id(text: str):
    match = re.search(r"\btask\s*(\d+)\b", text.lower())
    return match.group(1) if match else None


def resolve_status(text: str, role: str):
    t = text.lower()

    # Future / pending → Work In Progress
    if any(x in t for x in [
        "pending",
        "in progress",
        "working",
        "will be completed",
        "by "
    ]):
        return "Work In Progress"

    # Done / completed → Close or Closed
    if any(x in t for x in [
        "done",
        "completed",
        "finished"
    ]):
        return "Closed" if role == "manager" else "Close"

    # Reopen
    if "reopen" in t:
        return "Reopened"

    return None


def extract_remark(text: str, task_id: str):
    t = text.lower()

    # task id hatao
    t = re.sub(rf"task\s*{task_id}", "", t)

    # status words hatao
    for w in [
        "is pending",
        "pending",
        "in progress",
        "will be completed",
        "completed",
        "done",
        "finished"
    ]:
        t = t.replace(w, "")

    t = re.sub(r"\s+", " ", t).strip(" .,")

    return t.capitalize() if t else ""


async def assign_new_task_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    task_name: str,
    deadline: str
) -> str:
    """
    Assigns a new task to a user or group.
    Fixes: Duplicate name resolution, N/A phone numbers, and Meta 24h window blockage.
    """
    try:
        # 1. MERGE SOURCES: Fetch candidates from BOTH MongoDB and Appsavy (SID 606)
        team = load_team()
        mongo_matches = [u for u in team if name.lower() in u["name"].lower() or name.lower() == u["login_code"].lower()]

        assignee_res = await call_appsavy_api("GET_ASSIGNEE", GetAssigneeRequest(
            Event="0", 
            Child=[{"Control_Id": "106771", "AC_ID": "111057"}]
        ))
        
        appsavy_users = []
        if isinstance(assignee_res, dict):
            appsavy_users = assignee_res.get("data", {}).get("Result", [])
        elif isinstance(assignee_res, list):
            appsavy_users = assignee_res

        appsavy_matches = [
            {"name": u.get("NAME") or u.get("PARTICIPANT_NAME"), "login_code": u.get("ID") or u.get("LOGIN_ID"), "phone": "N/A"} 
            for u in appsavy_users if name.lower() in str(u.get("NAME", "")).lower()
        ]

        # Deduplicate using Login ID to ensure we catch every unique instance
        combined = {}
        for u in mongo_matches:
            combined[u["login_code"]] = u

        for u in appsavy_matches:
            if u["login_code"] not in combined:
                combined[u["login_code"]] = u

        matches = list(combined.values())

        if not matches:
            return f"Error: User or Group '{name}' not found in the authorized directory."

        # 2. DEEP LOOKUP & HIERARCHY: If multiple matches, fetch REAL details (SID 609)
        if len(matches) > 1:
            final_options = []
            for candidate in matches:
                # Call Detail API (SID 609) to get Mobile + Division + Zone
                details_res = await call_appsavy_api("GET_USERS_BY_ID", GetUsersByIdRequest(
                    Event="107018",
                    Child=[{
                        "Control_Id": "107019",
                        "AC_ID": "111271",
                        "Parent": [{"Control_Id": "106771", "Value": candidate["login_code"], "Data_Form_Id": ""}]
                    }]
                ))
                
                # If API succeeds, extract phone and office data
                if isinstance(details_res, list) and len(details_res) > 0:
                    detail = details_res[0]
                    candidate["phone"] = detail.get("MOBILE") or detail.get("PHONE") or "N/A"
                    # Capture Hierarchy levels
                    office_parts = [
                        detail.get("ZONE_NAME"),
                        detail.get("CIRCLE_NAME"),
                        detail.get("DIVISION_NAME")
                    ]
                    candidate["office"] = " > ".join([p for p in office_parts if p]) or "Office N/A"
                elif isinstance(details_res, dict) and "data" in details_res:
                    res_list = details_res.get("data", {}).get("Result", [])
                    if res_list:
                        candidate["phone"] = res_list[0].get("MOBILE") or "N/A"
                        candidate["office"] = res_list[0].get("DIVISION_NAME") or "Office N/A"
                
                final_options.append(candidate)

            # Format clarification message with Hierarchy and Phone Numbers
            options_text = "\n".join([f"- {u['name']} ({u.get('office', 'Office N/A')}): {u['phone']}" for u in final_options])
            return (
                f"I found multiple users named '{name}'. Who should I assign this to?\n\n"
                f"{options_text}\n\n"
                "Please reply with the correct 10-digit phone number."
            )

        # 3. SINGLE MATCH FOUND: Proceed with Assignment (SID 604)
        user = matches[0]
        login_code = user["login_code"]

        # 2. Handle Document Attachment
        documents_child = []
        document_data = getattr(getattr(ctx, "deps", None), "document_data", None)
        if document_data:            
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
                    # FIX: RE-OPEN 24H WINDOW FIRST
                    # We send the registration template to ensure the conversation session is active
                    send_registration_template(
                        recipient_number=user["phone"],
                        user_identifier=user["name"].title(),
                        phone_number_id=phone_id
                    )
                    
                    # Wait briefly to let Meta register the new Utility session
                    await asyncio.sleep(1.8)
                    
                    # Now send the free-form Task Details
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
    "submit": "Close",
    "submitted": "Close"

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

def resolve_final_status(intent: str, relationship: str, role: str) -> Optional[str]:
    if intent == "CLOSE_TASK":
        if role == "manager":
            return "Closed"
        if relationship in ["REPORTER", "ASSIGNEE"]:
            return "Close"

    if intent == "REOPEN_TASK":
        return "Reopened"
    return None

APPSAVY_STATUS_MAP = {
    "Open": "Open",
    "Work In Progress": "Work In Progress",
    "Close": "CLosed",
    "Closed": "Closed",
    "Reopened": "Reopen"
}

async def update_task_status_tool(
    ctx: RunContext[ManagerContext],
    task_id: str,
    status: str,
    remark: Optional[str] = None
) -> str:

    if not task_id:
        return "Please mention the Task ID you want to update."

    sender_mobile = ctx.deps.sender_phone[-10:]

    # ---- Ownership check (SID 632) ----
    ownership_payload = {
        "Event": "146560",
        "Child": [{
            "Control_Id": "146561",
            "AC_ID": "201877",
            "Parent": [
                {"Control_Id": "146559", "Value": task_id, "Data_Form_Id": ""},
                {"Control_Id": "146562", "Value": sender_mobile, "Data_Form_Id": ""}
            ]
        }]
    }

    ownership_res = await call_appsavy_api(
        "CHECK_OWNERSHIP",
        RootModel(ownership_payload)
    )

    result = ownership_res.get("data", {}).get("Result", [])
    if not result or not is_authorized(result[0].get("TASK_OWNER")):
        return f"Permission Denied: You are not authorized to update Task {task_id}."

    # ---- Role guard ----
    if ctx.deps.role == "employee" and status == "Closed":
        return "Final closure requires manager approval."

    # ---- STATUS MAPPING ----
    appsavy_status = APPSAVY_STATUS_MAP.get(status)
    if not appsavy_status:
        return f"Unsupported status '{status}'."

    # ---- FINAL PAYLOAD (EXACT FORMAT) ----
    req = UpdateTaskRequest(
        TASK_ID=task_id,
        STATUS=appsavy_status,               # internal code
        COMMENTS=remark or "Terminal Test",
        UPLOAD_DOCUMENT={
            "VALUE": "",
            "BASE64": ""
        },
        WHATSAPP_MOBILE_NUMBER=sender_mobile
    )

    api_response = await call_appsavy_api("UPDATE_STATUS", req)

    if api_response and str(api_response.get("RESULT")) == "1":
        if status == "Close":
            return f"Task {task_id} submitted for manager approval."
        if status == "Closed":
            return f"Task {task_id} closed successfully."
        if status == "Reopened":
            return f"Task {task_id} reopened."
        return f"Task {task_id} updated."

    return f"API Error: {api_response.get('resultmessage', 'Update failed')}"

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
            
                output_text = result.output
                if output_text.strip().startswith("{"):
                    try:
                        data = json.loads(output_text)
                        if "task_id" in data and "status" in data:
                            status = data["status"]
                            task_id = data["task_id"]
                            if status == "Close":
                                output_text = (
                                    f"Task {task_id} has been marked as completed "
                                    "and sent for manager approval."
                                )
                            elif status == "Closed":
                                output_text = f"Task {task_id} has been closed successfully."
                            elif status == "Reopened":
                                output_text = f"Task {task_id} has been reopened."
                            else:
                                output_text = f"Task {task_id} updated to {status}."

                    except Exception:
                        pass
                send_whatsapp_message(sender, output_text, pid)

            
            except Exception as e:
                logger.error(f"Agent execution failed: {str(e)}", exc_info=True)
                send_whatsapp_message(sender, f"System Error: Unable to process request. Please try again.", pid)
            
    except Exception as e:
        logger.error(f"handle_message error: {str(e)}", exc_info=True)
        send_whatsapp_message(sender, "An unexpected error occaurred. Please try again.", pid)