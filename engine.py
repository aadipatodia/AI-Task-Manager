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
    "ADD_DELETE_USER":{
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient",
        "headers": {
            "sid": "629",
            "pid": "309",
            "fid": "13580",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "799f57e5-af33-4341-9c0f-4c0f42ac9f79",
            "Cookie": ".AspNetCore.Antiforgery.DX06PTKdFOY=CfDJ8GsECdYRlwNDiE7FrXiNS9Vu1CzEhlc1-hKzhaifpxNfxBVBZbIgQXCNNvjyztiNjIqPWZr4FfxnVzUIs_ywP_M7udcWQj9oE-9aeSV7fruLH-MIiiGtQupgqSF1sn7zwJe-i_JM6BWaB66ksSMKU7E; XSRF-TOKEN=CfDJ8GsECdYRlwNDiE7FrXiNS9UyorRB1iuiI3RpvBinv1Dbh7vgW3WCkIAe2aAJN2XPLUnForPtj6yvncAR9pZdVq2Gm5oWHHivN5GEznNsNPSlcHdQb6NkCrtP3oUTLbfWURR9It4Jp-5WEW_SAwE6e9E"
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
            "TokenKey": "17bce718-18fb-43c4-90bb-910b19ffb34b",
            "Cookie": ".AspNetCore.Antiforgery.DX06PTKdFOY=CfDJ8GsECdYRlwNDiE7FrXiNS9Vu1CzEhlc1-hKzhaifpxNfxBVBZbIgQXCNNvjyztiNjIqPWZr4FfxnVzUIs_ywP_M7udcWQj9oE-9aeSV7fruLH-MIiiGtQupgqSF1sn7zwJe-i_JM6BWaB66ksSMKU7E; XSRF-TOKEN=CfDJ8GsECdYRlwNDiE7FrXiNS9UyorRB1iuiI3RpvBinv1Dbh7vgW3WCkIAe2aAJN2XPLUnForPtj6yvncAR9pZdVq2Gm5oWHHivN5GEznNsNPSlcHdQb6NkCrtP3oUTLbfWURR9It4Jp-5WEW_SAwE6e9E"
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
            "TokenKey": "d23e5874-ba53-4490-941f-0c70b25f6f56",
            "Cookie": ".AspNetCore.Antiforgery.DX06PTKdFOY=CfDJ8GsECdYRlwNDiE7FrXiNS9Vu1CzEhlc1-hKzhaifpxNfxBVBZbIgQXCNNvjyztiNjIqPWZr4FfxnVzUIs_ywP_M7udcWQj9oE-9aeSV7fruLH-MIiiGtQupgqSF1sn7zwJe-i_JM6BWaB66ksSMKU7E; XSRF-TOKEN=CfDJ8GsECdYRlwNDiE7FrXiNS9UyorRB1iuiI3RpvBinv1Dbh7vgW3WCkIAe2aAJN2XPLUnForPtj6yvncAR9pZdVq2Gm5oWHHivN5GEznNsNPSlcHdQb6NkCrtP3oUTLbfWURR9It4Jp-5WEW_SAwE6e9E"
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
            "TokenKey": "e5b4e098-f8b9-47bf-83f1-751582bfe147",
            "Cookie": ".AspNetCore.Antiforgery.DX06PTKdFOY=CfDJ8GsECdYRlwNDiE7FrXiNS9Vu1CzEhlc1-hKzhaifpxNfxBVBZbIgQXCNNvjyztiNjIqPWZr4FfxnVzUIs_ywP_M7udcWQj9oE-9aeSV7fruLH-MIiiGtQupgqSF1sn7zwJe-i_JM6BWaB66ksSMKU7E; XSRF-TOKEN=CfDJ8GsECdYRlwNDiE7FrXiNS9UyorRB1iuiI3RpvBinv1Dbh7vgW3WCkIAe2aAJN2XPLUnForPtj6yvncAR9pZdVq2Gm5oWHHivN5GEznNsNPSlcHdQb6NkCrtP3oUTLbfWURR9It4Jp-5WEW_SAwE6e9E"
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
            "TokenKey": "e5b4e098-f8b9-47bf-83f1-751582bfe147", 
            "Cookie": ".AspNetCore.Antiforgery.DX06PTKdFOY=CfDJ8GsECdYRlwNDiE7FrXiNS9Vu1CzEhlc1-hKzhaifpxNfxBVBZbIgQXCNNvjyztiNjIqPWZr4FfxnVzUIs_ywP_M7udcWQj9oE-9aeSV7fruLH-MIiiGtQupgqSF1sn7zwJe-i_JM6BWaB66ksSMKU7E; XSRF-TOKEN=CfDJ8GsECdYRlwNDiE7FrXiNS9UyorRB1iuiI3RpvBinv1Dbh7vgW3WCkIAe2aAJN2XPLUnForPtj6yvncAR9pZdVq2Gm5oWHHivN5GEznNsNPSlcHdQb6NkCrtP3oUTLbfWURR9It4Jp-5WEW_SAwE6e9E"
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
            "TokenKey": "75c6ec2e-9f9c-48fa-be24-d8eb612f4c03",
            "Cookie": ".AspNetCore.Antiforgery.DX06PTKdFOY=CfDJ8GsECdYRlwNDiE7FrXiNS9Vu1CzEhlc1-hKzhaifpxNfxBVBZbIgQXCNNvjyztiNjIqPWZr4FfxnVzUIs_ywP_M7udcWQj9oE-9aeSV7fruLH-MIiiGtQupgqSF1sn7zwJe-i_JM6BWaB66ksSMKU7E; XSRF-TOKEN=CfDJ8GsECdYRlwNDiE7FrXiNS9UyorRB1iuiI3RpvBinv1Dbh7vgW3WCkIAe2aAJN2XPLUnForPtj6yvncAR9pZdVq2Gm5oWHHivN5GEznNsNPSlcHdQb6NkCrtP3oUTLbfWURR9It4Jp-5WEW_SAwE6e9E"
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
            "TokenKey": "d23e5874-ba53-4490-941f-0c70b25f6f56",
            "Cookie": ".AspNetCore.Antiforgery.DX06PTKdFOY=CfDJ8GsECdYRlwNDiE7FrXiNS9Vu1CzEhlc1-hKzhaifpxNfxBVBZbIgQXCNNvjyztiNjIqPWZr4FfxnVzUIs_ywP_M7udcWQj9oE-9aeSV7fruLH-MIiiGtQupgqSF1sn7zwJe-i_JM6BWaB66ksSMKU7E; XSRF-TOKEN=CfDJ8GsECdYRlwNDiE7FrXiNS9UyorRB1iuiI3RpvBinv1Dbh7vgW3WCkIAe2aAJN2XPLUnForPtj6yvncAR9pZdVq2Gm5oWHHivN5GEznNsNPSlcHdQb6NkCrtP3oUTLbfWURR9It4Jp-5WEW_SAwE6e9E"
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
            "TokenKey": "dea16c4c-bf19-423f-a567-c2c265c7dd22",
            "Cookie": ".AspNetCore.Antiforgery.DX06PTKdFOY=CfDJ8GsECdYRlwNDiE7FrXiNS9Vu1CzEhlc1-hKzhaifpxNfxBVBZbIgQXCNNvjyztiNjIqPWZr4FfxnVzUIs_ywP_M7udcWQj9oE-9aeSV7fruLH-MIiiGtQupgqSF1sn7zwJe-i_JM6BWaB66ksSMKU7E; XSRF-TOKEN=CfDJ8GsECdYRlwNDiE7FrXiNS9UyorRB1iuiI3RpvBinv1Dbh7vgW3WCkIAe2aAJN2XPLUnForPtj6yvncAR9pZdVq2Gm5oWHHivN5GEznNsNPSlcHdQb6NkCrtP3oUTLbfWURR9It4Jp-5WEW_SAwE6e9E"
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


async def get_system_prompt(current_time: datetime.datetime) -> str:
    team = await get_dynamic_team_list()
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

### DIRECTORY ACCESS:
    If you are unsure of a user's Login ID or Name, you MUST use the 'get_assignee_list_tool' 
    to see the most up-to-date list of employees from the database. 
    Do not rely on a static list.

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
You must determine the correct 'new_status' string based on the user's role:

Assignees (Employees) Actions:
- Open: Acknowledging a task.
- Work In Progress: Use this when the user is actively working. 
  **IMPORTANT:** If an employee sends a document but says they are still working (e.g., "attached the draft, but ppt is pending"), keep the status as 'Work In Progress'. Do not move to 'Close' unless they indicate they are finished with the entire task.
- Close: Use ONLY when the employee indicates the total assignment is ready for final review. (It should be noted that if employee says something like "i have completed task <task_id>" then he means work is done from his side so apply close there, It doesn't mean that task is CLOSED there is a difference between close and closed).

Managers Actions:
- Closed: The user (manager) expresses satisfaction, approval, or finalization of the submitted work.
- Reopened: The user (manager) expresses dissatisfaction, rejects the work, or asks for revisions.

**CRITICAL:**
- Never use "Closed" for an employee. Never use "Close" for a manager's final approval.
- When updating task status, extract any additional text from the user's message as a remark and pass it in the COMMENTS field.
- Intent Interpretation: Map the intent of "starting/doing" to 'Work In Progress'. Map the intent of "submitting for review" to 'Close'. Map "final approval" to 'Closed'.
- Role Boundary: Never use "Closed" for an employee's message. Never use "Close" for a manager's final sign-off.
- Context: If a user says "I'm done with the first part," use 'Work In Progress'. If they say "Here is the final file," use 'Close'.
- ### DOCUMENT HANDLING:
- If a user sends a file with a status update (e.g., "I'm working on task 237, here is the doc"), extract the Task ID and the intent.
- Call 'update_task_status_tool' using the determined status (likely 'Work In Progress') and pass the document data to the tool.
- Acknowledge the receipt of the document specifically in your response (e.g., "I've updated Task 237 to Work In Progress and attached your document.").

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
- IMPORTANT:
When responding with task lists, return the tool output EXACTLY as-is.
Do not summarize, rephrase, or omit any fields.

### TASK ASSIGNMENT BY PHONE:
Support assignment using phone numbers:
- Extract 10-digit number or full format
- Use 'assign_task_by_phone_tool'

### USER LOOKUP:
When asked about users or resolving names:
- Use 'get_users_by_id_tool' with the ID from the directory.
- Note: IDs can start with 'D-' (Static User), 'G-' (Group), or 'O-' (Newly Created/Other). 
- All three formats ('D-', 'G-', 'O-') are valid for task assignment.

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

### DOCUMENT HANDLING:
- If a message contains [ATTACHED_BASE64: ...], extract that string and the filename.
- When calling 'update_task_status_tool' or 'assign_new_task_tool', pass these strings into the 'file_base64' and 'file_name' parameters.
- If a file is received without task details: Ask for assignee name, task description, and deadline.
- If a file is received with partial info: Ask for missing details.

### WHATSAPP PDF REPORTS:
When user asks to send, share, or receive a report on WhatsApp:
- Use 'send_whatsapp_report_tool'
- REPORT_TYPE: "Count" or "Detail"
- STATUS examples: Open, Closed, Reported Closed
- If no assignee specified, send report for requesting user

### IMPORTANT:
- Ignore WhatsApp headers like '[7:03 pm, 13/1/2026] ABC:' and focus only on the text after the colon.
"""

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
    COMMENTS: str = ""
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
    req = AddDeleteUserRequest(
        ACTION="Add",
        CREATOR_MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
        NAME=name,
        EMAIL=email,
        MOBILE_NUMBER=mobile[-10:]
    )

    res = await call_appsavy_api("ADD_DELETE_USER", req)

    if isinstance(res, dict) and (res.get("RESULT") == 1 or res.get("result") == 1):

        return f"User {name} added successfully."
    return f"Failed to add user: {res}"

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

    if isinstance(res, dict) and (res.get("RESULT") == 1 or res.get("result") == 1):
        return f"User {name} deleted successfully."
    return f"Failed to delete user: {res}"

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

def to_appsavy_datetime(iso_dt: str) -> str:
    """
    Converts ISO datetime (YYYY-MM-DDTHH:MM:SS)
    to Appsavy format: YYYY-MM-DD HH:MM:SS.mmm
    """
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
    if isinstance(tasks_data, dict):
        return tasks_data.get("data", {}).get("Result", [])
    if isinstance(tasks_data, list):
        return tasks_data
    return []

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
    Sends WhatsApp PDF report using SID 627. Resolved dynamically via API.
    """
    try:
        team = await get_dynamic_team_list()

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
            # Match sender phone to API user to get their login_code
            user = None
            for u in team:
                detail_req = GetUsersByIdRequest(
                    Child=[{"Control_Id": "107019", "AC_ID": "111271", "Parent": [{"Control_Id": "106771", "Value": u["login_code"], "Data_Form_Id": ""}]}]
                )
                details = await call_appsavy_api("GET_USERS_BY_ID", detail_req)
                u_phone = ""
                if isinstance(details, list) and len(details) > 0:
                    u_phone = str(details[0].get("phone") or details[0].get("MOBILE") or "")
                
                if u_phone.endswith(ctx.deps.sender_phone[-10:]):
                    user = u
                    break

        if not user:
            return "Unable to resolve your profile for the report."

        # Fetch full details for the specific phone number required for SID 627
        final_details_req = GetUsersByIdRequest(
            Child=[{"Control_Id": "107019", "AC_ID": "111271", "Parent": [{"Control_Id": "106771", "Value": user["login_code"], "Data_Form_Id": ""}]}]
        )
        final_res = await call_appsavy_api("GET_USERS_BY_ID", final_details_req)
        
        target_phone = ""
        if isinstance(final_res, list) and len(final_res) > 0:
            target_phone = str(final_res[0].get("phone") or final_res[0].get("MOBILE") or "")

        req = WhatsAppPdfReportRequest(
            ASSIGNED_TO=user["login_code"],
            REPORT_TYPE=report_type,
            STATUS=status,
            MOBILE_NUMBER=target_phone[-10:],
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
        now = ctx.deps.current_time

        if not name and ctx.deps.role != "manager":
            return "Permission Denied: Only managers can view the full team report."

        # --- STEP 1: Fetch current employees from API ---
        list_req = GetAssigneeRequest(Child=[{"Control_Id": "106771", "AC_ID": "111057"}])
        api_res = await call_appsavy_api("GET_ASSIGNEE", list_req)
        
        if not api_res or not isinstance(api_res, list):
            return "Error: Could not retrieve the current employee list from the system."

        # Create the dynamic team list from API results
        api_team = [
            {
                "name": (u.get("name") or u.get("PARTICIPANT_NAME") or "Unknown"), 
                "login_code": (u.get("LOGIN_ID") or u.get("ID"))
            } 
            for u in api_res if isinstance(u, dict)
        ]

        # --- STEP 2: Decide whose report to show (Resolving team members) ---
        display_team = []

        if name:
            # Manager is asking for a specific person from the dynamic list
            matched = next(
                (
                    u for u in api_team
                    if name.lower() in u["name"].lower()
                    or name.lower() == u["login_code"].lower()
                ),
                None
            )
            if not matched:
                return f"User '{name}' not found in the system directory."
            display_team = [matched]

        elif ctx.deps.role == "manager":
            # Manager sees everyone currently in the API list
            display_team = api_team

        else:
            # Employee case: Identify 'self' by checking SID 609 details for each user
            self_user = None
            for u in api_team:
                detail_req = GetUsersByIdRequest(
                    Event="107018",
                    Child=[{
                        "Control_Id": "107019",
                        "AC_ID": "111271",
                        "Parent": [{"Control_Id": "106771", "Value": u["login_code"], "Data_Form_Id": ""}]
                    }]
                )
                details_res = await call_appsavy_api("GET_USERS_BY_ID", detail_req)
                u_phone = ""
                if isinstance(details_res, list) and len(details_res) > 0:
                    u_phone = str(details_res[0].get("phone") or details_res[0].get("MOBILE") or "")
                elif isinstance(details_res, dict):
                    u_phone = str(details_res.get("phone") or details_res.get("MOBILE") or "")
                
                if u_phone.endswith(ctx.deps.sender_phone[-10:]):
                    self_user = u
                    break
            
            if not self_user:
                return "Unable to identify your profile in the system directory."
            display_team = [self_user]

        status_filter = build_status_filter(ctx.deps.role)

        results = []

        for member in display_team:
            member_login = member["login_code"]
            member_name = member["name"]

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
                    f"Name- {member_name.title()}\n"
                    f"Task Assigned- Count of Task {assigned_count} Nos\n"
                    f"Task Completed- Count of task {closed_from_api} Nos\n"
                    f"Task Pending -\n"
                    f"Within time: {within_time}\n"
                    f"Beyond time: {beyond_time}"
                )

            except Exception as e:
                logger.error(
                    f"Error processing report for {member_name}",
                    exc_info=True
                )
                results.append(
                    f"Name- {member_name.title()}\n"
                    f"Error: Unable to fetch report data"
                )

        if not results:
            return "No team members found for reporting."

        return "\n\n".join(results)

    except Exception as e:
        logger.error("get_performance_report_tool error", exc_info=True)
        return f"Error generating performance report: {str(e)}"

async def get_dynamic_team_list() -> List[Dict[str, str]]:
    """Fetches the most current team list from the Appsavy API (SID 606)."""
    try:
        req = GetAssigneeRequest(Event="0", Child=[{"Control_Id": "106771", "AC_ID": "111057"}])
        api_response = await call_appsavy_api("GET_ASSIGNEE", req)
        
        result_list = []
        if isinstance(api_response, dict):
            # API returns data -> Result list
            result_list = api_response.get("data", {}).get("Result", [])
        
        return [
            {
                "name": (u.get("NAME") or u.get("name") or "Unknown"),
                "login_code": (u.get("ID") or u.get("LOGIN_ID"))
            }
            for u in result_list if isinstance(u, dict)
        ]
    except Exception as e:
        logger.error(f"Error fetching dynamic team: {e}")
    return []

async def is_sender_in_backend(phone: str) -> bool:
    """Verifies if a phone number exists in the backend by checking user details."""
    team = await get_dynamic_team_list()
    for u in team:
        detail_req = GetUsersByIdRequest(
            Child=[{"Control_Id": "107019", "AC_ID": "111271", "Parent": [{"Control_Id": "106771", "Value": u["login_code"], "Data_Form_Id": ""}]}]
        )
        details = await call_appsavy_api("GET_USERS_BY_ID", detail_req)
        u_phone = ""
        if isinstance(details, list) and len(details) > 0:
            u_phone = str(details[0].get("phone") or details[0].get("MOBILE") or "")
        elif isinstance(details, dict):
            u_phone = str(details.get("phone") or details.get("MOBILE") or "")
        
        if u_phone.endswith(phone[-10:]):
            return True
    return False

async def get_task_list_tool(ctx: RunContext[ManagerContext]) -> str:
    try:
        # Resolve the sender's login_code dynamically via API
        team = await get_dynamic_team_list()
        login_code = None
        for u in team:
            detail_req = GetUsersByIdRequest(
                Child=[{"Control_Id": "107019", "AC_ID": "111271", "Parent": [{"Control_Id": "106771", "Value": u["login_code"], "Data_Form_Id": ""}]}]
            )
            details = await call_appsavy_api("GET_USERS_BY_ID", detail_req)
            u_phone = ""
            if isinstance(details, list) and len(details) > 0:
                u_phone = str(details[0].get("phone") or details[0].get("MOBILE") or "")
            elif isinstance(details, dict):
                u_phone = str(details.get("phone") or details.get("MOBILE") or "")
            
            if u_phone.endswith(ctx.deps.sender_phone[-10:]):
                login_code = u["login_code"]
                break

        if not login_code:
            return "Unable to identify your profile in the system. Please ensure your number is registered."

        raw_tasks_data = await call_appsavy_api(
            "GET_TASKS",
            GetTasksRequest(
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
                    deadline = datetime.datetime.strptime(deadline_raw, "%m/%d/%Y %I:%M:%S %p").strftime("%d-%b-%Y %I:%M %p")
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

async def assign_new_task_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    task_name: str,
    deadline: str
) -> str:
    try:
        logger.info(f"Dynamic Assignment: Searching for user '{name}' via API...")

        # --- STEP 1: RESOLVE NAME TO LOGIN_ID ---
        list_req = GetAssigneeRequest(Event="0", Child=[{"Control_Id": "106771", "AC_ID": "111057"}])
        api_res = await call_appsavy_api("GET_ASSIGNEE", list_req)
        
        # FIX: Navigate the dictionary structure
        assignee_list = []
        if isinstance(api_res, dict):
            assignee_list = api_res.get("data", {}).get("Result", [])
        
        if not assignee_list:
            return "Error: Could not retrieve the employee list from the system."

        # Find the user in the API response
        matched_user = next(
            (u for u in assignee_list if name.lower() in (u.get("NAME") or u.get("name") or "").lower()),
            None
        )

        if not matched_user:
            return f"User '{name}' was not found in the system."

        login_code = matched_user.get("ID") or matched_user.get("LOGIN_ID")
        display_name = matched_user.get("NAME") or matched_user.get("name")

        # --- STEP 2: FETCH CONTACT DETAILS (SID 609) ---
        # We need Phone and Email for notifications, which SID 606 might not provide
        details_req = GetUsersByIdRequest(
            Event="107018",
            Child=[{
                "Control_Id": "107019",
                "AC_ID": "111271",
                "Parent": [{"Control_Id": "106771", "Value": login_code, "Data_Form_Id": ""}]
            }]
        )
        user_details_res = await call_appsavy_api("GET_USERS_BY_ID", details_req)
        
        # Extract phone and email from details response
        user_phone = None
        user_email = None
        
        if isinstance(user_details_res, list) and len(user_details_res) > 0:
            details = user_details_res[0]
            user_phone = details.get("phone") or details.get("MOBILE")
            user_email = details.get("email")
        elif isinstance(user_details_res, dict):
            user_phone = user_details_res.get("phone") or user_details_res.get("MOBILE")
            user_email = user_details_res.get("email")

        if not user_phone:
            return f"Error: User '{display_name}' found, but no phone number is registered for notifications."

        # Ensure phone format is correct (91XXXXXXXXXX)
        if len(user_phone) == 10:
            user_phone = f"91{user_phone}"

        # --- STEP 3: CREATE THE TASK (SID 604) ---
        create_req = CreateTaskRequest(
            ASSIGNEE=login_code,
            DESCRIPTION=task_name,
            TASK_NAME=task_name,
            EXPECTED_END_DATE=to_appsavy_datetime(deadline),
            MOBILE_NUMBER=user_phone[-10:],
            DETAILS=Details(
                CHILD=[DetailChild(
                    SEL="Y",
                    LOGIN=login_code,
                    PARTICIPANTS=display_name.upper()
                )]
            ),
            DOCUMENTS=Documents(CHILD=[])
        )
        
        api_response = await call_appsavy_api("CREATE_TASK", create_req)
        
        if not api_response or not (api_response.get('RESULT') == 1 or api_response.get('result') == 1):
            return f"API failure: System could not save the task for {display_name}."

        # --- STEP 4: NOTIFICATIONS ---
        phone_id = os.getenv("PHONE_NUMBER_ID")
        
        # 1. WhatsApp Template
        if phone_id:
            send_registration_template(
                recipient_number=user_phone,
                user_identifier=display_name.title(), 
                phone_number_id=phone_id
            )
            
            # 2. WhatsApp Text Details
            whatsapp_msg = (
                f"New Task Assigned:\n\n"
                f"Task: {task_name}\n"
                f"Due Date: {deadline}\n\n"
                f"Please complete on time."
            )
            send_whatsapp_message(user_phone, whatsapp_msg, phone_id)

        # 3. Email to Employee
        if user_email:
            email_body = f"Dear {display_name},\n\nYou have a new task: {task_name}\nDue: {deadline}"
            send_email(user_email, f"New Task: {task_name}", email_body)

        # 4. Confirmation to Manager
        send_email(MANAGER_EMAIL, "Task Assigned Successfully", f"Task '{task_name}' assigned to {display_name}.")

        return f"Task successfully assigned to {display_name} (ID: {login_code}). Notifications sent."

    except Exception as e:
        logger.error(f"assign_new_task_tool error: {str(e)}", exc_info=True)
        return f"System Error: {str(e)}"
    
async def assign_task_by_phone_tool(
    ctx: RunContext[ManagerContext],
    phone: str,
    task_name: str,
    deadline: str
) -> str:
    try:
        team = await get_dynamic_team_list()
        target_name = None
        
        for u in team:
            detail_req = GetUsersByIdRequest(
                Child=[{"Control_Id": "107019", "AC_ID": "111271", "Parent": [{"Control_Id": "106771", "Value": u["login_code"], "Data_Form_Id": ""}]}]
            )
            details = await call_appsavy_api("GET_USERS_BY_ID", detail_req)
            u_phone = ""
            if isinstance(details, list) and len(details) > 0:
                u_phone = str(details[0].get("phone") or details[0].get("MOBILE") or "")
            elif isinstance(details, dict):
                u_phone = str(details.get("phone") or details.get("MOBILE") or "")
            
            if u_phone.endswith(phone[-10:]):
                target_name = u["name"]
                break

        if not target_name:
            return f"Error: No employee found in the database with phone number {phone}."
        
        return await assign_new_task_tool(ctx, target_name, task_name, deadline)
    except Exception as e:
        logger.error(f"assign_task_by_phone_tool error: {str(e)}", exc_info=True)
        return f"Error assigning task by phone: {str(e)}"

async def update_task_status_tool(
    ctx: RunContext[ManagerContext], 
    task_id: str, 
    new_status: str, 
    remark: Optional[str] = None,
    file_base64: Optional[str] = "", 
    file_name: Optional[str] = ""    
) -> str:
    req = UpdateTaskRequest(
        SID="607", 
        TASK_ID=task_id,
        STATUS=new_status,
        COMMENTS=remark or f"Status updated to {new_status} via AI Assistant",
        UPLOAD_DOCUMENT=file_name, 
        BASE64=file_base64       
    )
    
    api_response = await call_appsavy_api("UPDATE_STATUS", req)
    
    if isinstance(api_response, dict) and (api_response.get('RESULT') == 1 or api_response.get('result') == 1):
        return f"Success: Task {task_id} status updated to '{new_status}'."
    
    # If API returns 401, provide a helpful error
    if isinstance(api_response, dict) and api_response.get('status') == 401:
        return "Error: System Authorization failed (401). Please check the API TokenKey."
        
    return f"Failed to update task: {api_response}"
    
async def handle_message(command, sender, pid, message=None, full_message=None):
    try:
        # Normalize sender phone number
        if len(sender) == 10 and not sender.startswith('91'):
            sender = f"91{sender}"
    
        # Detect if the message contains media (document, image, etc.)
        is_media = False
        if message:
            is_media = any(k in message for k in ["document", "image", "video", "audio", "type"])
    
        # Case: File received without any text instructions
        if is_media and not command:
            send_whatsapp_message(
                sender, 
                "File received. Please provide the assignee name, task description, and deadline to complete the assignment.", 
                pid
            )
            return
    
        # Authentication Logic
        manager_phone = os.getenv("MANAGER_PHONE", "917428134319")
    
        if sender == manager_phone:
            role = "manager"
        elif await is_sender_in_backend(sender): 
            role = "employee"
        else:
            role = None
    
        # Authorization Check
        if not role:
            send_whatsapp_message(sender, "Access Denied: Your number is not authorized in the database.", pid)
            return
    
        # Initialize conversation history for new users
        if sender not in conversation_history:
            conversation_history[sender] = []
    
        # Process the command (Text or Media + Text)
        if command or is_media:
            try:
                # --- NEW: MEDIA PROCESSING LOGIC ---
                # If a file is attached, download it and convert to Base64 so Gemini can use it
                if is_media:
                    media_data = message.get("document") or message.get("image") or message.get("video")
                    if media_data:
                        file_base64 = download_and_encode_document(media_data)
                        file_name = media_data.get("filename") or f"file_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
                        
                        # Inject file context into the command string for Gemini's situational awareness
                        command = f"{command if command else ''} [ATTACHED_FILE_NAME: {file_name}] [ATTACHED_BASE64: {file_base64}]".strip()

                # Resolve team dynamically for multi-assignee extraction (Manager Shortcut)
                team = await get_dynamic_team_list()
                assignees = extract_multiple_assignees(command, team)

                # Handle Manager assigning one task to multiple people simultaneously
                if role == "manager" and len(assignees) > 1:
                    for name in assignees:
                        await assign_new_task_tool(
                            ctx=ManagerContext(sender_phone=sender, role=role, current_time=datetime.datetime.now()),
                            name=name, 
                            task_name=command, 
                            deadline=datetime.datetime.now().strftime("%Y-%m-%d")
                        )
                    send_whatsapp_message(sender, f"Task successfully assigned to:\n" + "\n".join(assignees), pid)
                    return

                # Regular AI Agent Flow
                current_time = datetime.datetime.now()
                dynamic_prompt = await get_system_prompt(current_time)
            
                current_agent = Agent(ai_model, deps_type=ManagerContext, system_prompt=dynamic_prompt)
                
                # Register all available tools to the agent
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

                # Run the AI Agent with current context
                result = await current_agent.run(
                    command,
                    message_history=conversation_history[sender],
                    deps=ManagerContext(sender_phone=sender, role=role, current_time=current_time)
                )
            
                # Update conversation history and maintain limit
                conversation_history[sender] = result.all_messages()
                if len(conversation_history[sender]) > 10:
                    conversation_history[sender] = conversation_history[sender][-10:]
            
                # Send the AI's response back to the user on WhatsApp
                send_whatsapp_message(sender, result.output, pid)

            except Exception as e:
                logger.error(f"Agent execution failed: {str(e)}", exc_info=True)
                send_whatsapp_message(sender, "System Error: Unable to process request. Please try again.", pid)
                
    except Exception as e:
        logger.error(f"handle_message error: {str(e)}", exc_info=True)
        send_whatsapp_message(sender, "An unexpected error occurred. Please try again.", pid)