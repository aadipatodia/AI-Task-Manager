import os
from pymongo import MongoClient
import certifi
import json
import datetime
import base64
from google.genai import Client
import requests
import logging
import re
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from send_message import send_whatsapp_message
from redis_session import (
    get_or_create_session,
    append_message,
    set_pending_document,
    get_pending_document,
    get_session_history,
    end_session_complete
)
from intent_classifier import intent_classifier
from user_resolver import resolve_user_by_phone
import asyncio 
from datetime import timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

REDIRECT_URI = os.getenv("REDIRECT_URI", "https://aitask.appsavy.com/")

# Initialize MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where()) if MONGO_URI else None
db = client['ai_task_manager'] if client is not None else None
users_collection = db['users'] if db is not None else None

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
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient", 
        "headers": {
            "sid": "675",
            "pid": "309",
            "fid": "13638",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "2c96a4d5-7254-4b43-a48f-160ba1e4e542", # Updated from documentation
            "Content-Type": "application/json"
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

    "GET_USERS_BY_WHATSAPP": {
        "url": f"{APPSAVY_BASE_URL}/PushdataJSONClient",
        "headers": {
            "sid": "669",
            "pid": "309",
            "fid": "13618",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "28036aa2-722f-46a4-a157-3cda45b3461d",
            "Content-Type": "application/json"
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

class ManagerContext(BaseModel):
    sender_phone: str
    role: str
    current_time: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(IST)
    )
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
    
class GetUserTasksRequest(BaseModel):
    SID: str = "675"
    EMPLOYEE: str
    WHATSAPP_MOBILE_NUMBER: str
    ASSIGNMENT: str = ""
    FROM_DATE: str = ""
    TO_DATE: str = ""
    STATUS: str = ""

class PerformanceCountResult(BaseModel):
    ASSIGNED_TASK: int = 0
    OPEN_TASK: int = 0
    DELAYED_OPEN_TASK: int = 0
    CLOSED_TASK: int = 0
    DELAYED_CLOSED_TASK: int = 0

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

class GetUsersByWhatsappRequest(BaseModel):
    SID: str = "669"
    WHATSAPP_MOBILE_NUMBER: str

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
    UPLOAD_DOCUMENT: UploadDocument = Field(default_factory=UploadDocument) # Changed from str to UploadDocument
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
    
async def run_gemini_extractor(prompt: str, message: str):
    client = Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=f"{prompt}\n\nUSER MESSAGE:\n{message}"
    )

    text = response.text.strip()
    log_reasoning("AGENT_2_OUTPUT", text)
    # If Gemini returns JSON → parse
    if text.startswith("{"):
        return json.loads(text)

    # Otherwise → treat as user-facing follow-up question
    return text

def AGENT_2_POLICY(current_time: datetime.datetime) -> str:
    team = load_team()
    team_description = "\n".join(
        [f"- {u['name']} (Login: {u['login_code']})" for u in team]
    )

    current_date_str = current_time.strftime("%Y-%m-%d")
    current_time_str = current_time.strftime("%I:%M %p")
    day_of_week = current_time.strftime("%A")

    return f"""
AUTHORIZED TEAM MEMBERS:
{team_description}

You are the Official AI Task Manager Assistant for the organization.
Identity: TM_API.

Current Date: {current_date_str} ({day_of_week})
Current Time: {current_time_str}

GENERAL OPERATING PRINCIPLES:
1. Understand user intent from natural language.
2. Use conversation context when relevant.
3. Never invent missing information.
4. Ask clear, minimal follow-up questions when required.
5. Stay strictly within the scope of task management.

COMMUNICATION STYLE:
- Professional and concise
- No emojis
- No casual language
- No internal system or tool names
- Respond only with what is required to move the task forward

IMPORTANT:
- Ignore WhatsApp metadata such as timestamps or sender headers.
- Focus only on the actual user message content.
"""

def load_team():
    """Ab ye function 100% dynamic hai, sirf MongoDB se users fetch karega."""
    if users_collection is None:
        logger.error("MongoDB connection cant be initialized")
        return []

    try:
        db_users = list(users_collection.find({}, {"_id": 0}))
        
        logger.info(f"Successfully loaded {len(db_users)} users from MongoDB.")
        return db_users
        
    except Exception as e:
        logger.error(f"Failed to fetch users from MongoDB: {e}")
        return []

async def add_user_tool(
    ctx: ManagerContext,
    name: str,
    mobile: str,
    email: Optional[str] = None
) -> str:
   
    log_reasoning("ADD_USER_START", {
        "name": name,
        "mobile": mobile,
        "email": email,
        "requested_by": ctx.sender_phone
    })
    
    req = AddDeleteUserRequest(
        ACTION="Add",
        CREATOR_MOBILE_NUMBER=ctx.sender_phone[-10:],
        NAME=name,
        EMAIL=email or "",
        MOBILE_NUMBER=mobile[-10:]
    )

    res = await call_appsavy_api("ADD_DELETE_USER", req)
    if not isinstance(res, dict):
        return f"Failed to add user: {res}"
    
    msg = res.get("resultmessage", "")
    login_code = None

    is_success = str(res.get("result")) == "1" or str(res.get("RESULT")) == "1"
    is_existing = "already exists" in msg.lower()

    if is_success or is_existing:
        match = re.search(r"login Code:\s*([A-Z0-9-]+)", msg, re.IGNORECASE)
        login_code = match.group(1) if match else None
        
        if not login_code:
            logger.info(f"ID missing from message. Fetching list to find: '{name}'")
            assignee_res = await call_appsavy_api(
                "GET_ASSIGNEE",
                GetAssigneeRequest(
                    Event="0",
                    Child=[{"Control_Id": "106771", "AC_ID": "111057"}]
                )
            )
            
            result_list = []
            if isinstance(assignee_res, dict):
                result_list = assignee_res.get("data", {}).get("Result", [])
            elif isinstance(assignee_res, list):
                result_list = assignee_res

            target_name = name.lower().strip()
            for item in result_list:
                item_name = str(item.get("NAME", "")).lower().strip()
                if re.fullmatch(rf"{re.escape(target_name)}", item_name):
                    login_code = item.get("ID") or item.get("LOGIN_ID")
                    break

        if login_code:
            new_user = {
                "name": name.lower().strip(),
                "phone": normalize_phone(mobile),
                "email": email or None,
                "login_code": login_code
            }
            
            if users_collection is not None:
                users_collection.update_one(
                    {"phone": new_user["phone"]},
                    {"$set": new_user},
                    upsert=True
                )

            logger.info(f"Successfully synced {name} to MongoDB with ID {login_code}")
            return None
    return None

async def delete_user_tool(
    ctx: ManagerContext,
    name: str,
    mobile: str,
    email: Optional[str] = None
) -> None:

    req = AddDeleteUserRequest(
        ACTION="Delete",
        CREATOR_MOBILE_NUMBER=ctx.sender_phone[-10:],
        NAME=name,
        EMAIL=email or "",
        MOBILE_NUMBER=mobile[-10:]
    )

    res = await call_appsavy_api("ADD_DELETE_USER", req)

    if not isinstance(res, dict):
        return None

    msg = res.get("resultmessage", "").lower()

    # Permission / ownership failure
    if "permission denied" in msg:
        return None

    # Successful deletion
    if str(res.get("result")) == "1" or str(res.get("RESULT")) == "1":
        if users_collection is not None:
            users_collection.delete_one({"phone": "91" + mobile[-10:]})
            logger.info(
                f"User with mobile {mobile[-10:]} removed from MongoDB."
            )
        return None

    return None

def log_reasoning(step: str, details: dict | str):
    logger.info(
        "[GEMINI_REASONING] %s | %s",
        step,
        json.dumps(details, ensure_ascii=False) if isinstance(details, dict) else details
    )
    
async def get_duplicate_resolution_message(matches: list, assignee_name: str) -> str:
    """
    Fetches full user details from MongoDB for duplicates and formats the WhatsApp response.
    """
    options_text = ""
    
    for i, candidate in enumerate(matches, 1):
        login_code = candidate.get("login_code")
        
        # Search Mongo for the authoritative record
        user_record = users_collection.find_one({"login_code": login_code})
        
        if user_record:
            name = user_record.get("name", candidate.get("name", "Unknown")).upper()
            phone = user_record.get("phone", "N/A")
            email = user_record.get("email", "N/A")
            options_text += f"{i}. *{name}*\n    {phone}\n    {email}\n\n"
        else:
            # Fallback if Appsavy has a user that isn't in your Mongo yet
            options_text += f"{i}. *{candidate['name'].upper()}*\n   (Details not found in DB)\n\n"

    return (
        f"I found multiple employees named '{assignee_name}'. Which one do you mean?\n\n"
        f"{options_text}"
        "Please reply with the correct *Mobile Number* to proceed."
    )

def normalize_status_for_report(status: str) -> str:
    report_status_map = {
        "open": "Open",
        "pending": "Open",
        "partial": "Partially Closed",
        "in progress": "Partially Closed",
        "reported": "Closed",
        "completed": "Closed",
        "done": "Closed",
        "closed": "Closed"
    }

    return report_status_map.get(status.lower(), status)

def to_appsavy_datetime(iso_dt: str) -> str:
    dt = datetime.datetime.fromisoformat(iso_dt)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

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
    if task_owner is None:
        return False
    return str(task_owner).strip() != "0"

async def call_appsavy_api(key: str, payload: BaseModel) -> Optional[Dict]:
    """Universal wrapper for Appsavy POST requests - 100% API dependency."""
    config = API_CONFIGS[key]
    try:
        logger.info(f"Calling API {key} with payload: {payload.model_dump()}")
        
        log_reasoning("API_CALL_DECISION", {
            "api_key": key,
            "trigger": "Gemini tool execution",
            "payload_type": payload.__class__.__name__
        })
        
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

async def send_whatsapp_report_tool(
    ctx: ManagerContext,
    report_type: str,
    status: str,
    assigned_to: Optional[str] = None
) -> None:
    
    try:
        team = load_team()

        # Resolve target user
        if assigned_to:
            user = next(
                (u for u in team if assigned_to == u["login_code"]),
                None
            )
            if not user:
                return None
        else:
            user = next(
                (u for u in team if u["phone"] == normalize_phone(ctx.sender_phone)),
                None
            )

        if not user:
            return None

        req = WhatsAppPdfReportRequest(
            ASSIGNED_TO=user["login_code"],
            REPORT_TYPE=report_type,
            STATUS=normalize_status_for_report(status),
            MOBILE_NUMBER=user["phone"][-10:],
            ASSIGNED_BY="",
            REFERENCE="WHATSAPP"
        )
        await call_appsavy_api("WHATSAPP_PDF_REPORT", req)
        # Silent success
        return None
    except Exception:
        logger.error("send_whatsapp_report_tool error", exc_info=True)
        return None

async def get_pending_tasks(login_code: str) -> List[str]:

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
    ctx: ManagerContext,
    report_type: str,  # Now passed from Gemini's extracted JSON
    name: Optional[str] = None
) -> None:
    try:
        team = load_team()

        # Resolve target login_code if a name is provided
        target_login = ""
        if name:
            name_l = name.lower()
            user = next(
                (u for u in team if name_l == u["login_code"].lower() or name_l in u["name"].lower()),
                None
            )
            if not user:
                logger.error(f"User {name} not found for performance report.")
                return None
            target_login = user["login_code"]


        # Safety check: Only managers can request 'Detail' reports
        final_report_type = report_type
        if final_report_type == "Detail" and ctx.role != "manager":
            logger.warning("Unauthorized Detail report request blocked.")
            return None

        req = WhatsAppPdfReportRequest(
            ASSIGNED_TO=target_login,
            REPORT_TYPE=final_report_type, # Uses value extracted by Gemini
            STATUS="",
            MOBILE_NUMBER=ctx.sender_phone[-10:],
            ASSIGNED_BY="",
            REFERENCE="WHATSAPP"
        )

        await call_appsavy_api("WHATSAPP_PDF_REPORT", req)
        return None

    except Exception:
        logger.error("get_performance_report_tool failed", exc_info=True)
        return None

