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

# Load environment variables from .env file
load_dotenv()

# --- LOGGING CONFIGURATION ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- GMAIL & OAUTH CONSTANTS ---
SCOPES = ['https://www.googleapis.com/auth/gmail.send']
REDIRECT_URI = os.getenv("REDIRECT_URI", "https://ai-task-manager-38w7.onrender.com/oauth2callback")
MANAGER_EMAIL = "patodiaaadi@gmail.com"

# --- API CONFIGURATION (100% Dependency) ---
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

# --- PYDANTIC AI AGENT INITIALIZATION ---
ai_model = GeminiModel('gemini-2.0-flash-exp')

class ManagerContext(BaseModel):
    sender_phone: str
    role: str
    current_time: datetime.datetime = Field(default_factory=datetime.datetime.now)

# --- ENHANCED SYSTEM PROMPT FOR NATURAL CONVERSATION ---
def get_system_prompt(current_time: datetime.datetime) -> str:
    """Generate system prompt with dynamic current date and time."""
    current_date_str = current_time.strftime("%Y-%m-%d")
    current_time_str = current_time.strftime("%I:%M %p")
    day_of_week = current_time.strftime("%A")
    
    return f"""You are the Official AI Task Manager Bot for the organization. Identity: TM_API (Manager).
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
1. **Pending** - Initial state when task is created
2. **Work Done** - Employee uses 'reported' action
3. **Completed** - Manager uses 'close' action to approve

**Status Actions:**
- 'partial' → "Partially Closed" (work in progress)
- 'reported' → "Reported Closed" (employee marks as done, awaits approval)
- 'close' → "Closed" (MANAGER ONLY - final approval)
- 'reopen' → "Reopened" (MANAGER ONLY - rejection)

**Role Permissions:**
- Employees: Can mark tasks as 'partial' or 'reported' only
- Managers: Can 'close' (approve) or 'reopen' (reject) tasks

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
- Sort by due date (oldest first)

### TASK ASSIGNMENT BY PHONE:
Support assignment using phone numbers:
- Extract 10-digit number or full format
- Use 'assign_task_by_phone_tool'

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
"""

# --- AUTHORIZED TEAM CONFIGURATION ---
def load_team():
    """Static team directory - source of truth for authentication and name resolution."""
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
    ASSIGNEE: str
    COMMENTS: str = "STATUS_UPDATE"

class GetCountRequest(BaseModel):
    Event: str = "107567"
    Child: List[Dict]

def get_gmail_service():
    """Initialize Gmail API service with OAuth2 credentials from environment variables."""
    try:
        # Load the JSON string from your env variable
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

# --- REST API HELPERS ---
async def call_appsavy_api(key: str, payload: BaseModel) -> Optional[Dict]:
    """Universal wrapper for Appsavy POST requests - 100% API dependency."""
    config = API_CONFIGS[key]
    try:
        res = requests.post(
            config["url"],
            headers=config["headers"],
            json=payload.model_dump(),
            timeout=15
        )
        if res.status_code == 200:
            logger.info(f"API {key} success")
            return res.json()
        logger.error(f"API {key} failed with status {res.status_code}: {res.text}")
        return {"error": res.text}
    except Exception as e:
        logger.error(f"Exception calling API {key}: {str(e)}")
        return None

async def fetch_api_tasks():
    req = GetTasksRequest(Child=[{
        "Control_Id": "106831",
        "AC_ID": "110803",
        "Parent": [{
            "Control_Id": "106825",
            "Value": "Pending,Open,Closed,Partially Closed,Reported Closed,Reopened",
            "Data_Form_Id": ""
        }]
    }])
    
    res = await call_appsavy_api("GET_TASKS", req)
    
    # Enhanced validation
    if not res:
        logger.error("GET_TASKS returned None")
        return []
    
    if isinstance(res, dict) and "error" in res:
        logger.error(f"GET_TASKS API error: {res['error']}")
        return []
    
    if isinstance(res, list):
        logger.info(f"GET_TASKS returned {len(res)} tasks")
        return res
    
    logger.warning(f"GET_TASKS returned unexpected format: {type(res)}")
    return []

