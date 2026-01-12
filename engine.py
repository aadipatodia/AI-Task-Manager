import os
import json
import datetime
import base64
import requests
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.gemini import GeminiModel
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
from send_message import send_whatsapp_message, send_whatsapp_document
from google_auth_oauthlib.flow import Flow 
from pymongo import MongoClient
import certifi

load_dotenv()

# --- MISSING OAUTH CONSTANTS (Fixed for webhook.py) ---
SCOPES = ['https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://ai-task-manager.onrender.com/oauth2callback")

# --- API CONFIGURATION (TM_API Fixed Manager) ---
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
    }
}

# --- DATABASE INITIALIZATION ---
MONGO_URI = os.getenv("MONGO_URI")
db_client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = db_client['ai_task_manager']

state_col = db['state']
tokens_col = db['user_tokens']
processed_col = db['processed_messages']

# --- PYDANTIC AI AGENT INITIALIZATION ---
# GeminiModel reads key from Environment Variables to avoid TypeError
ai_model = GeminiModel('gemini-2.0-flash')

class ManagerContext(BaseModel):
    sender_phone: str
    role: str
    message_data: Optional[Dict[str, Any]] = None

# --- DETAILED SYSTEM PROMPT ---
SYSTEM_PROMPT = """
You are the Official AI Task Manager Bot for login mdpvvnl. 
You act as the TM_API manager. You have no internal task memory; every query must be handled via API tools.

TASK STATUS PROTOCOLS:
- Initial state: 'Open'.
- For Employees (Assignees): Only 'Partially Closed' and 'Reported Closed' are allowed.
- For Managers (Assignors): Only they can set 'Closed' (Approval) or 'Reopened' (Rejection).
- Validation: If an employee tries to set 'Closed' or 'Reopened', state that only managers have this authority.

OPERATIONAL DIRECTIVES:
1. PERFORMANCE REPORTING: Use 'get_performance_report_tool'. Compare 'EXPECTED_END_DATE' against current time for 'Within time' vs 'Beyond time'.
   Format exactly:
   Name- [Name]
   Task Assigned- Count of Task [Total] Nos
   Task Completed- Count of task [Closed Status Only] Nos
   Task Pending - 
   Within time: [Count]
   Beyond time: [Count]

2. TASK LISTING: Use 'get_task_list_tool'. Sort results in descending order (older to newer) based on due date.

3. ASSIGNMENTS: Use 'assign_new_task_tool'. Resolve names to the Login ID/Mobile from the authorized directory.

4. DOCUMENTS: If a file/image is received, acknowledge it and state: "File saved. Provide the task name and assignee details to complete the assignment."

STRICT CONSTRAINTS:
- No emojis.
- No requirement numbers or meta-talk.
"""

task_agent = Agent(
    ai_model,
    deps_type=ManagerContext,
    system_prompt=SYSTEM_PROMPT
)

# --- AUTHORIZED TEAM MAPPING (Fixed Users) ---
def load_team():
    return [
        {"name": "mdpvvnl", "phone": "919650523477", "email": "test-email@example.com", "login_code": "mdpvvnl"},
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

# --- REST API HELPERS ---
def call_appsavy_api(key: str, payload: BaseModel) -> Optional[Dict]:
    config = API_CONFIGS[key]
    try:
        res = requests.post(config["url"], headers=config["headers"], json=payload.model_dump(), timeout=15)
        return res.json() if res.status_code == 200 else None
    except:
        return None

def download_and_encode_document(document_data: Dict):
    access_token = os.getenv("ACCESS_TOKEN")
    media_id = document_data.get("id")
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(f"https://graph.facebook.com/v20.0/{media_id}/", headers=headers)
    if r.status_code != 200: return None
    download_url = r.json().get("url")
    dr = requests.get(download_url, headers=headers)
    if dr.status_code == 200:
        return base64.b64encode(dr.content).decode("utf-8")
    return None

def fetch_live_tasks():
    req = GetTasksRequest(Child=[{"Control_Id": "106831", "AC_ID": "110803", "Parent": [{"Control_Id": "106825", "Value": "Open,Closed,Partially Closed,Reported Closed,Reopened", "Data_Form_Id": ""}]}])
    res = call_appsavy_api("GET_TASKS", req)
    return res if isinstance(res, list) else []

# --- AGENT TOOLS ---
@task_agent.tool
def get_performance_report_tool(ctx: RunContext[ManagerContext], name: Optional[str] = None) -> str:
    tasks_data, team, now = fetch_live_tasks(), load_team(), datetime.datetime.now()
    display_team = [e for e in team if name and name.lower() in e['name'].lower()] if name else team
    if not display_team: return f"Employee {name} not found."
    
    results = []
    for member in display_team:
        login = member['login_code']
        m_tasks = [t for t in tasks_data if t.get('LOGIN') == login]
        comp = len([t for t in m_tasks if t.get('STATUS') == 'Closed'])
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
            f"Task Assigned- Count of Task {len(m_tasks)} Nos\n"
            f"Task Completed- Count of task {comp} Nos\n"
            f"Task Pending -\nWithin time: {within}\nBeyond time: {beyond}"
        )
    return "\n\n".join(results)

