import os
import json
import redis
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import logging

IST = timezone(timedelta(hours=5, minutes=30))

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Session TTL: auto-expire idle sessions after 30 minutes ───
SESSION_TTL = 1800  # seconds


def create_session(session_key: str) -> str:
    counter_key = f"user_session_counter:{session_key}"
    counter = redis_client.incr(counter_key)
    session_id = f"sess{counter:03d}_{session_key}"

    redis_client.setex(
        f"user_active_session:{session_key}",
        SESSION_TTL,
        session_id
    )
    return session_id

def get_or_create_session(session_key: str) -> str:
    session_id = redis_client.get(f"user_active_session:{session_key}")
    if session_id:
        # Sliding window: refresh TTL on every interaction (single pipeline round-trip)
        pipe = redis_client.pipeline()
        pipe.expire(f"user_active_session:{session_key}", SESSION_TTL)
        pipe.expire(f"session:{session_id}", SESSION_TTL)
        pipe.expire(f"agent2_state:{session_id}", SESSION_TTL)
        pipe.execute()
        return session_id
    return create_session(session_key)

def append_message(session_id: str, role: str, content: str | dict):
    """Append message to session history. Content can be string or dict (for slots)"""
    content_to_store = content if isinstance(content, str) else json.dumps(content)
    
    redis_client.rpush(
        f"session:{session_id}",
        json.dumps({
            "role": role,
            "content": content_to_store,
            "ts": datetime.now(IST).isoformat()
        })
    )
    # Refresh TTL on write
    redis_client.expire(f"session:{session_id}", SESSION_TTL)

def set_pending_document(session_id: str, document_data: dict, ttl: int = 600):
    """
    Store pending document (PDF, image, etc) that was sent by user.
    TTL: 10 minutes by default
    """
    redis_client.setex(
        f"pending_document:{session_id}",
        ttl,
        json.dumps(document_data)
    )

def get_pending_document(session_id: str) -> Optional[dict]:
    """
    Retrieve pending document data if it exists.
    Returns None if document has expired or doesn't exist.
    """
    raw = redis_client.get(f"pending_document:{session_id}")
    if raw:
        return json.loads(raw)
    return None

def clear_pending_document(session_id: str):
    """Clear pending document from Redis"""
    redis_client.delete(f"pending_document:{session_id}")

def set_pending_document_state(session_id: str, is_first_message: bool, ttl: int = 600):
    """
    Tracks if document was sent as FIRST message (intent = null) or after (intent already set)
    """
    redis_client.setex(
        f"pending_doc_state:{session_id}",
        ttl,
        json.dumps({
            "is_first_message": is_first_message,
            "timestamp": datetime.now(IST).isoformat()
        })
    )

def get_pending_document_state(session_id: str) -> Optional[dict]:
    """Retrieves document state info"""
    key = f"pending_doc_state:{session_id}"
    raw = redis_client.get(key)
    if raw:
        return json.loads(raw)
    return None

def clear_pending_document_state(session_id: str):
    """Clears document state after processing"""
    redis_client.delete(f"pending_doc_state:{session_id}")

def get_session_history(session_id: str) -> List[Dict]:
    """Retrieve full conversation history for a session"""
    raw = redis_client.lrange(f"session:{session_id}", 0, -1)
    history = []
    for x in raw:
        try:
            msg = json.loads(x)
            # If content is a JSON string (slots), parse it back to dict
            if msg["role"] == "slots" and isinstance(msg["content"], str):
                try:
                    msg["content"] = json.loads(msg["content"])
                except json.JSONDecodeError:
                    pass
            history.append(msg)
        except json.JSONDecodeError:
            continue
    return history

def set_pending_task(session_id: str, data: dict, ttl: int = 300):
    """Store pending task data temporarily"""
    redis_client.setex(
        f"pending_task:{session_id}",
        ttl,
        json.dumps(data)
    )

def get_pending_task(session_id: str) -> Optional[dict]:
    """Retrieve pending task data"""
    raw = redis_client.get(f"pending_task:{session_id}")
    return json.loads(raw) if raw else None

def clear_pending_task(session_id: str):
    """Clear pending task from Redis"""
    redis_client.delete(f"pending_task:{session_id}")

def is_performance_locked(key: str) -> bool:
    """Check if performance report generation is locked"""
    return redis_client.exists(key)

def lock_performance(key: str, ttl: int = 120):
    """Lock performance report generation for TTL seconds"""
    redis_client.setex(key, ttl, "1")

def get_agent2_state(session_id: str) -> dict:
    """Get current Agent 2 parameter extraction state"""
    raw = redis_client.get(f"agent2_state:{session_id}")
    if raw:
        return json.loads(raw)
    return {
        "intent": None,
        "parameters": {},
        "ready": False
    }

def update_agent2_state(
    session_id: str,
    intent: Optional[str] = None,
    parameters: Optional[dict] = None,
    ready: Optional[bool] = None
) -> dict:
    """Update Agent 2 state incrementally"""
    state = get_agent2_state(session_id)

    if intent is not None:
        state["intent"] = intent

    if parameters is not None:
        state["parameters"].update(parameters)

    if ready is not None:
        state["ready"] = ready

    redis_client.set(
        f"agent2_state:{session_id}",
        json.dumps(state)
    )
    return state

def get_last_message_timestamp(session_id: str) -> Optional[datetime]:
    """Get the timestamp of the most recent message in the session."""
    raw = redis_client.lrange(f"session:{session_id}", -1, -1)
    if raw:
        try:
            msg = json.loads(raw[0])
            return datetime.fromisoformat(msg["ts"])
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return None


def get_inactivity_seconds(session_id: str) -> Optional[float]:
    """Returns seconds since the last message, or None if no history."""
    last_ts = get_last_message_timestamp(session_id)
    if last_ts is None:
        return None
    now = datetime.now(IST)
    return (now - last_ts).total_seconds()


def reset_session_after_api(session_key: str, session_id: str):
    """Reset session after successful API call"""
    pipe = redis_client.pipeline()
    # 1. Clear conversation history
    pipe.delete(f"session:{session_id}")
    # 2. Clear pending task (if any)
    pipe.delete(f"pending_task:{session_id}")
    # 3. Clear performance lock (if any)
    pipe.delete(f"performance_lock:{session_id}")
    # 4. Clear pending document
    pipe.delete(f"pending_document:{session_id}")
    # 5. Clear document state
    pipe.delete(f"pending_doc_state:{session_id}")
    # 6. Clear Agent 2 parameter state
    pipe.delete(f"agent2_state:{session_id}")
    # 7. Remove active session pointer
    pipe.delete(f"user_active_session:{session_key}")
    pipe.execute()

def end_session_complete(login_code: str, session_id: str):
    """Complete cleanup: wipe all session data from Redis"""
    try:
        pipe = redis_client.pipeline()
        
        # Clear conversation history
        pipe.delete(f"session:{session_id}")
        
        # Clear pending task data (if any)
        pipe.delete(f"pending_task:{session_id}")
        
        # Clear pending document
        pipe.delete(f"pending_document:{session_id}")
        
        # Clear document state
        pipe.delete(f"pending_doc_state:{session_id}")
        
        # Clear Agent 2 parameter state
        pipe.delete(f"agent2_state:{session_id}")
        
        # Remove the active session pointer for this user
        pipe.delete(f"user_active_session:{login_code}")
        
        pipe.execute()
        
        logger.info(f"Redis cache cleared for user {login_code} (Session: {session_id})")
        return True
    except Exception as e:
        logger.error(f"Failed to clear Redis cache for {login_code}: {e}")
        return False