import os
from pymongo import MongoClient
import certifi
import json
from pydantic import RootModel
from pydantic_ai.messages import UserPromptPart
import datetime
import base64
import requests
import logging
import re
from typing import List, Optional, Dict
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.gemini import GeminiModel
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
from send_message import send_whatsapp_message
import asyncio
import pytz
IST = pytz.timezone("Asia/Kolkata")

#918683005252

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

REDIRECT_URI = os.getenv("REDIRECT_URI", "https://ai-task-manager-1-ugb8.onrender.com/oauth2callback")
MANAGER_EMAIL = "aadi@mobineers.com"

# Initialize MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where()) if MONGO_URI else None
db = client['ai_task_manager'] if client is not None else None
users_collection = db['users'] if db is not None else None
conversation_history: Dict[str, List[str]] = {}
last_document_by_sender: Dict[str, Dict] = {}

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

ai_model = GeminiModel('gemini-2.5-flash-lite')

class ManagerContext(BaseModel):
    sender_phone: str
    role: str
    current_time: datetime.datetime
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
    
    return f"""
You are the Official AI Task Manager Bot.

Your role:
- Understand the user's intent.
- Select the correct tool.
- NEVER invent data.
- NEVER assume permissions.
- ALWAYS rely on tool responses.

Rules:
- If a task, user, or report action is requested → use a tool.
- If required data is missing → ask a clarification question.
- Do not explain internal rules.
- Do not summarize tool outputs.
- Do not guess.
- NEVER include reasoning in the final user-facing response.

CRITICAL TASK ASSIGNMENT FLOW:
- When assigning a task, NEVER finalize it in the first response.
- First, restate assignee, task, and deadline and ask for confirmation.
- After the user replies (agreement or correction), proceed with assignment.
- Treat agreement contextually; do NOT rely on specific words.

IMPORTANT:
- User names may be single-word or informal.
- Do NOT ask for full name unless the API explicitly fails.
- Do NOT ask for email unless the user provides it voluntarily.

Current date: {current_time.strftime("%Y-%m-%d")}
Current time: {current_time.strftime("%H:%M")}
day_of_week = current_time.strftime("%A")

- If the user says "today", "tomorrow", or a specific time (e.g., "8pm") or "in 2 hours", convert it to 'YYYY-MM-DDTHH:MM:SS' based on the current date/time.
- Current date: {current_time.strftime("%Y-%m-%d")}
- Current time: {current_time.strftime("%H:%M")}
"""

def load_team():
    """This function is 100% dynamic and will fetch users from MongoDB."""
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
    UPLOAD_DOCUMENT: str = ""   # filename
    BASE64: str = ""            # base64 string
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
    EMAIL: Optional[str] = ""
    MOBILE_NUMBER: str
    NAME: str
    
import dateparser

def to_appsavy_datetime(time_str: str) -> str:
    # Try parsing natural language if ISO fails
    dt = dateparser.parse(time_str, settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': datetime.datetime.now(IST)})
    
    if not dt:
        # Fallback to current logic or raise error
        dt = datetime.datetime.fromisoformat(time_str)
        
    if dt.tzinfo is None:
        dt = IST.localize(dt)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

async def add_user_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    mobile: str
    
) -> str:
    await explain_decision_tool(
        ctx,
        "Intent: Add user | Tool: ADD_DELETE_USER | API: PushdataJSONClient (SID 629)"
    )
    """
ROLE:
You create a new user.

REQUIRED FIELDS:
- Name
- 10-digit mobile number
- Email (optional)

FLOW:
1. Call ADD_DELETE_USER (ACTION=Add)
2. Extract login ID
3. Sync user to MongoDB

YOU MUST NOT:
- Ask follow-up if data is complete
- Guess login ID
- Modify mobile number format incorrectly

OUTPUT:
- Agent-internal confirmation string (not always sent to user)
- Or failure reason
"""


    # 1. Attempt to add the user to Appsavy
    req = AddDeleteUserRequest(
        ACTION="Add",
        CREATOR_MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
        NAME=name,
        EMAIL= "",
        MOBILE_NUMBER=mobile[-10:]
    )

    res = await call_appsavy_api("ADD_DELETE_USER", req)
    if not isinstance(res, dict): return f"Failed to add user: {res}"
    
    msg = res.get("resultmessage", "")
    login_code = None

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
                "phone": normalize_phone(mobile),
                "email": "",
                "login_code": login_code
            }
            
            if users_collection is not None:
                users_collection.update_one(
                    {"phone": new_user["phone"]},
                    {"$set": new_user},
                    upsert=True
                )
                logger.info(f"Successfully synced {name} to MongoDB with ID {login_code}")
                
                return 
    return "failed"