async def get_task_list_tool(
    ctx: ManagerContext,
    view: str = "tasks"   
) -> None:
    sender_mobile = ctx.sender_phone[-10:]

    # Handle the users list view
    if view == "users":
        req = GetUsersByWhatsappRequest(WHATSAPP_MOBILE_NUMBER=sender_mobile)
        await call_appsavy_api("GET_USERS_BY_WHATSAPP", req)
        return None

    # Identify the user from MongoDB to get their unique login_code
    team = load_team() 
    user = next(
        (u for u in team if u["phone"] == normalize_phone(ctx.sender_phone)),
        None
    )  
    
    if not user:
        logger.error(f"User not found in system for phone: {ctx.sender_phone}")
        return None

    # Construct request as per 'get user task list.txt' documentation
    req = GetUserTasksRequest(
        SID="675",
        EMPLOYEE=user["login_code"],
        WHATSAPP_MOBILE_NUMBER=sender_mobile,
        ASSIGNMENT="",
        STATUS=""
    )
    
    await call_appsavy_api("GET_TASKS", req)
    return None

def extract_multiple_assignees(text: str, team: list) -> list[str]:
    text = text.lower()
    found = []

    for member in team:
        name = member["name"].lower()
        # enforce word boundary match
        if re.search(rf"\b{name}\b", text):
            found.append(member["name"])

    return list(set(found))

