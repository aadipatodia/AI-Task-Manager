from typing import Optional, Dict
from pymongo.collection import Collection
import re

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
