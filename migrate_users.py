"""
One-time migration script: Backfill 'manager_phone' field for existing MongoDB users.

Works entirely from MongoDB — no external JSON files needed.

For any user that is missing 'manager_phone', it sets manager_phone = their
own phone (making them a self-managed / top-level manager).

If you need to assign specific users to specific managers, update them
directly in MongoDB after running this script:
    db.users.updateOne({phone: "91XXXXXXXXXX"}, {$set: {manager_phone: "91YYYYYYYYYY"}})

Run once:
    python migrate_users.py
"""

import re
from pymongo import MongoClient
import certifi
import os
from dotenv import load_dotenv

load_dotenv()


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        return "91" + digits
    elif len(digits) == 12 and digits.startswith("91"):
        return digits
    return digits


def migrate():
    MONGO_URI = os.getenv("MONGO_URI")
    if not MONGO_URI:
        print("ERROR: MONGO_URI not set in .env")
        return

    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
    db = client["ai_task_manager"]
    users_collection = db["users"]

    # For any user in MongoDB that has NO manager_phone field at all,
    # set manager_phone = their own phone (top-level / self-managed)
    orphan_result = users_collection.update_many(
        {"manager_phone": {"$exists": False}},
        [{"$set": {"manager_phone": "$phone"}}],
    )

    updated = orphan_result.modified_count
    if updated:
        print(f"  Set self-managed (manager_phone = own phone) for {updated} user(s)")

    # Also normalize any existing manager_phone values
    all_users = list(users_collection.find({}, {"_id": 0, "phone": 1, "name": 1, "manager_phone": 1}))
    normalized_count = 0
    for user in all_users:
        mp = user.get("manager_phone", "")
        normalized = normalize_phone(mp)
        if normalized and normalized != mp:
            users_collection.update_one(
                {"phone": user["phone"]},
                {"$set": {"manager_phone": normalized}},
            )
            normalized_count += 1

    if normalized_count:
        print(f"  Normalized manager_phone format for {normalized_count} user(s)")

    total = len(all_users)
    print(f"\nMigration complete: {total} total users, {updated} backfilled, {normalized_count} normalized")


if __name__ == "__main__":
    migrate()
