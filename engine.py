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
import asyncio
from send_message import send_registration_template

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://ai-task-manager-38w7.onrender.com/oauth2callback")
MANAGER_EMAIL = "patodiaaadi@gmail.com"

conversation_history: Dict[str, List[Any]] = {}

APPSAVY_BASE_URL = "https://configapps.appsavy.com/api/AppsavyRestService"

API_CONFIGS = {
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
            "fid": "10349",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "e5b4e098-f8b9-47bf-83f1-751582bfe147"
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

### TASK STATUS WORKFLOW:
1. **Pending** - Task is still open and not completed
2. **Work Done** - Employee uses 'reported' action
3. **Completed** - Manager uses 'close' action to approve

**Status Actions:**
- 'pending' → "Open" (task not completed)
- 'open' → "Open"
- 'partial' → "Partially Closed" (work in progress)
- 'reported' → "Reported Closed" (employee marks as done, awaits approval)

**Role Permissions:**
- Employees: Can mark tasks as 'pending' (open), 'partial' (in progress), or 'reported' (completed by employee)
- Managers: Can 'close' (approve) or 'reopen' (reject) tasks

When updating task status, extract any additional text from the user's message as a remark and pass it in the COMMENTS field.

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
- Show the tasks exactly as returned by the API without applying additional sorting

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
    """Static team directory - source of truth for authentication and name resolution."""
    return [
        {"name": "mdpvvnl", "phone": "919650523477", "email": "varun.verma@mobineers.com", "login_code": "D-3514-1001"},
        {"name": "chairman", "phone": "919310104458", "email": "abhilasha1333@gmail.com", "login_code": "D-3514-1003"},
        {"name": "mddvvnl", "phone": "917428134319", "email": "patodiaaadi@gmail.com", "login_code": "D-3514-1002"},
        {"name": "ce_ghaziabad", "phone": "91XXXXXXXXXX", "email": "ce@example.com", "login_code": "D-3514-1004"}
    ]

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
    MANUAL_DIARY_NUMBER: str = "er3"
    REFERENCE: str = "WHATSAPP_TASK"
    MOBILE_NUMBER: str
    NATURE_OF_COMPLAINT: str = "1"
    NOTICE_BEFORE: str = "4"
    NOTIFICATION: str = ""
    ORIGINAL_LETTER_NUMBER: str = "32"
    PRIORTY_TASK: str = "N"
    REFERENCE_LETTER_NUMBER: str = "334"
    TASK_NAME: str
    TYPE: str = "TYPE"
    DETAILS: Details
    DOCUMENTS: Documents

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
    if isinstance(tasks_data, dict):
        return tasks_data.get("data", {}).get("Result", [])
    if isinstance(tasks_data, list):
        return tasks_data
    return []

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
    """Retrieves aggregate counts via SID 616 - API dependent with robust error handling."""
    assignment_value = "Assigned By Me" if ctx_role == "manager" else "Assigned To Me"
    req = GetCountRequest(Child=[{
        "Control_Id": "108118",
        "AC_ID": "113229", # Updated from YAML source [cite: 13]
        "Parent": [
            {"Control_Id": "111548", "Value": "1", "Data_Form_Id": ""},
            {"Control_Id": "107566", "Value": login_code, "Data_Form_Id": ""}, # Assignee ID [cite: 20]
            {"Control_Id": "107568", "Value": "", "Data_Form_Id": ""},
            {"Control_Id": "107569", "Value": "", "Data_Form_Id": ""},
            {"Control_Id": "107599", "Value": assignment_value, "Data_Form_Id": ""},
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
            ASSIGNED_BY="Assigned By Me" if ctx.deps.role == "manager" else "Assigned To Me",
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
                    name = item.get("NAME") or item.get("PARTICIPANT_NAME")
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
                    name = item.get("NAME") or item.get("USER_NAME")
                    email = item.get("EMAIL")
                    phone = item.get("PHONE") or item.get("MOBILE")
                    
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
            name = api_response.get("NAME") or api_response.get("USER_NAME")
            email = api_response.get("EMAIL")
            phone = api_response.get("PHONE") or api_response.get("MOBILE")
            
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
    - SID 610 for task details
    """
    try:
        team = load_team()

        # 🔒 Role check
        if not name and ctx.deps.role != "manager":
            return "Permission Denied: Only managers can view the full team report."

        # 🔹 Decide whose tasks to fetch in GET_TASKS
        assignee_login = ""

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
            assignee_login = matched["login_code"]

        elif ctx.deps.role != "manager":
            self_user = next(
                (u for u in team if u["phone"] == ctx.deps.sender_phone),
                None
            )
            if not self_user:
                return "Unable to identify your profile."
            assignee_login = self_user["login_code"]

        # 🔹 Status filter
        status_filter = build_status_filter(ctx.deps.role)

        # 🔹 Fetch tasks (SID 610)
        raw_tasks_data = await call_appsavy_api(
            "GET_TASKS",
            GetTasksRequest(
                Child=[{
                    "Control_Id": "106831",
                    "AC_ID": "110803",
                    "Parent": [
                        {"Control_Id": "106825", "Value": status_filter, "Data_Form_Id": ""},
                        {"Control_Id": "106824", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "106827", "Value": assignee_login, "Data_Form_Id": ""},
                        {"Control_Id": "106829", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "107046", "Value": "", "Data_Form_Id": ""},
                        {"Control_Id": "107809", "Value": "0", "Data_Form_Id": ""}
                    ]
                }]
            )
        )

        tasks_data = normalize_tasks_response(raw_tasks_data)
        now = ctx.deps.current_time

        # 🔹 Decide whose report to show
        if name:
            display_team = [matched]
        elif ctx.deps.role == "manager":
            display_team = team
        else:
            display_team = [self_user]

        results = []

        for member in display_team:
            member_login = member["login_code"]

            try:
                counts = await fetch_task_counts_api(member_login, ctx.deps.role)

                member_tasks = [
                    t for t in tasks_data
                    if isinstance(t, dict) and t.get("ASSIGNEE") == member_login
                ]

                within_time = 0
                beyond_time = 0
                closed_count = 0

                for task in member_tasks:
                    status = str(task.get("STS", "")).lower()
                    expected_date = task.get("EXPECTED_END_DATE")

                    if status == "closed":
                        closed_count += 1
                    elif expected_date:
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
                    f"Name- {member['name'].title()}\n"
                    f"Task Assigned- Count of Task {assigned_count} Nos\n"
                    f"Task Completed- Count of task {closed_from_api} Nos\n"
                    f"Task Pending -\n"
                    f"Within time: {within_time}\n"
                    f"Beyond time: {beyond_time}"
                )

            except Exception as member_error:
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

        output = f"Tasks assigned to you ({user['name'].title()}):\n\n"
        for t in tasks:
            output += (
                f"ID: {t.get('TID')}\n"
                f"Task: {t.get('COMMENTS')}\n"
                f"Assigned On: {t.get('ASSIGN_DATE')}\n"
                f"Status: {t.get('STS')}\n\n"
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

async def assign_new_task_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    task_name: str,
    deadline: str
) -> str:
    try:
        # Step 1: Resolve Name/ID using the GET_USERS_BY_ID API (SID 609)
        # This handles both individual IDs (D-...) and Group IDs (G-...) 
        lookup_req = GetUsersByIdRequest(
            Child=[{"Control_Id": "107019", "AC_ID": "111271", 
                    "Parent": [{"Control_Id": "106771", "Value": name, "Data_Form_Id": ""}]}]
        )
        user_info = await call_appsavy_api("GET_USERS_BY_ID", lookup_req)
        
        if not user_info or (isinstance(user_info, dict) and "error" in user_info):
            return f"Error: Could not find user or group '{name}' in the system."

        # Extract the resolved Login ID (e.g., D-3514-1001) 
        user = user_info[0] if isinstance(user_info, list) else user_info
        login_code = user.get("LOGIN_ID") or user.get("USER_ID")
        
        # Step 2: Proceed to Create Task (SID 604) using the resolved code [cite: 80]
        req = CreateTaskRequest(
            ASSIGNEE=login_code,
            DESCRIPTION=task_name,
            EXPECTED_END_DATE=deadline.split('T')[0],
            TASK_NAME=task_name,
            MOBILE_NUMBER=user.get("PHONE", ""),
            DETAILS=Details(CHILD=[DetailChild(
                SEL="Y",
                LOGIN=login_code,
                PARTICIPANTS=user.get("NAME", "USER").upper()
            )]),
            DOCUMENTS=Documents(CHILD=[])
        )
        
        logger.info(f"Attempting to create task for {login_code}")
        logger.info(f"Full Payload: {req.model_dump_json(indent=2)}")
        
        api_response = await call_appsavy_api("CREATE_TASK", req)
        
        logger.info(f"Raw API Response: {api_response}")
        
        if not api_response:
            return "API failure: No response from server."
        
        if isinstance(api_response, dict):
            if api_response.get('error'):
                return f"API failure: {api_response.get('error')}"
            
            if api_response.get('RESULT') == 1 or api_response.get('result') == 1:
                whatsapp_msg = (
                    f"New Task Assigned:\n\n"
                    f"Task: {task_name}\n"
                    f"Due Date: {deadline}\n\n"
                    f"Please complete on time."
                )

                phone_id = os.getenv("PHONE_NUMBER_ID")
                if not phone_id:
                    logger.error("PHONE_NUMBER_ID missing. WhatsApp notification skipped.")
                else:
                    wa_status = send_registration_template(
                        recipient_number=user.get("PHONE", ""),
                        customer_name=user.get("NAME", "").title(),
                        phone_number_id=phone_id
                    )

                    if wa_status:
                        logger.info(f"Template successfully sent to {user.get('NAME', '')}")
                    else:
                        logger.error(f"Failed to send template to {user.get('NAME', '')}")

                    send_whatsapp_message(
                        user.get("PHONE", ""),
                        whatsapp_msg,
                        phone_id
                    )

                email_subject = f"New Task Assigned: {task_name}"
                email_body = f"""Dear {user.get("NAME", "").title()},
                You have been assigned a new task:
                Task Name: {task_name}
                Due Date: {deadline}
                
                Please ensure timely completion.
                Best regards,
                """

                send_email(
                    user.get("EMAIL", ""),
                    email_subject,
                    email_body
                )

                manager_subject = f"Task Assignment Confirmation: {task_name}"
                manager_body = f"""Task Assignment Confirmed

                Assignee: {user.get("NAME", "").title()}
                Task: {task_name}
                Due Date: {deadline}

                The task has been successfully assigned and the employee has been notified.
                """
                send_email(MANAGER_EMAIL, manager_subject, manager_body)
                
                return f"Task successfully assigned to {user['name'].title()} (Login: {login_code}).\nNotifications sent via WhatsApp and email."
            else:
                return f"API returned unexpected response: {api_response}"
        
        return "API failure: Unexpected response format."
        
    except Exception as e:
        logger.error(f"assign_new_task_tool error: {str(e)}", exc_info=True)
        return f"Error assigning task: {str(e)}"

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

async def update_task_status_tool(ctx: RunContext[ManagerContext], task_id: str, action: str, remark: Optional[str] = None) -> str:

    """
    Updates task status via API (SID 607).
    Enforces role-based permissions.
    """
    try:
        status_map = {
            # task NOT completed          
            "pending": "Open",
            "open": "Open",

            # task in progress
            "in progress": "Partially Closed",
            "partial": "Partially Closed",
            "working": "Partially Closed",

            # task completed by employee
            "completed": "Reported Closed",
            "done": "Reported Closed",
            "reported": "Reported Closed",

            # manager only
            "close": "Closed",
            "reopen": "Reopened"
        }


        
        new_status = status_map.get(action.lower())
        if not new_status:
            return "Error: Could not understand the requested task status."

        
        employee_statuses = {
            "Open",
            "Partially Closed",
            "Reported Closed"
        }

        manager_statuses = {
            "Closed",
            "Reopened"
        }

        if new_status in manager_statuses and ctx.deps.role != "manager":
            return "Permission Denied: Only managers can perform this action."

        if new_status in employee_statuses and ctx.deps.role != "employee":
            return "Permission Denied: Only employees can update task progress."

        
        team = load_team()
        user = next((u for u in team if u['phone'] == ctx.deps.sender_phone), None)
        if not user:
            return "Error: Could not identify your user profile."
        
        req = UpdateTaskRequest(
            TASK_ID=task_id,
            STATUS=new_status,
            COMMENTS=remark or "Updated by employee"
        )
        
        api_response = await call_appsavy_api("UPDATE_STATUS", req)
        
        if not api_response:
            return "API failure: No response from server."
        
        if isinstance(api_response, dict):
            if api_response.get('error'):
                return f"API failure: {api_response.get('error')}"
            
            if api_response.get('RESULT') == 1 or api_response.get('result') == 1:
                return f"Success: Task {task_id} updated to '{new_status}'."
            else:
                return f"API returned unexpected response: {api_response}"
    
    except Exception as e:
        logger.error(f"update_task_status_tool error: {str(e)}", exc_info=True)
        return f"Error updating task status: {str(e)}"
    
async def handle_message(command, sender, pid, message=None, full_message=None):
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
    
        manager_phone = os.getenv("MANAGER_PHONE", "919650523477")
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
                 # 🔹 STEP 1: detect multiple assignees
                assignees = extract_multiple_assignees(command, team)
                 # 🔹 STEP 2: MULTI ASSIGNEE CASE
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
                    return  # 🚨 agent.run() yahin stop


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

            
                result = await current_agent.run(
                    command,
                    message_history=conversation_history[sender],
                    deps=ManagerContext(sender_phone=sender, role=role, current_time=current_time)
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