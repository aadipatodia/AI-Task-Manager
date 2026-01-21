import os
from pymongo import MongoClient
import certifi
from dotenv import load_dotenv

load_dotenv()

def seed_users():
    # MongoDB connection setup
    MONGO_URI = os.getenv("MONGO_URI")
    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
    db = client['ai_task_manager']
    users_collection = db['users']

    # Aapka original static data
    original_team = [
        {"name": "mdpvvnl", "phone": "919650523477", "email": "varun.verma@mobineers.com", "login_code": "D-3514-1001"},
        {"name": "chairman", "phone": "91XXXXXXXXX", "email": "example@gmail.com", "login_code": "D-3514-1003"},
        {"name": "mddvvnl", "phone": "917428134319", "email": "patodiaaadi@gmail.com", "login_code": "D-3514-1002"},
        {"name": "ce_ghaziabad", "phone": "91XXXXXXXXXX", "email": "ce@example.com", "login_code": "D-3514-1004"}
    ]

    for user in original_team:
        # update_one with upsert=True duplicate entry se bachata hai
        users_collection.update_one(
            {"phone": user["phone"]}, 
            {"$set": user}, 
            upsert=True
        )
    print("Saved in MONGODB!")

if __name__ == "__main__":
    seed_users()