async def get_task_description(task_id: str) -> str:

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
    ctx: ManagerContext,
    assignee: str,          # name OR phone
    task_name: str,
    deadline: str
) -> Optional[str]:
    try:
        team = load_team()  # This already loads from MongoDB
        assignee_raw = assignee.strip()

        log_reasoning("ASSIGN_TASK_START", {
            "assignee": assignee_raw,
            "task": task_name,
            "deadline": deadline,
            "sender": ctx.sender_phone
        })

        digits = re.sub(r"\D", "", assignee_raw)
        is_phone = len(digits) in (10, 12)

        matches: list[dict] = []

        if is_phone:
            normalized_phone = normalize_phone(digits)
            resolved_user = next(
                (u for u in team if normalize_phone(u.get("phone", "")) == normalized_phone),
                None
            )
            if not resolved_user:
                return None
            matches = [resolved_user]
        else:
            # DIRECT MONGO SEARCH: No Appsavy API call here
            name_l = assignee_raw.lower()
            matches = [
                u for u in team 
                if re.search(rf"\b{re.escape(name_l)}\b", u["name"].lower())
            ]

        log_reasoning("ASSIGNEE_MATCHES_FOUND", {
            "count": len(matches),
            "matches": matches
        })

        if not matches:
            return f"I couldn't find any employee named '{assignee_raw}' in the database."

        # HANDLE MULTIPLE USERS FROM MONGO
        if len(matches) > 1:
            log_reasoning("DUPLICATE_FOUND_RESOLVING_VIA_MONGO", {"count": len(matches)})
            clarification_msg = await get_duplicate_resolution_message(matches, assignee_raw)
            return clarification_msg

        # Unique user resolved
        user = matches[0]
        login_code = user["login_code"]
            
        user = matches[0]
        login_code = user["login_code"]

        log_reasoning("ASSIGNEE_RESOLVED", {
            "login_code": login_code,
            "user": user
        })

        documents_child = []
        document_data = ctx.document_data
        if document_data:
            media_type = document_data.get("type") 
            media_info = document_data.get(media_type)
            if media_info:
                base64_data = download_and_encode_document(media_info)
                if base64_data:
                    fname = media_info.get("filename") or "attachment"
                    documents_child.append(
                        DocumentItem(
                            DOCUMENT=DocumentInfo(VALUE=fname, BASE64=base64_data),
                            DOCUMENT_NAME=fname
                        )
                    )
        req = CreateTaskRequest(
            ASSIGNEE=login_code,
            DESCRIPTION=task_name,
            TASK_NAME=task_name,
            EXPECTED_END_DATE=to_appsavy_datetime(deadline),
            MOBILE_NUMBER=ctx.sender_phone[-10:],
            DETAILS=Details(CHILD=[]),
            DOCUMENTS=Documents(CHILD=documents_child)
        )
        api_response = await call_appsavy_api("CREATE_TASK", req)
        if not api_response:
            return None
        if str(api_response.get("result")) == "1":
            return None
        return None
    
    except Exception:
        logger.error("assign_new_task_tool failed", exc_info=True)
        return None

