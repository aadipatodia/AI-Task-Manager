from typing import Optional
from pymongo.collection import Collection
import re

def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return "91" + digits
    return digits

def resolve_user_by_phone(
    users_collection: Collection,
    sender_phone: str
) -> Optional[dict]:
    """
    Returns full user document from MongoDB using phone number
    """
    normalized = normalize_phone(sender_phone)
    user = users_collection.find_one(
        {"phone": normalized},
        {"_id": 0}
    )
    return user
