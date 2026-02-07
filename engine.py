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
    get_session_history,
    end_session,
    get_agent2_state,
    update_agent2_state
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

REDIRECT_URI = os.getenv("REDIRECT_URI", "https://ai-task-manager-1-ugb8.onrender.com/oauth2callback")

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

    "GET_USERS_BY_WHATSAPP": {
        "url": f"{APPSAVY_BASE_URL}/GetDataJSONClient",
        "headers": {
            "sid": "635",
            "pid": "309",
            "fid": "13618",
            "cid": "64",
            "uid": "TM_API",
            "roleid": "1627",
            "TokenKey": "f097a996-b7cd-42c8-ad02-2e7d77f20988"
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
    Event: str = "146760"
    Child: List[Dict]

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
    EMAIL: Optional[str] = ""
    MOBILE_NUMBER: str
    NAME: str
    
async def run_gemini_extractor(
    prompt: str,
    message: str,
    intent: Optional[str] = None
):
    client = Client(api_key=os.getenv("GEMINI_API_KEY"))

    intent_block = f"\n\nLOCKED INTENT:\n{intent}\n" if intent else ""

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=f"{prompt}{intent_block}\nUSER MESSAGE:\n{message}"
    )

    raw_text = response.text

    # 🔒 CRITICAL GUARD
    if not raw_text:
        return {
            "parameters": {},
            "ready": False,
            "question": None
        }

    text = raw_text.strip()

    # JSON → ready
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return {
                "parameters": data,
                "ready": True,
                "question": None
            }
        except Exception:
            return {
                "parameters": {},
                "ready": False,
                "question": "I couldn’t understand that. Please try again."
            }

    # Plain text → follow-up question
    return {
        "parameters": {},
        "ready": False,
        "question": text
    }

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
    name: Optional[str] = None
) -> None:

    try:
        team = load_team()

        if not name:
            if ctx.role != "manager":
                return None

            req = WhatsAppPdfReportRequest(
                ASSIGNED_TO="",
                REPORT_TYPE="Detail",
                STATUS="",
                MOBILE_NUMBER=ctx.sender_phone[-10:],
                ASSIGNED_BY="",
                REFERENCE="WHATSAPP"
            )

            await call_appsavy_api("WHATSAPP_PDF_REPORT", req)
            return None

        name_l = name.lower()

        user = next(
            (
                u for u in team
                if name_l == u["login_code"].lower()
                or name_l in u["name"].lower()
            ),
            None
        )

        if not user:
            return None

        req = WhatsAppPdfReportRequest(
            ASSIGNED_TO=user["login_code"],
            REPORT_TYPE="Count",
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

    if view == "users":
        req = GetUsersByWhatsappRequest(
            Child=[{
                "Control_Id": "146761",
                "AC_ID": "202131",
                "Parent": [{
                    "Control_Id": "146759",
                    "Value": sender_mobile,
                    "Data_Form_Id": ""
                }]
            }]
        )
        await call_appsavy_api("GET_USERS_BY_WHATSAPP", req)
        return None

    team = load_team()
    user = next(
        (u for u in team if u["phone"] == normalize_phone(ctx.sender_phone)),
        None
    )
    if not user:
        return None
    login_code = user["login_code"]

    await call_appsavy_api(
        "GET_TASKS",
        GetTasksRequest(
            Event="106830",
            Child=[{
                "Control_Id": "106831",
                "AC_ID": "110803",
                "Parent": [
                    {"Control_Id": "106825", "Value": "Open,Work In Progress,Close", "Data_Form_Id": ""},
                    {"Control_Id": "106824", "Value": "", "Data_Form_Id": ""},
                    {"Control_Id": "106827", "Value": login_code, "Data_Form_Id": ""},
                    {"Control_Id": "106829", "Value": "", "Data_Form_Id": ""},
                    {"Control_Id": "107046", "Value": "", "Data_Form_Id": ""},
                    {"Control_Id": "107809", "Value": "0", "Data_Form_Id": ""},
                    {"Control_Id": "146515", "Value": sender_mobile, "Data_Form_Id": ""}
                ]
            }]
        )
    )

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
    ctx: ManagerContext,
    assignee: str,          # name OR phone
    task_name: str,
    deadline: str
) -> None:

    try:
        team = load_team()
        assignee_raw = assignee.strip()

        log_reasoning("ASSIGN_TASK_START", {
            "assignee": assignee_raw,
            "task": task_name,
            "deadline": deadline,
            "sender": ctx.sender_phone
        })

        digits = re.sub(r"\D", "", assignee_raw)
        is_phone = len(digits) in (10, 12)

        resolved_user = None
        matches: list[dict] = []

        if is_phone:
            normalized_phone = normalize_phone(digits)

            # Mongo is authoritative for phone resolution
            resolved_user = next(
                (u for u in team if normalize_phone(u.get("phone", "")) == normalized_phone),
                None
            )

            if not resolved_user:
                return None  # silent failure by design

            matches = [resolved_user]

        else:
            name_l = assignee_raw.lower()

            # ---- Fetch Appsavy directory ----
            assignee_res = await call_appsavy_api(
                "GET_ASSIGNEE",
                GetAssigneeRequest(
                    Event="0",
                    Child=[{"Control_Id": "106771", "AC_ID": "111057"}]
                )
            )

            appsavy_users = []
            if isinstance(assignee_res, dict):
                appsavy_users = assignee_res.get("data", {}).get("Result", [])
            elif isinstance(assignee_res, list):
                appsavy_users = assignee_res

            appsavy_matches = [
                {
                    "name": u.get("NAME"),
                    "login_code": u.get("ID"),
                    "phone": "N/A"
                }
                for u in appsavy_users
                if re.search(rf"\b{name_l}\b", str(u.get("NAME", "")).lower())
            ]

            mongo_matches = [
                {
                    "name": u["name"],
                    "login_code": u["login_code"],
                    "phone": u.get("phone", "N/A")
                }
                for u in team
                if re.search(rf"\b{name_l}\b", u["name"].lower())
            ]

            combined: dict[str, dict] = {}
            for u in appsavy_matches:
                combined[u["login_code"]] = u
            for u in mongo_matches:
                combined.setdefault(u["login_code"], u)

            matches = list(combined.values())

        log_reasoning("ASSIGNEE_MATCHES_FOUND", {
            "count": len(matches),
            "matches": matches
        })

        if not matches:
            return None

        if len(matches) > 1:
            final_options = []

            for candidate in matches:
                details_res = await call_appsavy_api(
                    "GET_USERS_BY_ID",
                    GetUsersByIdRequest(
                        Event="107018",
                        Child=[{
                            "Control_Id": "107019",
                            "AC_ID": "111271",
                            "Parent": [{
                                "Control_Id": "106771",
                                "Value": candidate["login_code"],
                                "Data_Form_Id": ""
                            }]
                        }]
                    )
                )

                res_list = (
                    details_res.get("data", {}).get("Result", [])
                    if isinstance(details_res, dict)
                    else details_res or []
                )

                if res_list:
                    d = res_list[0]
                    candidate["phone"] = d.get("MOBILE", "N/A")
    

                final_options.append(candidate)

            options_text = "\n".join(
                f"- {u['name']} ({u.get('office', 'Office N/A')}): {u['phone']}"
                for u in final_options
            )

            # clarification is allowed output
            return (
                f"I found multiple users matching '{assignee}'.\n\n"
                f"{options_text}\n\n"
                "Please reply with the correct 10-digit phone number."
            )
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
    
    log_reasoning("UPDATE_TASK_STATUS_START", {
        "task_id": task_id,
        "requested_status": status,
        "mapped_status": APPSAVY_STATUS_MAP.get(status),
        "by": ctx.role
    })

    sender_mobile = ctx.sender_phone[-10:]

    # ---- STATUS MAPPING (silent fallback) ----
    appsavy_status = APPSAVY_STATUS_MAP.get(status, "Closed")

    # ---- FINAL PAYLOAD ----
    req = UpdateTaskRequest(
        TASK_ID=task_id,
        STATUS=appsavy_status,
        COMMENTS=remark or "Terminal Test",
        UPLOAD_DOCUMENT={
            "VALUE": "",
            "BASE64": ""
        },
        WHATSAPP_MOBILE_NUMBER=sender_mobile
    )

    api_response = await call_appsavy_api("UPDATE_STATUS", req)

    # ---- ONLY SUCCESS MESSAGES ----
    if api_response and (str(api_response.get("RESULT")) == "1" or str(api_response.get("result")) == "1"):
        if status in ("Close", "Closed"):
            return None
        if status == "Reopened":
            return None
        return None
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
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return "91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits

