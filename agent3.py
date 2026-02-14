import asyncio
import concurrent.futures
import logging
import re
from typing import Optional, Tuple, List, Dict
from redis_session import (
    get_session_history,
    append_message,
    get_inactivity_seconds
)
import json
from google.genai import Client
import os

logger = logging.getLogger(__name__)

# Dedicated thread pool for blocking Gemini SDK calls in Agent 3
_agent3_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=20,
    thread_name_prefix="agent3-gemini"
)

# If user has been inactive for 10+ minutes, auto-reset (likely new conversation)
INACTIVITY_THRESHOLD = 600  # seconds
# Prevent infinite clarification loops
MAX_CLARIFICATIONS = 2

# Module-level Gemini client (avoids re-creation per call)
_gemini_client: Optional[Client] = None

def _get_client() -> Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _gemini_client


# ─── Helper functions (accept pre-fetched history — zero Redis calls) ───

def _get_existing_intent(history: List[Dict]) -> Optional[str]:
    for msg in reversed(history):
        if msg["role"] == "system" and "INTENT_SET:" in msg["content"]:
            return msg["content"].replace("INTENT_SET: ", "").strip()
    return None


def _last_msg_was_shift_clarification(history: List[Dict]) -> bool:
    for msg in reversed(history):
        if msg["role"] == "assistant":
            return msg["content"].startswith("[CLARIFY_SHIFT]")
        if msg["role"] == "user":
            break
    return False


def _count_recent_clarifications(history: List[Dict]) -> int:
    """Count consecutive [CLARIFY_SHIFT] assistant messages (most recent first)."""
    count = 0
    for msg in reversed(history):
        if msg["role"] == "assistant" and msg["content"].startswith("[CLARIFY_SHIFT]"):
            count += 1
        elif msg["role"] == "assistant":
            break
    return count


def _user_denied_shift(user_message: str) -> bool:
    """Detect if user is saying 'no, continue the current task'."""
    negatives = {
        "no", "nope", "nah", "continue", "same", "carry on",
        "no i want to continue", "keep going", "go ahead",
        "same task", "no change", "not a new task"
    }
    stripped = user_message.strip().lower().rstrip(".!?")
    return stripped in negatives or bool(re.match(r'^no[\s,]', stripped))


# ─── Main guard ───

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

    # ★ Single Redis fetch — all helpers reuse this list
    history = get_session_history(session_id)

    existing_intent = _get_existing_intent(history)

    # ── 1. No intent → start fresh ──
    if not existing_intent:
        return "RESET", None

    # ── 2. TIME GAP CHECK — auto-reset stale sessions ──
    inactivity = get_inactivity_seconds(session_id)
    if inactivity is not None and inactivity >= INACTIVITY_THRESHOLD:
        logger.info(
            f"[AGENT3] Inactivity gap of {inactivity:.0f}s "
            f"(threshold {INACTIVITY_THRESHOLD}s) → RESET"
        )
        return "RESET", None

    # ── 3. User replying to a shift clarification ──
    if _last_msg_was_shift_clarification(history):
        if _user_denied_shift(user_message):
            logger.info("[AGENT3] User denied shift → CONTINUE")
            return "CONTINUE", None
        else:
            logger.info("[AGENT3] Clarification answered (shift confirmed) → RESET")
            return "RESET", None

    # ── 4. Max clarification cap ──
    if _count_recent_clarifications(history) >= MAX_CLARIFICATIONS:
        logger.info("[AGENT3] Max clarifications reached → RESET")
        return "RESET", None

    # ── 5. Heuristic fast-path: very short replies are slot-fills ──
    stripped = user_message.strip().lower()
    if len(stripped.split()) <= 2:
        logger.info("[AGENT3] Short reply (likely slot-fill) → CONTINUE")
        return "CONTINUE", None

    # ── 6. LLM-based contextual check ──
    # Reuse the already-fetched history (no extra Redis call)
    history_text = "\n".join(
        f"{m['role']}: {m['content']}"
        for m in history
        if m["role"] in ("user", "assistant")
    )

    client = _get_client()

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
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            _agent3_executor,
            lambda: client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
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