async def explain_decision_tool(
    ctx: RunContext[ManagerContext],
    reason: str
) -> None:
    logger.info(
        f"[AI-DECISION]"
        f" User={ctx.deps.sender_phone}"
        f" Role={ctx.deps.role}"
        f" Reason={reason}"
    )

async def delete_user_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    mobile: str,
    email: Optional[str] = None,
    
) -> str:
    """
ROLE:
You delete an existing user.

ABSOLUTE RULE:
- Only the creator of the user can delete them

MANDATORY CHECK:
- requester mobile == creator mobile

IF CHECK FAILS:
- Deny deletion immediately

NEVER:
- Allow manager override
- Assume ownership
- Delete without verification

OUTPUT:
- Success or permission denied
"""
    
    req = AddDeleteUserRequest(
        ACTION="Delete",
        CREATOR_MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
        NAME=name,
        EMAIL=email or "",
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

        return
    return 

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
    if dt.tzinfo is None:
        dt = IST.localize(dt)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def normalize_tasks_response(tasks_data):
    """Normalize Appsavy GET_TASKS response to always return a list"""
    if not isinstance(tasks_data, dict):
        return []

    data = tasks_data.get("data")

    if not isinstance(data, dict):
        return []

    return data.get("Result", [])

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
            user = next((u for u in team if u["phone"] == normalize_phone(ctx.deps.sender_phone)), None)

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

        return

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
        "DELAYED_OPEN_TASK": 0, 
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
    """
    PURPOSE:
    - Provide performance statistics, task counts, or report files.

    WHEN TO USE:
    - User asks for "performance", "stats", "count", or "report".

    LOGIC:
    1. IF NO NAME IS MENTIONED:
       - Treat as a request for a full organization PDF report.
       - ONLY allowed for 'manager' role.
    2. IF A NAME/ID IS MENTIONED:
       - Fetch specific counts for that employee.
       - Use 'get_task_summary_from_tasks' internally.
    
    RULES:
    - Employees can ONLY see their own performance.
    - Managers can see anyone's performance.
    """
    
    team = load_team()
    
    if not name:
        if ctx.deps.role != "manager":
            return "Permission Denied: Only managers can view full performance reports."
        
        await call_appsavy_api(
            "WHATSAPP_PDF_REPORT",
            WhatsAppPdfReportRequest(
                ASSIGNED_TO="",
                REPORT_TYPE="Detail",
                STATUS="",
                MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
                REFERENCE="WHATSAPP"
            )
        )

        return 

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

    return

async def get_task_list_tool(ctx: RunContext[ManagerContext]) -> str:
    """
    PURPOSE:
    - Retrieve a list of active or pending tasks.

    WHEN TO USE:
    - User asks: "show my tasks", "what is my pending work?", "list tasks", or "to-do list".

    RULES:
    - Without a name: Show tasks for the requesting user (caller).
    - With a name: Only allowed if the caller is a 'manager'.
    - Output format: Return the ID, Task Name, and Deadline clearly.
    - Do NOT summarize or omit tasks returned by the system.
    """

    try:
        team = load_team()
        user = next((u for u in team if u["phone"] == normalize_phone(ctx.deps.sender_phone)), None)

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
                        {"Control_Id": "106825", "Value": "Open,Work In Progress,Close", "Data_Form_Id": ""},  # or leave empty or "Open"
                        {"Control_Id": "106824", "Value": "", "Data_Form_Id": ""},           # from date
                        {"Control_Id": "106827", "Value": login_code, "Data_Form_Id": ""},   # ← ensure this is correct D-... or whatever Appsavy uses
                        {"Control_Id": "106829", "Value": "", "Data_Form_Id": ""},           # to date
                        {"Control_Id": "107046", "Value": "", "Data_Form_Id": ""},           # assignment type
                        {"Control_Id": "107809", "Value": "0", "Data_Form_Id": ""},          # button label / flag
                        {"Control_Id": "146515", "Value": ctx.deps.sender_phone[-10:], "Data_Form_Id": ""}  # ← ADD THIS LINE – critical for WhatsApp context
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
                f"Deadline: {deadline}\n\n"
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
PURPOSE:
- Assign a new task to a user or group.

WHEN TO ACT:
- User wants to assign, give, create, or delegate a task.

REQUIRED INPUT:
- Assignee (name, login code, or phone)
- Task description
- Deadline (Format: 'YYYY-MM-DDTHH:MM:SS'. You must convert relative times like '8pm today' or "day fater tomorrow" or "in 5 hours" to this format yourself using the current time context).


RULES:
- Resolve assignee using MongoDB + Appsavy.
- If multiple matches → ask clarification.
- If document exists → attach automatically.
- NEVER assign without a deadline.
- BEFORE FINAL ALLOTMENT OF THE TASK ALWAYS CONFIRM FROM THE USER 

CRITICAL TASK ASSIGNMENT RULE:
- Before calling assign_new_task_tool, you MUST explicitly confirm:
  1. Assignee
  2. Task description
  3. Deadline
- If confirmation has NOT been explicitly given by the user,
  DO NOT finalize task assignment.
- In that case, ask the user to confirm the details instead of assigning.

OUTPUT:
- Single confirmation or single error message
"""
    try:
        # 1. MERGE SOURCES: Fetch candidates from BOTH MongoDB and Appsavy (SID 606)
        team = load_team()
        mongo_matches = [u for u in team if name.lower() in u["name"].lower() or name.lower() == u["login_code"].lower()]
        
        last_messages = conversation_history.get(ctx.deps.sender_phone, [])
        if len(last_messages) < 2:
            return (
                "Please confirm the task details before I proceed:\n\n"
                f"Assignee: {name}\n"
                f"Task: {task_name}\n"
                f"Deadline: {deadline}\n\n"
                "Reply with CONFIRM to proceed, or reply with corrections."
            )
            
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
                        f"task_image_{datetime.datetime.now(IST).strftime('%Y%m%d_%H%M%S')}.png" 
                        if media_type == "image" else "task_document.pdf"
                    )
                    documents_child.append(DocumentItem(
                        DOCUMENT=DocumentInfo(VALUE=fname, BASE64=base64_data),
                        DOCUMENT_NAME=fname
                    ))

        req = CreateTaskRequest(
            ASSIGNEE=login_code,   
            DESCRIPTION=task_name,
            TASK_NAME=task_name,
            EXPECTED_END_DATE=to_appsavy_datetime(deadline),
            MOBILE_NUMBER=ctx.deps.sender_phone[-10:],
            DETAILS=Details(
                CHILD=[]
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
                last_document_by_sender.pop(ctx.deps.sender_phone, None)
                return f"Task successfully assigned to {user['name'].title()} (ID: {login_code})."

        return f"API Error: {api_response.get('resultmessage', 'Unexpected response format')}"
        
    except Exception as e:
        logger.error(f"assign_new_task_tool error: {str(e)}", exc_info=True)
        return f"System Error: Unable to assign task ({str(e)})"

def parse_relative_deadline(text: str, now: datetime.datetime) -> Optional[str]:
    text = text.lower()

    match = re.search(r"in\s+(\d+)\s*(hour|hours|hr|hrs)", text)
    if match:
        hours = int(match.group(1))
        dt = now + datetime.timedelta(hours=hours)
        return dt.isoformat()

    match = re.search(r"in\s+(\d+)\s*(minute|minutes|min|mins)", text)
    if match:
        mins = int(match.group(1))
        dt = now + datetime.timedelta(minutes=mins)
        return dt.isoformat()

    return None

async def assign_task_by_phone_tool(
    ctx: RunContext[ManagerContext],
    phone: str,
    task_name: str,
    deadline: str
) -> str:
    
    try:
        team = load_team()
        normalized_phone = normalize_phone(phone)
        
        user = next(
            (
                u for u in team
                if normalize_phone(u.get("phone", "")) == normalized_phone
            ),
            None
        )

        if not user:
            return f"Error: No employee found with phone number {phone}."

        login_code = user["login_code"]

        if users_collection is not None:
            users_collection.update_one(
                {"login_code": login_code},
                {"$set": {
                    "name": user["name"].lower(),
                    "phone": normalized_phone,
                    "login_code": login_code
                }},
                upsert=True
            )
            
        return await assign_new_task_tool(
            ctx,
            user["name"],
            task_name,
            deadline
        )

    except Exception as e:
        logger.error(
            f"assign_task_by_phone_tool error: {str(e)}",
            exc_info=True
        )
        return f"Error assigning task by phone: {str(e)}"

APPSAVY_STATUS_MAP = {
    "Open": "Open",
    "Work In Progress": "Work In Progress",
    "Close": "Closed",
    "Closed": "Closed",
    "Reopened": "Reopen"
}

async def update_task_status_tool(
    ctx: RunContext[ManagerContext],
    task_id: str,
    status: str,
    remark: Optional[str] = None
) -> str:
    """
    PURPOSE:
    - Update the status of an existing task.

    WHEN TO USE:
    - User wants to mark a task as done, closed, reopened, or in progress.

    AUTHORIZATION RULES:
    - Only task owner (assignee or reporter) can update.
    - Never ask user if h is assignee or reporter, that is already handled by sid 632, i.e CHECK_OWNERSHIP API
    - Employees CAN use status "Closed".
    - Managers CANNOT use status "Work In Progress".
    - Map intent → status
    - Call UPDATE_STATUS API
    - Do Attach document if given by the user

    STATUS INTERPRETATION:
    - Employee phrases like "done", "completed","close" → Closed
    - Manager phrases like "approved", "final close","close" → Closed
    - Manager phrases like "redo", "not ok" → Reopened
    - Employee phrases like "in progress", "pending"-> Work in Progress
   
    HARD RULES:
    - NEVER ask questions.
    - NEVER invent task IDs.
    - NEVER bypass ownership check.
    - ALWAYS call CHECK_OWNERSHIP first.

    OUTPUT:
    - Return ONLY user-facing confirmation text."""

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

    # ---- STATUS MAPPING ----
    appsavy_status = APPSAVY_STATUS_MAP.get(status)
    if not appsavy_status:
        return f"Unsupported status '{status}'."

    # ---- DOCUMENT HANDLING (WHATSAPP ATTACHMENT) ----
    filename = ""
    base64_data = ""

    if ctx.deps.document_data:
        media_type = ctx.deps.document_data.get("type")
        media_info = ctx.deps.document_data.get(media_type)

        if media_info:
            logger.info(f"Downloading document for task update: {media_type}")
            base64_data = download_and_encode_document(media_info)
            mime = media_info.get("mime_type", "")
            if not media_info.get("filename"):
                if "pdf" in mime:
                    filename = "attachment.pdf"
                elif "image" in mime:
                    filename = "image.jpg"
                elif "audio" in mime:
                    filename = "audio.mp3"
                else:
                    filename = "attachment.bin"
            else:
                filename = media_info["filename"]

    req = UpdateTaskRequest(
        TASK_ID=task_id,
        STATUS=appsavy_status,
        COMMENTS=remark or "Updated via WhatsApp",
        UPLOAD_DOCUMENT=filename,
        BASE64=base64_data,
        WHATSAPP_MOBILE_NUMBER=sender_mobile
    )

    api_response = await call_appsavy_api("UPDATE_STATUS", req)

    if api_response and str(api_response.get("RESULT")) == "1":
        last_document_by_sender.pop(ctx.deps.sender_phone, None)
        if status == "Close":
            return f"Task {task_id} closed"
        if status == "Closed":
            return f"Task {task_id} closed."
        if status == "Reopened":
            return f"Task {task_id} reopened."
        return f"Task {task_id} updated."

    return f"API Error: {api_response.get('resultmessage', 'Update failed')}"

def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return "91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits

async def handle_message(command, sender, pid, message=None, full_message=None):
    # ---- Quick command shortcut ----
    if command and command.strip().lower() == "delete & add":
        send_whatsapp_message(
            sender,
            "Please resend user details in this format:\n\n"
            "Add user\nName\nMobile\nEmail",
            pid
        )
        return

    try:
        sender = normalize_phone(sender)

        # ---- Media detection ----
        is_media = False
        if message:
            is_media = any(k in message for k in ["document", "image", "video", "audio", "type"])

        if is_media:
            last_document_by_sender[sender] = message

        if is_media and not command:
            send_whatsapp_message(
                sender,
                "File received. Please provide the assignee name, task description, and deadline.",
                pid
            )
            return

        # ---- Role resolution ----
        manager_phone = normalize_phone(os.getenv("MANAGER_PHONE"))
        team = load_team()

        if sender == manager_phone:
            role = "manager"
        elif any(normalize_phone(u["phone"]) == sender for u in team):
            role = "employee"
        else:
            role = None

        if not role:
            send_whatsapp_message(
                sender,
                "Access Denied: Your number is not authorized to use this system.",
                pid
            )
            return

        # ---- Conversation memory ----
        if sender not in conversation_history:
            conversation_history[sender] = []

        if command:
            conversation_history[sender].append(command)
            conversation_history[sender] = conversation_history[sender][-5:]

        # ---- Multi-assignee fast path ----
        if command:
            assignees = extract_multiple_assignees(command, team)
            if len(assignees) > 1:
                send_whatsapp_message(
                    sender,
                    "I found multiple assignees. Please confirm:\n\n"
                    + "\n".join(assignees)
                    + "\n\nAlso confirm the task details and deadline.",
                    pid
                )
                return

        # ---- Agent setup ----
        current_time = datetime.datetime.now(IST)
        dynamic_prompt = get_system_prompt(current_time)

        agent = Agent(
            ai_model,
            deps_type=ManagerContext,
            system_prompt=dynamic_prompt
        )

        # ---- Register tools ----
        agent.tool(get_performance_report_tool)
        agent.tool(get_task_list_tool)
        agent.tool(assign_new_task_tool)
        agent.tool(assign_task_by_phone_tool)
        agent.tool(update_task_status_tool)
        agent.tool(get_assignee_list_tool)
        agent.tool(get_users_by_id_tool)
        agent.tool(send_whatsapp_report_tool)
        agent.tool(add_user_tool)
        agent.tool(delete_user_tool)
        agent.tool(explain_decision_tool)

        # ---- Build context window (SAFE + DETERMINISTIC) ----
        messages = [command]
        if command.strip().lower() in {"confirm", "yes", "okay", "proceed"}:
            messages = conversation_history[sender]
        else:
            messages = [command]


        relative_deadline = parse_relative_deadline(command, current_time)
        if relative_deadline:
            messages.append(
                f"System note: Deadline resolved as {relative_deadline}"
            )

        # ---- Run agent (guard against Gemini empty output) ----
        called_tools = []
        try:
            result = await agent.run(
                messages,
                deps=ManagerContext(
                    sender_phone=sender,
                    role=role,
                    current_time=current_time,
                    document_data=last_document_by_sender.get(sender)
                )
                called_tools = []
            )
            for msg in result.all_messages():
                    if hasattr(msg, "tool_name") and msg.tool_name:
                        called_tools.append(msg.tool_name)
                        
        except Exception as e:
            logger.error("Agent execution failed", exc_info=True)
            return

        output_text = (result.output or "").strip()
        if not output_text:
            output_text = (
                "I couldn’t identify a task, update, or request in that message. "
                "Please clarify what you want me to do."
            )

        # ---- Send WhatsApp response ----
        send_whatsapp_message(sender, output_text, pid)

    except Exception as e:
        logger.error(f"handle_message error: {str(e)}", exc_info=True)
        send_whatsapp_message(
            sender,
            "A system error occurred. Please try again shortly.",
            pid
        )