APPSAVY_STATUS_MAP = {
    "Open": "Open",
    "Work In Progress": "Work In Progress",
    "Close": "Closed",
    "Closed": "Closed",
    "Reopened": "Reopen"
}

async def update_task_status_tool(
    ctx: ManagerContext,
    task_id: str,
    status: str,
    remark: Optional[str] = None
) -> None:
    """
    Updates the status of an existing task using the pre-mapped status from Agent 2.
    """
    log_reasoning("UPDATE_TASK_STATUS_START", {
        "task_id": task_id,
        "status": status,
        "by": ctx.role
    })

    sender_mobile = ctx.sender_phone[-10:]

    # Handle optional document

    doc_value, doc_base64 = "", ""
    if ctx.document_data:
        media_type = ctx.document_data.get("type")
        media_info = ctx.document_data.get(media_type)
        if media_info:
            base64_data = download_and_encode_document(media_info)
            if base64_data:
                doc_value = media_info.get("filename") or "update_attachment"
                doc_base64 = base64_data

    req = UpdateTaskRequest(
        TASK_ID=str(task_id),
        STATUS=status,
        COMMENTS=remark or "Updated via AI Assistant",
        UPLOAD_DOCUMENT=UploadDocument(VALUE=doc_value, BASE64=doc_base64), # Correct mapping
        WHATSAPP_MOBILE_NUMBER=sender_mobile
    )

    await call_appsavy_api("UPDATE_STATUS", req)
    return None

