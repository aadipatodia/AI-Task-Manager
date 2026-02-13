import os
from typing import Optional, Dict, List, Set
from pymongo.collection import Collection
import re
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    phone = str(phone)
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return "91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits


def get_top_manager_phone() -> str:
    """Return the normalized phone of the hierarchy root (from env)."""
    raw = os.getenv("MANAGER_PHONE", "")
    return normalize_phone(raw)


def resolve_user_by_phone(
    users_collection: Optional[Collection],
    phone: str
) -> Optional[Dict]:
    if users_collection is None:
        return None

    normalized = normalize_phone(phone)
    return users_collection.find_one({"phone": normalized}, {"_id": 0})


def resolve_user_by_phone_or_email(users_collection, value: str):
    value = value.strip().lower()

    query = {
        "$or": [
            {"phone": normalize_phone(value)},
            {"email": value}
        ]
    }
    return users_collection.find_one(query, {"_id": 0})


# ─── Hierarchy helpers ───────────────────────────────────────────────

def get_all_subordinates(
    users_collection: Optional[Collection],
    phone: str,
    _visited: Optional[Set[str]] = None
) -> List[Dict]:
    """
    Recursively collect every user below `phone` in the hierarchy.
    Returns a flat list (excludes the user themselves).
    Uses a visited-set to prevent infinite loops from cyclic data.
    """
    if users_collection is None:
        return []

    if _visited is None:
        _visited = set()

    normalized = normalize_phone(phone)
    if normalized in _visited:
        return []
    _visited.add(normalized)

    # Direct reports (excludes self-reference)
    direct = list(users_collection.find(
        {"manager_phone": normalized, "phone": {"$ne": normalized}},
        {"_id": 0}
    ))

    result = list(direct)  # copy
    for child in direct:
        result.extend(
            get_all_subordinates(users_collection, child["phone"], _visited)
        )

    return result


def is_subordinate(
    users_collection: Optional[Collection],
    superior_phone: str,
    target_phone: str
) -> bool:
    """
    Return True if `target_phone` sits anywhere below `superior_phone`
    in the manager→report hierarchy.
    """
    if users_collection is None:
        return False

    sup = normalize_phone(superior_phone)
    tgt = normalize_phone(target_phone)

    if sup == tgt:
        return False  # you are not your own subordinate

    # Top-manager shortcut — they are above everyone
    if sup == get_top_manager_phone():
        return True

    all_subs = get_all_subordinates(users_collection, sup)
    return any(normalize_phone(u["phone"]) == tgt for u in all_subs)


def get_hierarchy_chain(
    users_collection: Optional[Collection],
    phone: str
) -> List[str]:
    """
    Walk upward from `phone` through manager_phone links.
    Returns list of phones from the user up to the root (inclusive).
    """
    if users_collection is None:
        return []

    chain: List[str] = []
    visited: Set[str] = set()
    current = normalize_phone(phone)

    while current and current not in visited:
        visited.add(current)
        chain.append(current)
        user = users_collection.find_one({"phone": current}, {"_id": 0})
        if not user:
            break
        mgr = normalize_phone(user.get("manager_phone", ""))
        if mgr == current:
            break  # self-managed root
        current = mgr

    return chain
