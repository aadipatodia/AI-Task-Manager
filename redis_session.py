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

def create_session(session_key: str) -> str:
    counter_key = f"user_session_counter:{session_key}"
    counter = redis_client.incr(counter_key)
    session_id = f"sess{counter:03d}_{session_key}"

    redis_client.set(
        f"user_active_session:{session_key}",
        session_id
    )
    return session_id

def get_or_create_session(session_key: str) -> str:
    session_id = redis_client.get(f"user_active_session:{session_key}")
    if session_id:
        return session_id
    return create_session(session_key)

def append_message(session_id: str, role: str, content: str):
    redis_client.rpush(
        f"session:{session_id}",
        json.dumps({
            "role": role,
            "content": content,
            "ts": datetime.now(IST).isoformat()
        })
    )

def set_pending_task(session_id: str, data: dict, ttl: int = 300):
    redis_client.setex(
        f"pending_task:{session_id}",
        ttl,
        json.dumps(data)
    )
    
def is_performance_locked(key: str) -> bool:
    return redis_client.exists(key)

def lock_performance(key: str, ttl: int = 120):
    redis_client.setex(key, ttl, "1")

def get_pending_task(session_id: str) -> dict | None:
    raw = redis_client.get(f"pending_task:{session_id}")
    return json.loads(raw) if raw else None

def clear_pending_task(session_id: str):
    redis_client.delete(f"pending_task:{session_id}")


def get_agent2_state(session_id: str) -> dict:
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

def get_session_history(session_id: str) -> List[Dict]:
    raw = redis_client.lrange(f"session:{session_id}", 0, -1)
    return [json.loads(x) for x in raw]
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

def reset_session_after_api(session_key: str, session_id: str):

    pipe = redis_client.pipeline()
    # 1. Clear conversation history
    pipe.delete(f"session:{session_id}")
    # 2. Clear pending task (if any)
    pipe.delete(f"pending_task:{session_id}")
    # 3. Clear performance lock (if any)
    pipe.delete(f"performance_lock:{session_id}")
    # 4. Remove active session pointer
    pipe.delete(f"user_active_session:{session_key}")
    pipe.execute()

def end_session_complete(login_code: str, session_id: str):

    try:
        # Clear conversation history
        redis_client.delete(f"session:{session_id}")
        
        # Clear pending task data (if any)
        redis_client.delete(f"pending_task:{session_id}")
        
        # Clear Agent 2 parameter state
        redis_client.delete(f"agent2_state:{session_id}")
        
        # Remove the active session pointer for this user
        redis_client.delete(f"user_active_session:{login_code}")
        
        logger.info(f"Redis cache cleared for user {login_code} (Session: {session_id})")
        return True
    except Exception as e:
        logger.error(f"Failed to clear Redis cache for {login_code}: {e}")
        return False