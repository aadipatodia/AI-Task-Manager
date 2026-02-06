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
