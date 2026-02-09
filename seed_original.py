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
    original_team = []

    for user in original_team:
        users_collection.update_one(
            {"phone": user["phone"]}, 
            {"$set": user}, 
            upsert=True
        )
    print("Saved in MONGODB!")

if __name__ == "__main__":
    seed_users()