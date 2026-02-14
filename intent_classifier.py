import os
import json
import re
import asyncio
import concurrent.futures
from dotenv import load_dotenv
from google.genai import Client

# Load environment variables
load_dotenv()

MODEL_NAME = "gemini-2.0-flash"

# Dedicated thread pool for blocking Gemini SDK calls (avoids starving default pool)
_classifier_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=20,
    thread_name_prefix="intent-classifier"
)

SUPPORTED_INTENTS = {
    "TASK_ASSIGNMENT",
    "VIEW_EMPLOYEE_PERFORMANCE",
    "VIEW_EMPLOYEES_UNDER_MANAGER",
    "UPDATE_TASK_STATUS",
    "VIEW_PENDING_TASKS",
    "PENDING_TASKS_AMBIGUOUS",
    "ADD_USER",
    "DELETE_USER"
}

INTENT_CLASSIFIER_PROMPT = """
You are an Intent Classification Agent for a Task Management System.

Your task:
- Read the user's message
- Understand what the user wants to do and dont just look for keywords but understand the meaning of the message
- If the message is related to task management:
    - Identify the PRIMARY or MAIN intent
    - Even if multiple actions are mentioned, choose ONE
- Return intent as null ONLY if the request is completely unrelated
  to task management

SUPPORTED INTENTS:
TASK_ASSIGNMENT
VIEW_EMPLOYEE_PERFORMANCE
VIEW_EMPLOYEES_UNDER_MANAGER
UPDATE_TASK_STATUS
VIEW_PENDING_TASKS
PENDING_TASKS_AMBIGUOUS
ADD_USER
DELETE_USER

### **TASK_ASSIGNMENT**

This intent means that the user is assigning a **new task** to an employee.
**Example user messages:**
- "Send this document to [Name] and tell them to [Action]"
- "Ask [Name] to complete a report on this"
- "Forward this to [Name]"
- “Assign the dashboard bug fix to Rahul”
- “Give Neha a task to prepare the monthly report”
- “Create a task for Aman to deploy backend APIs”

**IMPORTANT: When document is sent:**
- Intent determination: "Assign a new task" → TASK_ASSIGNMENT
- Intent determination: "Update status of a task" → UPDATE_TASK_STATUS
- Intent must NEVER be decided based on PDF content
- Intent is ONLY determined from user's explicit message choice

---

### **VIEW_EMPLOYEE_PERFORMANCE**
This intent is triggered when a **manager wants to view the performance** of an employee or their team.
It can include completed tasks, pending tasks, delays, or an overall performance summary for a **specific employee or all employees under the manager**.
**Example user messages:**
* “Show Rahul’s performance”
* “How is Neha performing?”
* “Give me the performance report of my team”
* “Show pending and completed tasks for Aman”
* "Pending tasks for ABC"  
    - **This is an important type of command if user specifies someone's name when and asks pending tasks then it should classify intent as VIEW_EMPLOYEE_PERFORMANCE**
* "Performance summary"
* "Performance Report for ABC"


---

### **VIEW_EMPLOYEES_UNDER_MANAGER**
This intent is used when a **manager wants to see the list of employees who report to them**.
**Example user messages:**
* “Show employees under me”
* “Who are my team members?”
* "Employee list"
* "Who reports to me?"
* "List of my employees"
* "Show my team"
* "List of users"

These are just some examples, but the key is that the user is asking about the employees that directly report to them or are under their management.


---

### **UPDATE_TASK_STATUS**
This intent is triggered when a user wants to **update the status of an existing task**, such as marking it as completed or in progress.
**Example user messages:**
* “Mark the login bug task as completed”
* “Update task status to in progress”
* “I have finished the report task”
* "Mark this task complete based on the document"
* "Upload this evidence and mark task as done"
* “Close the task assigned to me”

**IMPORTANT: When document is sent:**
- Intent determination: "Assign a new task" → TASK_ASSIGNMENT
- Intent determination: "Update status of a task" → UPDATE_TASK_STATUS
- Intent must NEVER be decided based on PDF content
- Intent is ONLY determined from user's explicit message choice

---

### **VIEW_PENDING_TASKS**
This intent is used when the user **clearly states** they want to see **their own** pending tasks.
**Example user messages:**
* "Show my pending tasks"
* "What tasks are still pending for me?"
* "Any unfinished tasks today for me?"
* "Show me my tasks"

**KEY RULE:** This intent should ONLY be used when the user explicitly says "my" or clearly refers to themselves. If it is unclear whose pending tasks they want to see, use PENDING_TASKS_AMBIGUOUS instead.

---

### **PENDING_TASKS_AMBIGUOUS**
This intent is used when the user asks about **pending tasks** but does NOT clearly specify whether they want to see:
- Their OWN pending tasks, OR
- Pending tasks of their TEAM / people under them

**Example user messages (AMBIGUOUS — use this intent):**
* "Pending tasks"
* "List of pending tasks"
* "Show pending tasks"
* "What are the pending tasks?"
* "Any pending tasks?"
* "Tasks that are pending"

**Example user messages (NOT ambiguous — do NOT use this intent):**
* "Show my pending tasks" → VIEW_PENDING_TASKS (clearly says "my")
* "Pending tasks for Rahul" → VIEW_EMPLOYEE_PERFORMANCE (clearly names a person)
* "Show pending tasks of my team" → VIEW_EMPLOYEE_PERFORMANCE (clearly says "team")
* "What are Neha's pending tasks?" → VIEW_EMPLOYEE_PERFORMANCE (clearly names a person)

**RULE:** If the user mentions a specific person's name OR says "my team" / "team" → it is NOT ambiguous. If the user says "my" pending tasks → it is NOT ambiguous. Only use PENDING_TASKS_AMBIGUOUS when there is genuine ambiguity about whose tasks they want.

---

### **ADD_USER**
This intent means the user (usually an admin) wants to **add a new user** to the system.
**Example user messages:**
* “Add a new user named Ankit”
* “Create an employee account for Riya”
* “Add Neha as a manager”
* “Register Aman in the system”

---

### **DELETE_USER**
This intent is triggered when the user wants to **remove or deactivate an existing user** from the system.
**Example user messages:**
* “Delete user Rahul”
* “Remove Aman from the system”
* “Deactivate Neha’s account”

---

### **DOCUMENT_UPLOAD_HANDLING**
The user has a document in context. You MUST categorize their reply:
1. **TASK_ASSIGNMENT**: User wants to create/assign a task (e.g., "Assign it", "New task", "To Rahul").
2. **UPDATE_TASK_STATUS**: User wants to update an existing task (e.g., "Update task", "Proof for task 101").

If the message is brief but a document is present, pick the intent that matches their action. Never return null if the user is making a choice about the document.
---

IT SHOULD BE NOTED THAT ABOVE GIVEN ARE JUST SOME EXAMPLES OF EACH INTENT BUT ARE NOT LIMITED TO THESE


Rules:
- Do NOT invent new intents
- Do NOT return null just because the request is complex
- Mixed actions ≠ unsupported
- Focus on meaning, not keywords

Return STRICT JSON only.

Format:
{
  "intent": "<ONE_INTENT_OR_NULL>",
  "confidence": 0.0,
  "reasoning": "short explanation"

}
"""