async def fetch_task_counts_api(login_code: str):
    """Retrieves aggregate counts via SID 616 - API dependent with robust error handling."""
    req = GetCountRequest(Child=[{
        "Control_Id": "108118",
        "AC_ID": "113229",
        "Parent": [
            {"Control_Id": "111548", "Value": "1", "Data_Form_Id": ""},
            {"Control_Id": "107566", "Value": login_code, "Data_Form_Id": ""},
            {"Control_Id": "107599", "Value": "Assigned By Me", "Data_Form_Id": ""}
        ]
    }])
    
    try:
        res = await call_appsavy_api("GET_COUNT", req)
        
        # Debug logging
        logger.info(f"API Count Response for {login_code}: {res}")
        
        # Handle different response formats
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

# --- AGENT TOOLS (Will be registered dynamically) ---
async def get_performance_report_tool(ctx: RunContext[ManagerContext], name: Optional[str] = None) -> str:
    """
    Generate performance report using API data (SID 616 for counts, SID 610 for task details).
    Without name: Report for ALL employees
    With name: Report for specific employee
    """
    try:
        # Fetch tasks with error handling
        tasks_data = await fetch_api_tasks()
        if not isinstance(tasks_data, list):
            logger.error(f"Unexpected tasks_data format: {type(tasks_data)}")
            tasks_data = []
        
        team = load_team()
        now = ctx.deps.current_time
        
        # Filter team members
        if name:
            display_team = [e for e in team if name.lower() in e['name'].lower() or name.lower() == e['login_code'].lower()]
            if not display_team:
                return f"User '{name}' not found in directory."
        else:
            display_team = team
        
        results = []
        for member in display_team:
            login = member['login_code']
            
            try:
                # Fetch counts from API (SID 616)
                counts = await fetch_task_counts_api(login)
                
                # Calculate pending task breakdown from actual tasks
                member_tasks = [t for t in tasks_data if t.get('LOGIN') == login]
                
                within_time = 0
                beyond_time = 0
                closed_count = 0
                
                for task in member_tasks:
                    status = task.get('STATUS', '').lower()
                    
                    # Count closed tasks
                    if status == 'closed':
                        closed_count += 1
                    
                    # Count pending tasks (not closed)
                    elif status in ['open', 'pending', 'partially closed', 'reported closed', 'reopened', '']:
                        try:
                            due_date_str = task.get('EXPECTED_END_DATE', '')
                            if due_date_str:
                                # Handle both ISO format and other formats
                                due_date_str = due_date_str.replace("Z", "").replace("+00:00", "")
                                due_date = datetime.datetime.fromisoformat(due_date_str)
                                
                                if due_date > now:
                                    within_time += 1
                                else:
                                    beyond_time += 1
                            else:
                                within_time += 1  # No deadline = within time
                        except Exception as date_error:
                            logger.warning(f"Date parsing error for task {task.get('TASK_ID')}: {date_error}")
                            within_time += 1  # Default to within time on error
                
                # Use API counts if available, otherwise use calculated counts
                assigned_count = counts.get('ASSIGNED_TASK', str(len(member_tasks)))
                closed_from_api = counts.get('CLOSED_TASK', str(closed_count))
                
                results.append(
                    f"Name- {member['name'].title()}\n"
                    f"Task Assigned- Count of Task {assigned_count} Nos\n"
                    f"Task Completed- Count of task {closed_from_api} Nos\n"
                    f"Task Pending -\n"
                    f"Within time: {within_time}\n"
                    f"Beyond time: {beyond_time}"
                )
                
            except Exception as member_error:
                logger.error(f"Error processing report for {member['name']}: {str(member_error)}", exc_info=True)
                results.append(
                    f"Name- {member['name'].title()}\n"
                    f"Error: Unable to fetch report data"
                )
        
        if not results:
            return "No team members found for reporting."
        
        return "\n\n".join(results)
        
    except Exception as e:
        logger.error(f"get_performance_report_tool error: {str(e)}", exc_info=True)
        return f"Error generating performance report: {str(e)}"