@task_agent.tool
def get_task_list_tool(ctx: RunContext[ManagerContext], target_name: Optional[str] = None) -> str:
    tasks_data, team = fetch_live_tasks(), load_team()
    login_id = None
    if target_name:
        user = next((u for u in team if target_name.lower() in u['name'].lower()), None)
        if user: login_id = user['login_code']
    else:
        user = next((u for u in team if u['phone'] == ctx.deps.sender_phone), None)
        if user: login_id = user['login_code']

    if not login_id: return "No tasks found."
    filtered = [t for t in tasks_data if t.get('LOGIN') == login_id]
    try:
        filtered.sort(key=lambda x: x.get('EXPECTED_END_DATE', ''), reverse=True)
    except: pass
    
    if not filtered: return "No pending tasks."
    output = "Task List:\n"
    for t in filtered:
        output += f"- ID: {t.get('TASK_ID')} | {t.get('TASK_NAME')} | Due: {t.get('EXPECTED_END_DATE')} | Status: {t.get('STATUS')}\n"
    return output

@task_agent.tool
def assign_new_task_tool(ctx: RunContext[ManagerContext], name: str, task_name: str, deadline: str) -> str:
    team = load_team()
    user = next((u for u in team if name.lower() in u['name'].lower()), None)
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
        ASSIGNEE=login_code,
        DESCRIPTION=task_name,
        EXPECTED_END_DATE=deadline,
        TASK_NAME=task_name,
        DETAILS=Details(CHILD=[DetailChild(LOGIN=login_code, PARTICIPANTS=user['name'].upper())]),
        DOCUMENTS=doc_payload
    )

    if call_appsavy_api("CREATE_TASK", req):
        send_whatsapp_message(user['phone'], f"New Task: {task_name}. Due: {deadline}", os.getenv("PHONE_NUMBER_ID"))
        if pending_doc:
            state[ctx.deps.sender_phone].pop("pending_document", None)
            state_col.update_one({"id": "global_state"}, {"$set": {"data": state}})
        return f"Task assigned to {user['name']} (ID: {login_code}). Notification sent."
    return "API Error."

@task_agent.tool
def update_task_status_tool(ctx: RunContext[ManagerContext], task_id: str, action: str) -> str:
    status_map = {"partial": "Partially Closed", "reported": "Reported Closed", "close": "Closed", "reopen": "Reopened"}
    new_status = status_map.get(action.lower())
    if not new_status: return "Invalid status."
    
    if action.lower() in ["close", "reopen"] and ctx.deps.role != "manager":
        return "Permission Denied: Only managers can Close or Reopen tasks."

    req = UpdateTaskRequest(TASK_ID=task_id, STATUS=new_status)
    if call_appsavy_api("UPDATE_STATUS", req):
        return f"Task {task_id} status updated to {new_status}."
    return "API update failed."

# --- MESSAGE HANDLER ---
def handle_message(command, sender, pid, message=None, full_message=None):
    mid = full_message.get("id") if full_message else None
    processed = {d["msg_id"] for d in processed_col.find({}, {"msg_id": 1})}
    if mid and mid in processed: return
    
    if len(sender) == 10 and not sender.startswith('91'): sender = f"91{sender}"
    state_doc = state_col.find_one({"id": "global_state"}) or {"data": {}}
    state = state_doc.get("data", {})
    
    if not command and message and "document" in message:
        state[sender] = {"pending_document": message["document"]}
        state_col.update_one({"id": "global_state"}, {"$set": {"data": state}}, upsert=True)
        send_whatsapp_message(sender, "File received. Provide details to assign.", pid)
        return

    manager_phone = os.getenv("MANAGER_PHONE")
    team = load_team()
    
    if sender == manager_phone:
        role = "manager"
    elif any(u['phone'] == sender for u in team):
        role = "employee"
    else:
        send_whatsapp_message(sender, "Access Denied.", pid)
        return
    
    if command:
        try:
            result = task_agent.run_sync(command, deps=ManagerContext(sender_phone=sender, role=role))
            send_whatsapp_message(sender, result.data, pid)
        except Exception as e:
            send_whatsapp_message(sender, f"Error: {str(e)}", pid)
    
    if mid: processed_col.insert_one({"msg_id": mid})