async def handle_message(command, sender, pid, message=None, full_message=None):
    try:
        # ---------- Normalize sender ----------
        policy = AGENT_2_POLICY(datetime.datetime.now(IST))
        log_reasoning("AGENT_2_POLICY_ACTIVE", policy)
        sender = normalize_phone(sender)
        trace_id = f"{sender}-{int(datetime.datetime.now().timestamp())}"
        output = None
        log_reasoning("TRACE_START", trace_id)

        # ---------- Media-only handling ----------
        if message and not command:
            send_whatsapp_message(
                sender,
                "File received. Please provide assignee, task description, and deadline.",
                pid
            )
            return

        if not command:
            return

        # ---------- Authorization ----------
        manager_phone = normalize_phone(os.getenv("MANAGER_PHONE", ""))
        team = load_team()

        if sender == manager_phone:
            role = "manager"
        elif any(normalize_phone(u["phone"]) == sender for u in team):
            role = "employee"
        else:
            send_whatsapp_message(
                sender,
                "Access Denied: Your number is not authorized.",
                pid
            )
            return

        # ---------- Resolve user ----------
        user = resolve_user_by_phone(users_collection, sender)

        if not user and sender == manager_phone:
            user = {
                "login_code": "MANAGER",
                "phone": sender,
                "name": "Manager"
            }

        if not user:
            send_whatsapp_message(
                sender,
                "Access Denied: Your number is not registered.",
                pid
            )
            return

        login_code = user["login_code"]

        # ---------- Redis session ----------
        session_id = get_or_create_session(login_code)
        append_message(session_id, "user", command)

        is_supported, intent, confidence, reasoning = intent_classifier(command)
        if not is_supported or intent is None:
            send_whatsapp_message(
                sender,
                "I couldn’t understand what you want to do.\n"
                "Do you want to assign a task, update a task, or view something?",
                pid
            )
            return
        
        state = get_agent2_state(session_id)
        if state["intent"] is None:
            update_agent2_state(session_id, intent=intent)
        else:
            intent = state["intent"]  # lock to previous intent

        log_reasoning("INTENT_CLASSIFIED", {
            "intent": intent,
            "confidence": confidence,
            "reasoning": reasoning
        })

        if not is_supported or intent is None:
            send_whatsapp_message(
                sender,
                "I can help with task assignment, task updates, performance reports, "
                "viewing tasks, and user management. Please clarify your request.",
                pid
            )
            return

        ctx = ManagerContext(
            sender_phone=sender,
            role=role,
            current_time=datetime.datetime.now(IST),
            document_data=message
        )

        if intent == "TASK_ASSIGNMENT":
            extraction_prompt = f"""
You are helping assign a task.

USER QUERY (verbatim):
\"\"\"{command}\"\"\"

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

Rules:
- Either return NOTHING OR a question
- Do not explain anything else
"""

            result = await run_gemini_extractor(
                prompt=extraction_prompt,
                message=command,
                intent=intent
            )

    # If Gemini asked a question → forward directly
            existing = get_agent2_state(session_id).get("parameters", {})
            merged = {**existing, **result["parameters"]}
            update_agent2_state(
                session_id,
                parameters=merged,
                ready=result["ready"]
            )
            if not result["ready"]:
                send_whatsapp_message(sender, result["question"], pid)
                return

        elif intent == "UPDATE_TASK_STATUS":
            extraction_prompt = f"""
You are helping update a task status.

USER QUERY (verbatim):
\"\"\"{command}\"\"\"

Your job:
- Reuse ANY information already present in the user query
- Extract missing values ONLY if they are not clearly specified
- If ALL required fields are present → return JSON
- If ANY required field is missing → ask ONE clear follow-up question
- Do NOT invent values
- Do NOT repeat information already given

Required fields:
- task_id
- status (open / in progress / closed / reopened)
Optional:
- remark

Rules:
- Either return NOTHING OR a follow-up question
- No explanations
"""

            result = await run_gemini_extractor(
                extraction_prompt,
                command,
                intent=intent
            )

    # Gemini asked a question → forward as-is
            existing = get_agent2_state(session_id).get("parameters", {})
            merged = {**existing, **result["parameters"]}
            update_agent2_state(
                session_id,
                parameters=merged,
                ready=result["ready"]
            )
            if not result["ready"]:
                send_whatsapp_message(sender, result["question"], pid)
                return

        elif intent == "VIEW_EMPLOYEE_PERFORMANCE":
            extraction_prompt = f"""
You are helping generate a performance report.

USER QUERY (verbatim):
\"\"\"{command}\"\"\"

Your job is to:
1. Detect if the user mentioned a specific employee
2. If no employee is mentioned → return null
3. Do NOT invent names
4. Do NOT explain

Rules:
- Return NOTHING
"""

            result = await run_gemini_extractor(extraction_prompt, command, intent=intent)
            employee = result["parameters"].get("employee")
            await get_performance_report_tool(ctx, name=employee)
            update_agent2_state(session_id, ready=False)
            return

        elif intent == "VIEW_EMPLOYEES_UNDER_MANAGER":
            extraction_prompt = f"""
You are helping a manager view employees added by them.

USER QUERY (verbatim):
\"\"\"{command}\"\"\"

Your job:
- Confirm this intent
- No parameters are required
- Do NOT ask questions
- Do NOT invent anything
- Return JSON ONLY

Return:
{{
  "action": "list_users"
}}
"""
            await run_gemini_extractor(extraction_prompt, command, intent=intent)
            await get_task_list_tool(ctx, view="users")
            update_agent2_state(session_id, ready=False)
            return

        elif intent == "VIEW_PENDING_TASKS":
            await run_gemini_extractor(
                prompt="""
        You are helping a user view pending tasks.
        No parameters are required.
        Return NOTHING.
        """,
                message=command,
                intent=intent
            )

            pending = await get_pending_tasks(login_code)

            if pending:
                output = "\n".join(pending)
                send_whatsapp_message(sender, output, pid)
            else:
                send_whatsapp_message(sender, "No pending tasks found.", pid)

            update_agent2_state(session_id, ready=False)
            return

        elif intent == "ADD_USER":
            extraction_prompt = f"""
You are helping add a new user.

USER QUERY (verbatim):
\"\"\"{command}\"\"\"

Your job:
- Reuse information already present
- Ask ONE follow-up question if something is missing
- Do NOT invent values

Required:
- name
- mobile (10 digits)
Optional:
- email (DO NOT ASK USER FOR EMAIL IF HE HASN'T PROVIDED ANY)

Rules:
- Either return NOTHING OR a follow-up question
- No explanations
"""
            result = await run_gemini_extractor(extraction_prompt, command, intent=intent)
            
            existing = get_agent2_state(session_id).get("parameters", {})
            merged = {**existing, **result["parameters"]}
            update_agent2_state(
                session_id,
                parameters=merged,
                ready=result["ready"]
            )
            if not result["ready"]:
                send_whatsapp_message(sender, result["question"], pid)
                return

        elif intent == "DELETE_USER":
            extraction_prompt = f"""
You are helping delete a user.

USER QUERY (verbatim):
\"\"\"{command}\"\"\"

Your job:
- Reuse information already present
- Ask ONE follow-up question if missing
- Do NOT invent values

Required:
- name
- mobile


Rules:
- Either return NOTHING OR a follow-up question
- No explanations
"""
            result = await run_gemini_extractor(extraction_prompt, command, intent=intent)
            
            existing = get_agent2_state(session_id).get("parameters", {})
            merged = {**existing, **result["parameters"]}
            update_agent2_state(
                session_id,
                parameters=merged,
                ready=result["ready"]
            )
            if not result["ready"]:
                send_whatsapp_message(sender, result["question"], pid)
                return
            
        # ---------- EXECUTION TRIGGER ----------
        state = get_agent2_state(session_id)

        if state["ready"] is True:

            if state["intent"] == "TASK_ASSIGNMENT":
                await assign_new_task_tool(ctx, **state["parameters"])

            elif state["intent"] == "UPDATE_TASK_STATUS":
                await update_task_status_tool(ctx, **state["parameters"])

            elif state["intent"] == "ADD_USER":
                await add_user_tool(ctx, **state["parameters"])

            elif state["intent"] == "DELETE_USER":
                await delete_user_tool(ctx, **state["parameters"])

            end_session(login_code, session_id)
            return

        state = get_agent2_state(session_id)
        if state["ready"] is False:
            return  

        # ---------- WhatsApp output ----------
        if output and should_send_whatsapp(output):
            send_whatsapp_message(sender, output, pid)

    except Exception:
        logger.error("handle_message failed", exc_info=True)