def should_send_whatsapp(text: str) -> bool:

    if not text:
        return False

    block_keywords = [
        "api error",
        "system error",
        "failed",
        "error",
        "exception",
        "invalid",
        "update failed",
        "unable to"
    ]

    t = text.lower()
    return not any(k in t for k in block_keywords)

def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    # Ensure it's a string and strip non-digits
    digits = re.sub(r"\D", "", str(phone))
    # Remove leading zero if it's an 11-digit number (e.g., 09999999999)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    # Standardize to 91XXXXXXXXXX
    if len(digits) == 10:
        return "91" + digits
    elif len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits

def merge_slots(session_id: str, new_slots: dict):
    history = get_session_history(session_id)
    log_reasoning("SESSION_HISTORY_LOG", {
        "session_id": session_id,
        "full_history": [f"{m['role']}: {m['content']}" for m in history]
    })

    # find existing slots
    existing = next(
        (msg["content"] for msg in history if msg["role"] == "slots"),
        {}
    )
    merged = {**existing, **new_slots}
    append_message(session_id, "slots", merged)
    return merged

def check_for_reset_trigger(message: str) -> bool:
    """
    Checks if the user explicitly wants to kill the current session.
    """
    if not message:
        return False
        
    reset_phrases = [
        "reset conversation",
        "clear session",
        "restart bot",
        "start over"
    ]
    
    # Normalize and check for exact match
    return message.lower().strip() in reset_phrases

