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

# --- API CONFIGURATION ---
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ai_model = GeminiModel('gemini-2.0-flash', api_key=GEMINI_API_KEY)

class ManagerContext(BaseModel):
    sender_phone: str
    role: str
    message_data: Optional[Dict[str, Any]] = None

# --- SYSTEM PROMPT (Strictly No Emojis / API Centric) ---
SYSTEM_PROMPT = """
You are the Official AI Task Manager Bot for login mdpvvnl. 
Your operations are strictly governed by the provided API tools. 

OPERATIONAL RULES:
1. STATUS MANAGEMENT:
   - Tasks must strictly follow this progression: 'Pending' -> 'Work done Pending for approval' -> 'Closed'.
   - Use update_task_status_tool to transition between these states.
   - Refuse approval requests if the user role is not 'manager'.

2. PERFORMANCE REPORTING:
   - When generating reports, use the get_performance_report_tool.
   - Data must be formatted exactly as follows:
     Name- [Name]
     Task Assigned- Count of Task [Total] Nos
     Task Completed- Count of task [Closed] Nos
     Task Pending - 
     Within time: [Calculated Count]
     Beyond time: [Calculated Count]
   - Calculate 'Within' vs 'Beyond' time by comparing EXPECTED_END_DATE from the API to current date and time.

3. TASK LISTING AND SORTING:
   - Fetch tasks via get_task_list_tool.
   - Sort the output in descending order by due date (Oldest due dates first).
   - Label tasks as [Pending], [Waiting Approval], or [Closed]. Do not use emojis.

4. TASK ASSIGNMENT:
   - Assignments must be linked to a Mobile Number. 
   - Use assign_new_task_tool which maps to the CREATE_TASK API.
   - You must pass the target mobile number to the ASSIGNEE field and the LOGIN field within DETAILS.

5. DOCUMENT HANDLING:
   - If a document is received, inform the user you are ready to link it once they provide the mobile number for assignment.
"""

task_agent = Agent(
    ai_model,
    deps_type=ManagerContext,
    system_prompt=SYSTEM_PROMPT
)

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
    NATURE_OF_COMPLAINT: str = "1"
    NOTICE_BEFORE: str = "4"
    MANUAL_DIARY_NUMBER: str = "er3"
    ORIGINAL_LETTER_NUMBER: str = "32"
    REFERENCE_LETTER_NUMBER: str = "334"

class GetAssigneeRequest(BaseModel):
    Event: str = "0"
    Child: List[Dict] = Field(default_factory=lambda: [{"Control_Id": "106771", "AC_ID": "111057"}])

class GetTasksRequest(BaseModel):
    Event: str = "106830"
    Child: List[Dict]

class UpdateTaskRequest(BaseModel):
    SID: str = "607"
    TASK_ID: str
    STATUS: str
    COMMENTS: str = "TASK ACKNOWLEDGE"

# --- REST API HELPERS ---
def call_appsavy_api(key: str, payload: BaseModel) -> Optional[Dict]:
    config = API_CONFIGS[key]
    try:
        res = requests.post(config["url"], headers=config["headers"], json=payload.model_dump(), timeout=15)
        return res.json() if res.status_code == 200 else None
    except Exception:
        return None

def load_team():
    res = call_appsavy_api("GET_ASSIGNEE", GetAssigneeRequest())
    if not res or not isinstance(res, list): return []
    return [{"name": i.get("PARTICIPANTS", "").lower(), "phone": i.get("LOGIN", ""), "email": ""} for i in res]

def load_tasks():
    req = GetTasksRequest(Child=[{"Control_Id": "106831", "AC_ID": "110803", "Parent": [{"Control_Id": "106825", "Value": "Open,Closed,Work done Pending for approval", "Data_Form_Id": ""}]}])
    res = call_appsavy_api("GET_TASKS", req)
    if not res or not isinstance(res, list): return []
    tasks = []
    for i in res:
        tasks.append({
            "task_id": str(i.get("TASK_ID", "0")), 
            "task": i.get("TASK_NAME", ""),
            "assignee_name": i.get("USER_NAME", ""), 
            "deadline": i.get("EXPECTED_END_DATE", ""),
            "status": i.get("STATUS", "Pending"), 
            "remarks": i.get("COMMENTS", ""),
            "assignee_phone": i.get("LOGIN", ""), 
            "manager_phone": i.get("MANAGER_PHONE", "")
        })
    return tasks

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