async def get_task_list_tool(ctx: RunContext[ManagerContext], target_name: Optional[str] = None) -> str:
    """
    Retrieves task list from API (SID 610).
    Without name: Show tasks for requesting user
    With name: Show tasks for specified employee (managers can view others)
    Sort by due date (oldest first - descending order)
    """
    try:
        tasks_data = await fetch_api_tasks()
        team = load_team()
        
        # Identify user
        if target_name:
            # Manager viewing someone else's tasks
            user = next((u for u in team if target_name.lower() in u['name'].lower() or target_name.lower() == u['login_code'].lower()), None)
            if not user:
                return f"User '{target_name}' not found in directory."
        else:
            # User viewing their own tasks
            user = next((u for u in team if u['phone'] == ctx.deps.sender_phone), None)
            if not user:
                return "Unable to identify your profile."
        
        # Filter tasks
        filtered = [t for t in tasks_data if t.get('LOGIN', '').lower() == user['login_code'].lower()]
        
        # Sort by due date (oldest first - descending order by date value)
        filtered.sort(key=lambda x: x.get('EXPECTED_END_DATE', ''), reverse=True)
        
        if not filtered:
            return f"No tasks found for {user['name']}."
        
        output = f"Task List for {user['name'].title()}:\n\n"
        for task in filtered:
            output += (
                f"ID: {task.get('TASK_ID')}\n"
                f"Task: {task.get('TASK_NAME')}\n"
                f"Due: {task.get('EXPECTED_END_DATE')}\n"
                f"Status: {task.get('STATUS')}\n\n"
            )
        
        return output.strip()
        
    except Exception as e:
        logger.error(f"get_task_list_tool error: {str(e)}", exc_info=True)
        return f"Error retrieving task list: {str(e)}"

async def assign_new_task_tool(
    ctx: RunContext[ManagerContext],
    name: str,
    task_name: str,
    deadline: str
) -> str:
    """
    Assigns new task via API (SID 604).
    Sends WhatsApp notification to employee.
    Sends email to both employee and manager.
    Attaches pending documents if available.
    """
    try:
        team = load_team()
        
        # Resolve assignee
        user = next((u for u in team if name.lower() in u['name'].lower() or name.lower() == u['login_code'].lower()), None)
        if not user:
            return f"Error: User '{name}' not found in directory."
        
        login_code = user['login_code']
        
        # No MongoDB, so no pending document handling - assume no document
        doc_payload = Documents(CHILD=[])
        
        # Create task via API
        req = CreateTaskRequest(
            ASSIGNEE=login_code,
            DESCRIPTION=task_name,
            EXPECTED_END_DATE=deadline,
            TASK_NAME=task_name,
            DETAILS=Details(CHILD=[DetailChild(
                LOGIN=login_code,
                PARTICIPANTS=user['name'].upper()
            )]),
            DOCUMENTS=doc_payload
        )
        
        api_response = await call_appsavy_api("CREATE_TASK", req)
        
        if not api_response or isinstance(api_response, dict) and "error" in api_response:
            return "API failure: Task creation was not successful."
        
        # Send WhatsApp notification to employee
        whatsapp_msg = f"New Task Assigned:\n\nTask: {task_name}\nDue Date: {deadline}\n\nPlease complete on time."
        send_whatsapp_message(user['phone'], whatsapp_msg, os.getenv("PHONE_NUMBER_ID"))
        
        # Send email to employee
        email_subject = f"New Task Assigned: {task_name}"
        email_body = f"""Dear {user['name'].title()},

You have been assigned a new task:

Task Name: {task_name}
Due Date: {deadline}

Please ensure timely completion.

Best regards,
Task Management System"""
        
        send_email(user['email'], email_subject, email_body)
        
        # Send email to manager
        manager_subject = f"Task Assignment Confirmation: {task_name}"
        manager_body = f"""Task Assignment Confirmed

Assignee: {user['name'].title()}
Task: {task_name}
Due Date: {deadline}

The task has been successfully assigned and the employee has been notified.

Task Management System"""
        
        send_email(MANAGER_EMAIL, manager_subject, manager_body)
        
        return f"Task successfully assigned to {user['name'].title()} (Login: {login_code}).\nNotifications sent via WhatsApp and email."
        
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
        
        # Normalize phone number
        if len(phone) == 10 and not phone.startswith('91'):
            phone = f"91{phone}"
        
        # Find user by phone
        user = next((u for u in team if u['phone'] == phone), None)
        if not user:
            return f"Error: No employee found with phone number {phone}."
        
        # Use existing assign tool
        return await assign_new_task_tool(ctx, user['name'], task_name, deadline)
        
    except Exception as e:
        logger.error(f"assign_task_by_phone_tool error: {str(e)}", exc_info=True)
        return f"Error assigning task by phone: {str(e)}"

