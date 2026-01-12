import os
import json
import datetime
import base64
import requests
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.messages import ModelResponse, ModelRequest
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
from send_message import send_whatsapp_message, send_whatsapp_document
from google_auth_oauthlib.flow import Flow 
from pymongo import MongoClient
import certifi

load_dotenv()

# --- GMAIL & OAUTH CONSTANTS ---
# Essential for webhook.py to import for authentication flows
SCOPES = ['https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://ai-task-manager-38w7.onrender.com/oauth2callback")

# --- API CONFIGURATION (5 APIs - 100% Dependency) ---
# Absolute reliance on Appsavy for data; includes the new Count API
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

# --- DATABASE INITIALIZATION ---
MONGO_URI = os.getenv("MONGO_URI")
db_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = db_client['ai_task_manager']
state_col = db['state']
tokens_col = db['user_tokens']
processed_col = db['processed_messages']
history_col = db['chat_history']

# --- AGENT SETUP ---
ai_model = GeminiModel('gemini-2.0-flash')

class ManagerContext(BaseModel):
    sender_phone: str
    role: str
    current_time: datetime.datetime = Field(default_factory=datetime.datetime.now)

# --- FULL DETAILED SYSTEM PROMPT ---
# Incorporating intelligent time inference and history reliance
SYSTEM_PROMPT = """
You are the Official AI Task Manager Bot for 'mdpvvnl'. 
Identity: TM_API (Manager). You are a precise, professional assistant.
Current Date: 2026-01-12.

### 1. INTELLIGENT TIME & ASSIGNMENT INFERENCE
- When a user says "[Name] has to [Task] by [Time]", immediately use 'assign_new_task_tool'.
- **Deadline Logic:**
  * If the mentioned time (e.g., 5pm) is LATER than the current system time, assume the date is TODAY (2026-01-12).
  * If the mentioned time has already passed today, assume the date is TOMORROW (2026-01-13).
- **Name Resolution:** Resolve "[Name]" or even just login IDs (like mdpvvnl) to the correct user in your directory.

### 2. CONVERSATIONAL MEMORY
- You have access to a short history of the conversation. Use it to identify who 'he' or 'she' refers to or to remember the last discussed task.
- **Doubt Protocol:** IF IN DOUBT (e.g., multiple possible assignees or ambiguous deadlines), ALWAYS ASK THE USER FOR CONFIRMATION before calling a tool.

### 3. ROLE-BASED STATUS PROTOCOL
- **Assignees (Employee):** Can only set 'Partially Closed' or 'Reported Closed'.
- **Assignor (Manager):** Only they set 'Closed' (Approval) or 'Reopened' (Rejection).
- **Validation:** Refuse 'Closed' or 'Reopened' requests from employees.

### 4. PERFORMANCE REPORTING
Call 'get_performance_report_tool'. Format the output exactly:
Name- [Name]
Task Assigned- Count of Task [Total] Nos
Task Completed- Count of task [Closed Status Only] Nos
Task Pending - 
Within time: [Count]
Beyond time: [Count]

### 5. CONSTRAINTS
- NO emojis. NO requirement numbers.
- Task Lists must be sorted DESCENDING (Older tasks at top).
"""

task_agent = Agent(ai_model, deps_type=ManagerContext, system_prompt=SYSTEM_PROMPT)

# --- AUTHORIZED TEAM ---
def load_team():
    return [
        {"name": "mdpvvnl", "phone": "919650523477", "email": "varun.verma@mobineers.com", "login_code": "mdpvvnl"},
        {"name": "chairman", "phone": "91XXXXXXXXXX", "email": "chairman@example.com", "login_code": "chairman"},
        {"name": "mddvvnl", "phone": "91XXXXXXXXXX", "email": "mddvvnl@example.com", "login_code": "mddvvnl"},
        {"name": "ce_ghaziabad", "phone": "91XXXXXXXXXX", "email": "ce@example.com", "login_code": "ce_ghaziabad"}
    ]

# --- API SCHEMAS ---
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
    DETAILS: Details
    DOCUMENTS: Documents
    TYPE: str = "TYPE"
    PRIORTY_TASK: str = "N"

class GetTasksRequest(BaseModel):
    Event: str = "106830"
    Child: List[Dict]

class UpdateTaskRequest(BaseModel):
    SID: str = "607"
    TASK_ID: str
    STATUS: str
    COMMENTS: str = "STATUS_UPDATE"

class GetCountRequest(BaseModel):
    Event: str = "107567"
    Child: List[Dict]

# --- REST API HELPERS ---
async def call_appsavy_api(key: str, payload: BaseModel) -> Optional[Dict]:
    config = API_CONFIGS[key]
    try:
        res = requests.post(config["url"], headers=config["headers"], json=payload.model_dump(), timeout=15)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None

async def fetch_api_tasks():
    req = GetTasksRequest(Child=[{"Control_Id": "106831", "AC_ID": "110803", "Parent": [{"Control_Id": "106825", "Value": "Open,Closed,Partially Closed,Reported Closed,Reopened", "Data_Form_Id": ""}]}])
    res = await call_appsavy_api("GET_TASKS", req)
    return res if isinstance(res, list) else []

async def fetch_task_counts_api(login_code: str):
    """Fetches assigned/closed counts via SID 616"""
    req = GetCountRequest(Child=[{
        "Control_Id": "108118", "AC_ID": "113229",
        "Parent": [
            {"Control_Id": "111548", "Value": "1", "Data_Form_Id": ""},
            {"Control_Id": "107566", "Value": login_code, "Data_Form_Id": ""},
            {"Control_Id": "107599", "Value": "Assigned By Me", "Data_Form_Id": ""}
        ]
    }])
    res = await call_appsavy_api("GET_COUNT", req)
    return res[0] if res and isinstance(res, list) else {}

def download_and_encode_document(document_data: Dict):
    access_token = os.getenv("ACCESS_TOKEN")
    media_id = document_data.get("id")
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(f"https://graph.facebook.com/v20.0/{media_id}/", headers=headers)
    if r.status_code != 200: return None
    download_url = r.json().get("url")
    dr = requests.get(download_url, headers=headers)
    return base64.b64encode(dr.content).decode("utf-8") if dr.status_code == 200 else None

# --- AGENT TOOLS ---
@task_agent.tool
async def get_performance_report_tool(ctx: RunContext[ManagerContext], name: Optional[str] = None) -> str:
    """Requirement 1 & 2: Reports using specialized GET_COUNT API"""
    tasks_data = await fetch_api_tasks()
    team, now = load_team(), ctx.deps.current_time
    display_team = [e for e in team if name and name.lower() in e['name'].lower()] if name else team
    if not display_team: return f"User {name} not found."
    
    results = []
    for member in display_team:
        login = member['login_code']
        counts = await fetch_task_counts_api(login)
        m_tasks = [t for t in tasks_data if t.get('LOGIN') == login]
        within, beyond = 0, 0
        for t in m_tasks:
            if t.get('STATUS') != 'Closed':
                try:
                    dt = datetime.datetime.fromisoformat(t['EXPECTED_END_DATE'].replace("Z", ""))
                    if dt > now: within += 1
                    else: beyond += 1
                except: within += 1
        results.append(
            f"Name- {member['name'].title()}\n"
            f"Task Assigned- Count of Task {counts.get('ASSIGNED_TASK', '0')} Nos\n"
            f"Task Completed- Count of task {counts.get('CLOSED_TASK', '0')} Nos\n"
            f"Task Pending -\nWithin time: {within}\nBeyond time: {beyond}"
        )
    return "\n\n".join(results)

@task_agent.tool
async def get_task_list_tool(ctx: RunContext[ManagerContext], target_name: Optional[str] = None) -> str:
    """Requirement 3 & 7: Descending task list via API"""
    tasks_data = await fetch_api_tasks()
    team = load_team()
    user = next((u for u in team if (target_name and target_name.lower() in u['name'].lower()) or u['phone'] == ctx.deps.sender_phone), None)
    if not user: return "Identification failed."
    
    filtered = [t for t in tasks_data if t.get('LOGIN') == user['login_code']]
    filtered.sort(key=lambda x: x.get('EXPECTED_END_DATE', ''), reverse=True)
    
    output = "Task List:\n"
    for t in filtered:
        output += f"- ID: {t.get('TASK_ID')} | {t.get('TASK_NAME')} | Due: {t.get('EXPECTED_END_DATE')} | [{t.get('STATUS')}]\n"
    return output if filtered else "No pending tasks listed."

@task_agent.tool
async def assign_new_task_tool(ctx: RunContext[ManagerContext], name: str, task_name: str, deadline: str) -> str:
    """Requirement 4: Create task with auto-attachment of pending files"""
    team = load_team()
    user = next((u for u in team if name.lower() in u['name'].lower() or name.lower() == u['login_code'].lower()), None)
    if not user: return f"User {name} not found."

    login_code = user['login_code']
    state_doc = state_col.find_one({"id": "global_state"}) or {"data": {}}
    state = state_doc.get("data", {})
    pending_doc = state.get(ctx.deps.sender_phone, {}).get("pending_document")
    
    doc_payload = Documents(CHILD=[])
    if pending_doc:
        b64 = download_and_encode_document(pending_doc)
        if b64:
            doc_payload.CHILD.append(DocumentItem(
                DOCUMENT=DocumentInfo(VALUE=pending_doc.get("filename", "file.png"), BASE64=b64),
                DOCUMENT_NAME="ATTACHMENT"
            ))

    req = CreateTaskRequest(
        ASSIGNEE=login_code, DESCRIPTION=task_name, EXPECTED_END_DATE=deadline,
        TASK_NAME=task_name, DETAILS=Details(CHILD=[DetailChild(LOGIN=login_code, PARTICIPANTS=user['name'].upper())]),
        DOCUMENTS=doc_payload
    )

    if await call_appsavy_api("CREATE_TASK", req):
        send_whatsapp_message(user['phone'], f"New Task Assigned: {task_name}. Deadline: {deadline}", os.getenv("PHONE_NUMBER_ID"))
        if pending_doc:
            state[ctx.deps.sender_phone].pop("pending_document", None)
            state_col.update_one({"id": "global_state"}, {"$set": {"data": state}})
        return f"Task assigned to {user['name']} (ID: {login_code}). Notification sent."
    return "API failure during task creation."

@task_agent.tool
async def update_task_status_tool(ctx: RunContext[ManagerContext], task_id: str, action: str) -> str:
    """Requirement 5: Approval-based status updates"""
    status_map = {"partial": "Partially Closed", "reported": "Reported Closed", "close": "Closed", "reopen": "Reopened"}
    new_status = status_map.get(action.lower())
    if not new_status: return "Invalid status action."
    
    if action.lower() in ["close", "reopen"] and ctx.deps.role != "manager":
        return "Permission Denied: Only managers can Close or Reopen tasks."

    req = UpdateTaskRequest(TASK_ID=task_id, STATUS=new_status)
    if await call_appsavy_api("UPDATE_STATUS", req):
        return f"Task {task_id} status updated to {new_status}."
    return "API status update failed."

# --- ASYNC MESSAGE HANDLER (HISTORY & MEDIA FIX) ---
async def handle_message(command, sender, pid, message=None, full_message=None):
    """Restores full conversational memory and media logic"""
    if full_message and processed_col.find_one({"msg_id": full_message.get("id")}): return
    if len(sender) == 10 and not sender.startswith('91'): sender = f"91{sender}"
    
    # Media Logic Fix
    msg_type = message.get("type", "text") if message else "text"
    is_media = msg_type in ["document", "image", "video", "audio"]
    
    if is_media and not command: 
        state_doc = state_col.find_one({"id": "global_state"}) or {"data": {}}
        state = state_doc.get("data", {})
        state[sender] = {"pending_document": message.get("document") or message.get("image")}
        state_col.update_one({"id": "global_state"}, {"$set": {"data": state}}, upsert=True)
        send_whatsapp_message(sender, "File received. Provide details (Name, Task, Deadline) to assign it.", pid)
        return

    # Chat History Retrieval
    history_records = list(history_col.find({"sender": sender}).sort("timestamp", -1).limit(5))
    history_records.reverse()
    formatted_history = []
    for h in history_records:
        formatted_history.append(ModelRequest(parts=[h['user_msg']]))
        formatted_history.append(ModelResponse(parts=[h['bot_res']]))

    manager_phone = os.getenv("MANAGER_PHONE")
    team = load_team()
    role = "manager" if sender == manager_phone else "employee" if any(u['phone'] == sender for u in team) else None
    
    if command:
        try:
            result = await task_agent.run(
                command, 
                deps=ManagerContext(sender_phone=sender, role=role),
                message_history=formatted_history
            )
            send_whatsapp_message(sender, result.output, pid)
            # Save history
            history_col.insert_one({"sender": sender, "user_msg": command, "bot_res": result.data, "timestamp": datetime.datetime.now()})
        except Exception as e:
            send_whatsapp_message(sender, f"Internal Error: {str(e)}", pid)
    
    if full_message: processed_col.insert_one({"msg_id": full_message.get("id")})