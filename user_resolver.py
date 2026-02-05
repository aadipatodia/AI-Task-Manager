from typing import Optional, Dict
from pymongo.collection import Collection
import re

def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return "91" + digits
    return digits

def resolve_user_by_phone(
    users_collection: Optional[Collection],
    phone: str
) -> Optional[Dict]:
    if users_collection is None:
        return None

    normalized = normalize_phone(phone)
    return users_collection.find_one({"phone": normalized})