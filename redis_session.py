import os
import json
import redis
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

# ---------- Timezone ----------
IST = timezone(timedelta(hours=5, minutes=30))

# ---------- Redis Client ----------
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True
)


def create_session(session_key: str) -> str:
    """
    Create a new session ID for a user and mark it as active.
    """
    counter_key = f"user_session_counter:{session_key}"
    counter = redis_client.incr(counter_key)

    # Optional hygiene: auto-expire counter after 30 days
    redis_client.expire(counter_key, 86400 * 30)

    session_id = f"sess{counter:03d}_{session_key}"

    redis_client.set(
        f"user_active_session:{session_key}",
        session_id
    )
    return session_id


def get_or_create_session(session_key: str) -> str:
    """
    Get active session if exists, otherwise create a new one.
    """
    session_id = redis_client.get(f"user_active_session:{session_key}")
    if session_id:
        return session_id
    return create_session(session_key)


def end_session(session_key: str, session_id: str):
    """
    Fully end a user session.
    Clears conversation history, pending task, and active session pointer.
    """
    try:
        redis_client.delete(f"session:{session_id}")
        redis_client.delete(f"pending_task:{session_id}")
        redis_client.delete(f"user_active_session:{session_key}")
    except Exception as e:
        print(f"[REDIS] Failed to end session {session_id}: {e}")


def append_message(session_id: str, role: str, content: str):
    """
    Append a message to session history.
    Empty / None content is ignored to prevent pollution.
    """
    if not content:
        return

    redis_client.rpush(
        f"session:{session_id}",
        json.dumps({
            "role": role,
            "content": content,
            "ts": datetime.now(IST).isoformat()
        })
    )


def get_session_history(session_id: str) -> List[Dict]:
    """
    Retrieve full conversation history for a session.
    """
    raw = redis_client.lrange(f"session:{session_id}", 0, -1)
    return [json.loads(x) for x in raw]

def set_pending_task(session_id: str, data: dict, ttl: int = 300):
    """
    Store partial task data while waiting for clarification.
    """
    redis_client.setex(
        f"pending_task:{session_id}",
        ttl,
        json.dumps(data)
    )


def get_pending_task(session_id: str) -> Optional[dict]:
    """
    Fetch pending task data if exists.
    """
    raw = redis_client.get(f"pending_task:{session_id}")
    return json.loads(raw) if raw else None


def clear_pending_task(session_id: str):
    """
    Remove pending task data.
    """
    redis_client.delete(f"pending_task:{session_id}")


def is_performance_locked(key: str) -> bool:
    """
    Check if a performance-report lock exists.
    Key format is decided by caller (e.g. perf:<login>:<hash>)
    """
    return redis_client.exists(key) == 1


def lock_performance(key: str, ttl: int = 120):
    """
    Lock a performance request to prevent duplicates.
    """
    redis_client.setex(key, ttl, "1")
