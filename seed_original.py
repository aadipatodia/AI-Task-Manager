import os
from pymongo import MongoClient
import certifi
from dotenv import load_dotenv

load_dotenv()


def seed_users():
    """
    Seed initial users directly into MongoDB.
    Each user must have a 'manager_phone' field for hierarchy:
      - If manager_phone == own phone → top-level manager
      - Otherwise → reports to that manager
    """
    MONGO_URI = os.getenv("MONGO_URI")
    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
    db = client['ai_task_manager']
    users_collection = db['users']

    # Define users inline — no external JSON files needed.
    # Add/remove entries here before running.
    original_team = [
        # Example structure (uncomment and edit):
        # {
        #     "name": "aadi",
        #     "email": "patodiaaadi@gmail.com",
        #     "phone": "917428134319",
        #     "login_code": "AADI-001",
        #     "manager_phone": "917428134319"   # self → top-level manager
        # },
        # {
        #     "name": "ankita mishra",
        #     "email": "ankita.mishra@mobineers.com",
        #     "phone": "919871536210",
        #     "login_code": "ANKITA-001",
        #     "manager_phone": "917428134319"   # reports to aadi
        # },
    ]

    for user in original_team:
        # Safety: ensure manager_phone is always present
        if "manager_phone" not in user:
            user["manager_phone"] = user.get("phone", "")

        users_collection.update_one(
            {"phone": user["phone"]},
            {"$set": user},
            upsert=True
        )

    print(f"Seeded {len(original_team)} users to MongoDB (with manager_phone hierarchy)!")


if __name__ == "__main__":
    seed_users()