async def update_task_status_tool(
    ctx: RunContext[ManagerContext],
    task_id: str,
    action: str
) -> str:
    try:
        # 1. Updated Map to include 'Open'
        status_map = {
            "open": "Open",
            "partial": "Partially Closed",
            "reported": "Reported Closed",
            "close": "Closed",
            "reopen": "Reopened"
        }
        
        new_status = status_map.get(action.lower())
        if not new_status:
            return f"Error: Invalid action. Use: open, partial, reported, close, reopen"
        
        # 2. Strict Role Validation
        if action.lower() in ["close", "reopen"]:
            if ctx.deps.role != "manager":
                return "Permission Denied: Only managers can Closed or Reopened tasks."
        elif action.lower() in ["open", "partial", "reported"]:
            if ctx.deps.role != "employee":
                return "Note: These statuses are restricted to assigned employees."

        # 3. Fetch current user's login_code to pass as ASSIGNEE
        team = load_team()
        user = next((u for u in team if u['phone'] == ctx.deps.sender_phone), None)
        if not user:
            return "Error: Could not identify your user profile for this update."
        
        # 4. API Request with ASSIGNEE column
        req = UpdateTaskRequest(
            TASK_ID=task_id, 
            STATUS=new_status, 
            ASSIGNEE=user['login_code'] # Passing the login code here
        )
        api_response = await call_appsavy_api("UPDATE_STATUS", req)
        
        if not api_response or (isinstance(api_response, dict) and "error" in api_response):
            return "API failure: Status update could not be completed."
        
        return f"Success: Task {task_id} status updated to '{new_status}'."
        
    except Exception as e:
        logger.error(f"update_task_status_tool error: {str(e)}", exc_info=True)
        return f"Error updating task status: {str(e)}"

# --- ASYNC MESSAGE HANDLER ---
async def handle_message(command, sender, pid, message=None, full_message=None):
    """Main logic entry point for processing WhatsApp messages."""
    
    try:
        if len(sender) == 10 and not sender.startswith('91'):
            sender = f"91{sender}"
        
        # Handle media files - no storage, ask immediately
        msg_type = message.get("type", "text") if message else "text"
        is_media = msg_type in ["document", "image", "video", "audio"]
        
        if is_media and not command:
            send_whatsapp_message(
                sender,
                "File received. Please provide the assignee name, task description, and deadline to complete the assignment.",
                pid
            )
            return
        
        # No history without MongoDB
        
        # Determine user role
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
        
        # Process command with AI agent
        if command:
            try:
                # Get current time and create dynamic system prompt
                current_time = datetime.datetime.now()
                dynamic_prompt = get_system_prompt(current_time)
                
                # Recreate agent with dynamic prompt
                current_agent = Agent(ai_model, deps_type=ManagerContext, system_prompt=dynamic_prompt)
                
                # Register all tools
                current_agent.tool(get_performance_report_tool)
                current_agent.tool(get_task_list_tool)
                current_agent.tool(assign_new_task_tool)
                current_agent.tool(assign_task_by_phone_tool)
                current_agent.tool(update_task_status_tool)
                
                # Run agent (no history)
                result = await current_agent.run(
                    command,
                    deps=ManagerContext(sender_phone=sender, role=role, current_time=current_time)
                )
                
                # Send response
                send_whatsapp_message(sender, result.output, pid)
                
            except Exception as e:
                logger.error(f"Agent execution failed: {str(e)}", exc_info=True)
                send_whatsapp_message(sender, f"System Error: Unable to process request. Please try again or contact support.", pid)
        
    except Exception as e:
        logger.error(f"handle_message error: {str(e)}", exc_info=True)
        send_whatsapp_message(sender, "An unexpected error occurred. Please try again.", pid)
