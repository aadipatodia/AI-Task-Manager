import os
from pymongo import MongoClient
import certifi
from dotenv import load_dotenv

load_dotenv()

def clear_entire_database():
    # 1. Get the URI from your environment variables
    MONGO_URI = os.getenv("MONGO_URI")
    
    if not MONGO_URI:
        print("Error: MONGO_URI not found in environment variables.")
        return

    # 2. Initialize the client
    # Using tlsCAFile=certifi.where() as seen in your engine.py
    client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
    
    # 3. Specify the database name
    db_name = 'ai_task_manager'
    
    print(f"Connecting to database: {db_name}...")
    
    # 4. Confirmation step (Safety)
    confirm = input(f"Are you sure you want to PERMANENTLY DELETE all data in '{db_name}'? (yes/no): ")
    
    if confirm.lower() == 'yes':
        try:
            # This drops the entire database, including all collections
            client.drop_database(db_name)
            print(f" Success: Database '{db_name}' has been cleared.")
        except Exception as e:
            print(f"Error occurred: {e}")
    else:
        print("Operation cancelled.")

if __name__ == "__main__":
    clear_entire_database()