async def handle_message(command, sender, pid, message=None, full_message=None):
    
    try:
        sender = normalize_phone(sender)
        trace_id = f"{sender}-{int(datetime.datetime.now().timestamp())}"
        log_reasoning("TRACE_START", trace_id)

        if not command and not message:
            return
        
        #  Authorization
        manager_phone = normalize_phone(os.getenv("MANAGER_PHONE", ""))
        team = load_team()

        # ====== ADD THIS SECTION HERE ======
        if should_reset_conversation(command):
            user = resolve_user_by_phone(users_collection, sender)
            if user:
                login_code = user["login_code"]
                session_id = get_or_create_session(login_code)
                end_session_complete(login_code, session_id)
                log_reasoning("CONVERSATION_RESET", {"sender": sender, "trigger": command})
                send_whatsapp_message(
                    sender, 
                    "Ok lets start again, please tell me how can I be of your help",
                    pid
                )
            return
        # ====== END OF NEW SECTION ======
        # Determine Role
        if sender == manager_phone:
            role = "manager"
        elif any(normalize_phone(u["phone"]) == sender for u in team):
            role = "employee"
        else:
            user_temp = resolve_user_by_phone(users_collection, sender)
            if user_temp:
                end_session_complete(user_temp["login_code"], get_or_create_session(user_temp["login_code"]))
            
            send_whatsapp_message(sender, "Access Denied: Your number is not authorized.", pid)
            return

        user = resolve_user_by_phone(users_collection, sender)
        if not user and sender == manager_phone:
            user = {"login_code": "MANAGER", "phone": sender, "name": "Manager"}

        if not user:
            send_whatsapp_message(sender, "Access Denied: Your number is not registered.", pid)
            return

        login_code = user["login_code"]
        session_id = get_or_create_session(login_code)
        
        # Save user input to history
        append_message(session_id, "user", command)
        log_reasoning("USER_INPUT_RECEIVED", {"sender": sender, "command": command})
        history = get_session_history(session_id)
        log_reasoning("SESSION_HISTORY_LOG", {
            "session_id": session_id,
            "full_history": [f"{m['role']}: {m['content']}" for m in history]
        })

        # Setup Context
        last_assistant_msg = next((m for m in reversed(history) if m["role"] == "assistant"), None)
        is_cross_questioning = last_assistant_msg and "[CLARIFY]" in last_assistant_msg["content"]

        # Find the most recent intent saved in the system history
        existing_intent = next(
            (m["content"].replace("INTENT_SET: ", "") 
            for m in reversed(history) 
            if m["role"] == "system" and "INTENT_SET:" in m["content"]), 
            None
        )

        # Logging        
        log_reasoning("DEBUG_STATE", {"is_cross_questioning": is_cross_questioning, "existing_intent": existing_intent, "last_assistant_msg": last_assistant_msg})

        intent = None
        is_supported = False

        if is_cross_questioning:
            if existing_intent:
                # CONDITION: Cross question and intent is not null -> Agent 2
                intent = existing_intent
                is_supported = True
                log_reasoning("AGENT_2_RESUME", {"intent": intent, "reason": "Reply to [CLARIFY]"})
            else:
                # CONDITION : Cross question and intent is null -> Error
                log_reasoning("ERROR", {"reason": "Cross-question state detected but no existing_intent found."})
                send_whatsapp_message(sender, "System error: Lost context of previous request. Please start over.", pid)
                end_session_complete(login_code, session_id)
                return
        else:
            if existing_intent:
                # CONDITION: Intent is not null (not in cross-question) -> Agent 2
                intent = existing_intent
                is_supported = True
                log_reasoning("AGENT_2_CONTINUE", {"intent": intent})
            else:
                # CONDITION: Intent is null -> Agent 1 call
                is_supported, intent, confidence, reasoning = intent_classifier(command)
        
                log_reasoning("INTENT_CLASSIFIED", {
                    "intent": intent,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "is_supported": is_supported
                })

                if is_supported and intent:
                    append_message(session_id, "system", f"INTENT_SET: {intent}")
                else:
                    send_whatsapp_message(
                        sender,
                        "I'm sorry, I didn't quite catch that. I can help with task assignment, "
                        "updates, performance reports, and user management. What would you like to do?",
                        pid
                    )
                    end_session_complete(login_code, session_id)
                    return
                
        # Context Setup 
        AGENT2_INTENTS = {"TASK_ASSIGNMENT", "UPDATE_TASK_STATUS", "ADD_USER", "DELETE_USER", "VIEW_EMPLOYEE_PERFORMANCE"}
        agent2_required = intent in AGENT2_INTENTS
        
        if message and not command:
            set_pending_document(session_id, message)
            send_whatsapp_message(
                sender, 
                "I've received your document. Would you like to 'Assign a new task' with this or 'Update an existing task'?", 
                pid
            )
            return
        pending_doc = get_pending_document(session_id)
        ctx_document = pending_doc if pending_doc else message
        ctx = ManagerContext(
            sender_phone=sender,
            role=role,
            current_time=datetime.datetime.now(IST),
            document_data=ctx_document 
        )
        
        # Direct Tools (Agent 1 Only)
        if not agent2_required:
            try:
                if intent == "VIEW_EMPLOYEES_UNDER_MANAGER":
                    await get_task_list_tool(ctx, view="users")
                elif intent == "VIEW_PENDING_TASKS":
                    pending = await get_task_list_tool(ctx, view="tasks")
                    if pending:
                        send_whatsapp_message(sender, "\n".join(pending), pid)
                elif intent == "VIEW_EMPLOYEE_PERFORMANCE":
                    await get_performance_report_tool(ctx)
            except Exception as e:
                logger.error(f"Error executing direct tool {intent}: {e}")
            finally:
                # Requirement: Clear cache on every successful or failed call
                end_session_complete(login_code, session_id)
            
            return

        # Agent-2 : Parameter Extraction
        # Retrieve latest slots and format history for Agent 2
        slots = next((m["content"] for m in reversed(history) if m.get("role") == "slots"), {})
        full_convo_context = "\n".join([f"{m['role']}: {m['content']}" for m in history])
        log_reasoning("AGENT_2_HISTORY_CONTEXT", {"history_sent": full_convo_context})

        result = None

        if intent == "TASK_ASSIGNMENT":
            result = await run_gemini_extractor(
                prompt=f"""You are helping assign a task.

KNOWN INFORMATION (do NOT ask again):
{json.dumps(slots, indent=2)}

USER QUERY (verbatim):
"{command}"

Current Date: {ctx.current_time.strftime("%Y-%m-%d")}
Current Time: {ctx.current_time.strftime("%I:%M %p")}

RULES:
- Convert relative deadlines (e.g., "in 4 hours", "tomorrow", "by EOD") into absolute ISO 8601 format.
- "EOD" should be treated as 18:00 (6:00 PM) of the current day.
- Ensure the 'deadline' string is strictly a valid ISO format.

Your job:
- Reuse ANY information already present in the user query
- Extract missing values ONLY if they are not clearly specified
- If ALL required fields are present → return JSON
- If ANY required field is missing → ask ONE clear follow-up question
- Do NOT invent values
- Do NOT repeat information already given

Required fields:
- assignee (name or phone)
- task_name
- deadline (ISO format if possible)

Current date: {ctx.current_time.strftime("%Y-%m-%d")}

If returning JSON, use EXACTLY this format:
{{
  "assignee": string,
  "task_name": string,
  "deadline": string
}}

Rules:
- Either return JSON OR a question
- Do not explain anything else
""",
                message=full_convo_context
            )

        elif intent == "UPDATE_TASK_STATUS":
            result = await run_gemini_extractor(
                prompt=f"""You are helping update a task status.

KNOWN INFORMATION (do NOT ask again):
{json.dumps(slots, indent=2)}

USER QUERY (verbatim):
"{command}"

Current Date: {ctx.current_time.strftime("%Y-%m-%d")}
Current Time: {ctx.current_time.strftime("%I:%M %p")}

RULES:
- Convert relative deadlines (e.g., "in 4 hours", "tomorrow", "by EOD") into absolute ISO 8601 format.
- "EOD" should be treated as 18:00 (6:00 PM) of the current day.
- Ensure the 'deadline' string is strictly a valid ISO format.

MAPPING RULES (Return EXACTLY one of these 4 values for the 'status' field):
- If the user wants to start, is working on it, or it's pending -> "Work In Progress"
- If the user has finished, completed, or fixed it -> "Closed"
- If the user wants to restart or redo a closed task -> "Reopened"
- If the user says it is still open or should stay open -> "Open"

Required fields:
- task_id: string
- status: "Open" | "Work In Progress" | "Closed" | "Reopened"
Optional:
- remark: string | null

If returning JSON, use EXACTLY this format:
{{
  "task_id": string,
  "status": string,
  "remark": string | null
}}

Rules:
- Either return JSON OR a follow-up question
- No explanations
""",
                message=full_convo_context
            )

        elif intent == "ADD_USER":
            result = await run_gemini_extractor(
                prompt=f"""You are helping add a new user.

KNOWN INFORMATION (do NOT ask again):
{json.dumps(slots, indent=2)}

USER QUERY (verbatim):
"{command}"

Your job:
- Reuse information already present
- Ask ONE follow-up question if something is missing
- Do NOT invent values

Required:
- name
- mobile (10 digits)
Optional:
- email

If returning JSON, use EXACTLY:
{{
  "name": string,
  "mobile": string,
  "email": string | null
}}

Rules:
- Either return JSON OR a follow-up question
- No explanations
""",
                message=full_convo_context
            )
            
        elif intent == "VIEW_EMPLOYEE_PERFORMANCE":
            result = await run_gemini_extractor(
                prompt=f"""
                REPORT TYPE RULES:
                1. If the user mentions a specific person (e.g., "Abhilasha", "Rahul") -> report_type = "Count", name = "extracted name"
                2. If the user asks for a general/overall report or no name is found -> report_type = "Detail", name = null
                Return ONLY JSON:
                {{
                    "report_type": "Detail" | "Count",
                    "name": string | null
                }}
                """,
                message=full_convo_context
            )

        elif intent == "DELETE_USER":
            result = await run_gemini_extractor(
                prompt=f"""You are helping delete a user.

KNOWN INFORMATION (do NOT ask again):
{json.dumps(slots, indent=2)}

USER QUERY (verbatim):
"{command}"

Your job:
- Reuse information already present
- Ask ONE follow-up question if missing
- Do NOT invent values

Required:
- name
- mobile

If returning JSON, use EXACTLY:
{{
  "name": string,
  "mobile": string
}}

Rules:
- Either return JSON OR a follow-up question
- No explanations
""",
                message=full_convo_context
            )

        # Logic: If it's a string, check if it's actually JSON in a string wrapper
        if isinstance(result, str):
            cleaned_result = result.strip().replace("```json", "").replace("```", "").strip()
            
            try:
                # Try to parse it. If it works, it's NOT a clarification, it's DATA.
                result = json.loads(cleaned_result)
                log_reasoning("AGENT_2_JSON_PARSED", {"source": "string_cleaned"})
            except json.JSONDecodeError:
                # If parsing fails, it's definitely a question/clarification for the user.
                log_reasoning("AGENT_2_CLARIFICATION_SENT", {"agent_msg": result})
                append_message(session_id, "assistant", f"[CLARIFY] {result}") 
                send_whatsapp_message(sender, result, pid)
                return

        # Agent 2 produced JSON (the "Flag" is now set to true)
        merged_data = merge_slots(session_id, result)
        log_reasoning("AGENT_2_FLAG_TRUE", {"parameters_extracted": merged_data})
        append_message(session_id, "slots", merged_data)

        # Execute Tool Calls
        try:
            if intent == "TASK_ASSIGNMENT" and all(k in merged_data for k in ("assignee", "task_name", "deadline")):
                log_reasoning("TOOL_EXECUTION_START", {"intent": intent, "data": merged_data})
                tool_output = await assign_new_task_tool(ctx, **merged_data)
                
                if isinstance(tool_output, str):
                    append_message(session_id, "assistant", f"[CLARIFY] {tool_output}") 
                    send_whatsapp_message(sender, tool_output, pid)
                    return 
                end_session_complete(login_code, session_id)
            elif intent == "UPDATE_TASK_STATUS" and all(k in merged_data for k in ("task_id", "status")):
                log_reasoning("TOOL_EXECUTION_START", {"intent": intent, "data": merged_data})
                await update_task_status_tool(ctx, **merged_data)
                end_session_complete(login_code, session_id)

            elif intent == "ADD_USER" and all(k in merged_data for k in ("name", "mobile")):
                log_reasoning("TOOL_EXECUTION_START", {"intent": intent, "data": merged_data})
                await add_user_tool(ctx, **merged_data)
                end_session_complete(login_code, session_id)

            elif intent == "DELETE_USER" and all(k in merged_data for k in ("name", "mobile")):
                log_reasoning("TOOL_EXECUTION_START", {"intent": intent, "data": merged_data})
                await delete_user_tool(ctx, **merged_data)
                end_session_complete(login_code, session_id)
            
            elif intent == "VIEW_EMPLOYEE_PERFORMANCE" and "report_type" in merged_data:
                log_reasoning("TOOL_EXECUTION_START", {"intent": intent, "data": merged_data})
                await get_performance_report_tool(
                    ctx,
                    report_type=merged_data["report_type"], 
                    name=merged_data.get("name")
                )
                end_session_complete(login_code, session_id)
            
        except Exception as e:
            logger.error(f"API Tool Execution Failed for {intent}: {e}")
            # Requirement: Clear cache even on failed API calls
            end_session_complete(login_code, session_id)

    except Exception:
        logger.error("handle_message failed", exc_info=True)
        