# --- AGENT TOOLS ---
@task_agent.tool
def get_performance_report_tool(ctx: RunContext[ManagerContext], name: Optional[str] = None) -> str:
    tasks, team, now = load_tasks(), load_team(), datetime.datetime.now()
    display_team = [e for e in team if name and name.lower() in e['name'].lower()] if name else team
    if not display_team: return f"Employee {name} not found."
    results = []
    for member in display_team:
        phone = member['phone']
        m_tasks = [t for t in tasks if t['assignee_phone'] == phone]
        comp = len([t for t in m_tasks if t['status'] == 'Closed'])
        pend_list = [t for t in m_tasks if t['status'] != 'Closed']
        within, beyond = 0, 0
        for t in pend_list:
            try:
                dt = datetime.datetime.fromisoformat(t['deadline'].replace("Z", ""))
                if dt > now: within += 1
                else: beyond += 1
            except Exception: within += 1
        results.append(
            f"Name- {member['name'].title()}\n"
            f"Task Assigned- Count of Task {len(m_tasks)} Nos\n"
            f"Task Completed- Count of task {comp} Nos\n"
            f"Task Pending -\nWithin time: {within}\nBeyond time: {beyond}"
        )
    return "\n\n".join(results)

@task_agent.tool
def get_task_list_tool(ctx: RunContext[ManagerContext], filter_self: bool = True) -> str:
    tasks = load_tasks()
    if filter_self:
        tasks = [t for t in tasks if t['assignee_phone'] == ctx.deps.sender_phone]
    try:
        tasks.sort(key=lambda x: x['deadline'], reverse=True)
    except Exception: pass
    if not tasks: return "No tasks found."
    output = "Task List:\n"
    for t in tasks:
        output += f"- ID: {t['task_id']} | {t['task']} | Due: {t['deadline']} | [{t['status']}]\n"
    return output

@task_agent.tool
def assign_new_task_tool(ctx: RunContext[ManagerContext], mobile: str, task_name: str, deadline: str) -> str:
    team = load_team()
    emp = next((e for e in team if mobile in e['phone']), None)
    participant_name = emp['name'].upper() if emp else "EXTERNAL USER"
    state_doc = state_col.find_one({"id": "global_state"}) or {"data": {}}
    state = state_doc.get("data", {})
    pending_doc = state.get(ctx.deps.sender_phone, {}).get("pending_document")
    doc_payload = Documents(CHILD=[])
    if pending_doc:
        b64_content = download_and_encode_document(pending_doc)
        if b64_content:
            doc_payload.CHILD.append(DocumentItem(
                DOCUMENT=DocumentInfo(VALUE=pending_doc.get("filename", "ABC.PNG"), BASE64=b64_content),
                DOCUMENT_NAME="TEST"
            ))
    req = CreateTaskRequest(
        ASSIGNEE=mobile,
        DESCRIPTION=task_name,
        EXPECTED_END_DATE=deadline,
        TASK_NAME=task_name,
        DETAILS=Details(CHILD=[DetailChild(SEL="Y", LOGIN=mobile, PARTICIPANTS=participant_name)]),
        DOCUMENTS=doc_payload
    )
    if call_appsavy_api("CREATE_TASK", req):
        if pending_doc:
            state[ctx.deps.sender_phone].pop("pending_document", None)
            state_col.update_one({"id": "global_state"}, {"$set": {"data": state}})
        return f"Task successfully assigned to mobile {mobile}."
    return "Failed to assign task through API."

@task_agent.tool
def update_task_status_tool(ctx: RunContext[ManagerContext], task_id: str, action: str) -> str:
    status_map = {"finish": "Work done Pending for approval", "approve": "Closed"}
    new_status = status_map.get(action.lower())
    if not new_status: return "Invalid action. Use 'finish' or 'approve'."
    if action.lower() == "approve" and ctx.deps.role != "manager":
        return "Permission Denied: Only managers can approve tasks."
    req = UpdateTaskRequest(TASK_ID=task_id, STATUS=new_status)
    if call_appsavy_api("UPDATE_STATUS", req):
        return f"Task {task_id} status updated to {new_status}."
    return "API error updating task status."

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
        send_whatsapp_message(sender, "Document received. Provide the mobile number and details to assign it.", pid)
        return
    team = load_team()
    role = "manager" if not any(e.get("phone") == sender for e in team) else "employee"
    if command:
        try:
            result = task_agent.run_sync(command, deps=ManagerContext(sender_phone=sender, role=role, message_data=message))
            send_whatsapp_message(sender, result.data, pid)
        except Exception as e:
            send_whatsapp_message(sender, f"Processing Error: {str(e)}", pid)
    if mid: processed_col.insert_one({"msg_id": mid})