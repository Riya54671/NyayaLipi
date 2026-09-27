"""
MongoDB connection
-------------------
Creates a single shared MongoClient and exposes the `users` and `files`
collections used by the auth system and translation history.

Env vars (see .env):
    MONGO_URI   mongodb+srv://... or mongodb://localhost:27017
    MONGO_DB    database name (default: nyayalipi)
"""

import os
from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB", "nyayalipi")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]

users_collection = db["users"]
files_collection = db["files"]

# ---------------------------------------------------------------------------
# Indexes — run once at import time (idempotent, cheap if already present)
# ---------------------------------------------------------------------------
users_collection.create_index([("email", ASCENDING)], unique=True)
users_collection.create_index([("username", ASCENDING)], unique=True)
users_collection.create_index([("google_id", ASCENDING)], sparse=True)
files_collection.create_index([("user_id", ASCENDING)])