import os
import json
import re
from dotenv import load_dotenv
from google.genai import Client

# Load environment variables
load_dotenv()

MODEL_NAME = "gemini-2.5-pro"

SUPPORTED_INTENTS = {
    "TASK_ASSIGNMENT",
    "VIEW_EMPLOYEE_PERFORMANCE",
    "VIEW_EMPLOYEES_UNDER_MANAGER",
    "UPDATE_TASK_STATUS",
    "VIEW_PENDING_TASKS",
    "ADD_USER",
    "DELETE_USER"
}

INTENT_CLASSIFIER_PROMPT = """
You are an Intent Classification Agent for a Task Management System.

Your task:
- Read the user's message
- Understand what the user wants to do
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
ADD_USER
DELETE_USER

Ahh got it 👍
You want **clean, intent-doc style definitions** — short, precise, *system-level* explanations with examples. No extra fluff. Let’s do it exactly in the format you want 👇

---

### **TASK_ASSIGNMENT**

This intent means that the user is assigning a **new task** to an employee.
**Example user messages:**
* “Assign the dashboard bug fix to Rahul”
* “Give Neha a task to prepare the monthly report”
* “Create a task for Aman to deploy backend APIs”

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
* "Performance summary"
* "Performance Report for ABC"

---

### **VIEW_EMPLOYEES_UNDER_MANAGER**
This intent is used when a **manager wants to see the list of employees who report to them**.
**Example user messages:**
* “Show employees under me”
* “Who are my team members?”
* "Employee list"

---

### **UPDATE_TASK_STATUS**
This intent is triggered when a user wants to **update the status of an existing task**, such as marking it as completed or in progress.
**Example user messages:**
* “Mark the login bug task as completed”
* “Update task status to in progress”
* “I have finished the report task”
* “Close the task assigned to me”

---

### **VIEW_PENDING_TASKS**
This intent is used when a user wants to **view their own pending tasks** or, in the case of a manager, the pending tasks of their team or a specific employee.
**Example user messages:**
* “Show my pending tasks”
* “What tasks are still pending for me?”
* “Any unfinished tasks today for me?”

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


def init_gemini():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY missing")

    return Client(api_key=api_key)

def clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```json", "", text)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()

def intent_classifier(user_message: str):
    client = init_gemini()

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=f"{INTENT_CLASSIFIER_PROMPT}\n\nUser message:\n{user_message}"
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
