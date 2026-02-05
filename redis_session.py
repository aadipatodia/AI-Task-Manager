import os
import json
import redis
from datetime import datetime, timezone, timedelta
from typing import List, Dict

IST = timezone(timedelta(hours=5, minutes=30))

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True
)

def create_session(login_code: str) -> str:
    counter_key = f"user_session_counter:{login_code}"
    counter = redis_client.incr(counter_key)
    session_id = f"sess{counter:03d}_{login_code}"
    redis_client.set(
        f"user_active_session:{login_code}",
        session_id
    )
    return session_id

def get_or_create_session(login_code: str) -> str:
    session_id = redis_client.get(f"user_active_session:{login_code}")
    if session_id:
        return session_id
    return create_session(login_code)


def append_message(session_id: str, role: str, content: str):
    redis_client.rpush(
        f"session:{session_id}",
        json.dumps({
            "role": role,
            "content": content,
            "ts": datetime.now(IST).isoformat()
        })
    )

def get_session_history(session_id: str) -> List[Dict]:
    raw = redis_client.lrange(f"session:{session_id}", 0, -1)
    return [json.loads(x) for x in raw]

def end_session(login_code: str, session_id: str):
    """
    End the active Redis session for a user
    """
    try:
        # delete session messages
        redis_client.delete(f"session:{session_id}")

        # delete active session pointer
        redis_client.delete(f"user_active_session:{login_code}")

    except Exception as e:
        print(f"[REDIS] Failed to end session {session_id}: {e}")