# Module-level Gemini client singleton
_gemini_client: Client | None = None

def init_gemini() -> Client:
    global _gemini_client
    if _gemini_client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY missing")
        _gemini_client = Client(api_key=api_key)
    return _gemini_client

def clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json", "", text)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()

def intent_classifier(user_message: str, has_document: bool = False):
    client = init_gemini()

    prompt = INTENT_CLASSIFIER_PROMPT
    if has_document:
        prompt += "\n\nCONTEXT: The user has uploaded a document and is replying to a prompt about it. The intent MUST be either 'TASK_ASSIGNMENT' or 'UPDATE_TASK_STATUS'. Do NOT choose other intents."

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=f"{prompt}\n\nUser message:\n{user_message}"
    )

    cleaned = clean_json(response.text)

    try:
        result = json.loads(cleaned)
        intent = result.get("intent")
        reasoning = result.get("reasoning", "")
        confidence = float(result.get("confidence", 0.0))
    except Exception:
        return False, None, 0.0, "Unable to confidently understand the request."

    # normalize confidence
    confidence = max(0.0, min(confidence, 1.0))

    if intent in SUPPORTED_INTENTS:
        return True, intent, confidence, reasoning

    return False, None, confidence, reasoning


async def async_intent_classifier(user_message: str, has_document: bool = False):
    """Async wrapper that runs intent_classifier in a dedicated thread pool
    instead of the default asyncio executor (which has only ~8 workers)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _classifier_executor,
        intent_classifier,
        user_message,
        has_document
    )


# -----------------------------
# REAL USER INPUT (INTERACTIVE)
# -----------------------------
if __name__ == "__main__":
    print("Task Manager Intent Classifier")
    print("Type 'exit' to quit\n")

    while True:
        user_query = input("User: ").strip()

        if user_query.lower() in ["exit", "quit"]:
            print("Exiting...")
            break

        if not user_query:
            continue

        is_supported, intent, confidence, reasoning = intent_classifier(user_query)

        if not is_supported:
            print(
                "\nI can help with task assignment, task status updates, "
                "viewing tasks or employees, and managing users.\n"
                "Can you please clarify what you want to do?\n"
            )
            continue

        # ✅ JSON ONLY WHEN INTENT IS VALID
        print(json.dumps({
            "intent": intent,
            "confidence": confidence,
            "reasoning": reasoning
        }, indent=2))
        print()
