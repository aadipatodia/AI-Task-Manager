import logging
from typing import Optional, Tuple
from redis_session import (
    get_session_history,
    append_message
)
import json
from google.genai import Client
import os

logger = logging.getLogger(__name__)


def get_existing_intent(session_id: str) -> Optional[str]:
    history = get_session_history(session_id)

    for msg in reversed(history):
        if msg["role"] == "system" and "INTENT_SET:" in msg["content"]:
            return msg["content"].replace("INTENT_SET: ", "").strip()

    return None


def last_message_was_shift_clarification(session_id: str) -> bool:
    history = get_session_history(session_id)

    for msg in reversed(history):
        if msg["role"] == "assistant":
            return msg["content"].startswith("[CLARIFY_SHIFT]")
    return False


async def agent3_intent_guard(
    session_id: str,
    user_message: str
) -> Tuple[str, Optional[str]]:
    """
    Returns:
        ("CONTINUE", None)
        ("ASK_CLARIFICATION", message)
        ("RESET", None)
    """

    existing_intent = get_existing_intent(session_id)

    # No intent → start fresh
    if not existing_intent:
        return "RESET", None

    history = get_session_history(session_id)

    # If user is replying to a shift clarification,
    # treat that reply as confirmation → RESET conversation
    if last_message_was_shift_clarification(session_id):
        logger.info("[AGENT3] Clarification answered → RESET")
        return "RESET", None

    # Send only user + assistant messages (hide system/slots)
    history_text = "\n".join(
        f"{m['role']}: {m['content']}"
        for m in history
        if m["role"] in ("user", "assistant")
    )

    client = Client(api_key=os.getenv("GEMINI_API_KEY"))

    prompt = f"""
You are monitoring a professional task-management conversation.

CURRENT ACTIVE REQUEST:
{existing_intent}

FULL CONVERSATION:
{history_text}

NEW USER MESSAGE:
"{user_message}"

Decide:

1) If the user is continuing the same request → return:
CONTINUE

2) If the user appears to be starting a different request:
- Generate a short, natural clarification question.
- Do NOT mention the word "intent".
- Do NOT expose system logic.
- Ask in a professional tone.
- Be conservative. If unsure, return CONTINUE.
- Then return JSON:

{{
  "action": "ASK_CLARIFICATION",
  "message": "your generated question"
}}

Return ONLY:
- CONTINUE
OR
- JSON as shown above
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt
        )

        text = response.text.strip()

        logger.info(f"[AGENT3_DECISION_RAW] {text}")

        # Normalize CONTINUE safely
        if text.strip().upper().startswith("CONTINUE"):
            return "CONTINUE", None

        # Clean possible markdown formatting
        cleaned = (
            text.replace("```json", "")
                .replace("```", "")
                .strip()
        )

        parsed = json.loads(cleaned)

        if parsed.get("action") == "ASK_CLARIFICATION":
            clarification = parsed.get("message", "").strip()

            if clarification:
                append_message(
                    session_id,
                    "assistant",
                    "[CLARIFY_SHIFT] " + clarification
                )
                return "ASK_CLARIFICATION", clarification

    except Exception as e:
        logger.warning(f"[AGENT3_ERROR] {str(e)}")

    # Safe fallback
    logger.warning("[AGENT3_FALLBACK] Defaulting to CONTINUE")
    return "CONTINUE", None