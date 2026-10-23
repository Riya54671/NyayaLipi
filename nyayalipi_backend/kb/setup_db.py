# kb/setup_db.py — create collections, indexes and kb_meta (safe to re-run)
# Run from nyayalipi_backend/: python kb/setup_db.py

import os
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING

load_dotenv()

db_name = os.environ["MONGO_DB"]          # required: never silently writes to the wrong DB
client = MongoClient(os.environ["MONGO_URI"])
client.admin.command("ping")
db = client[db_name]
print(f"Connected to Atlas, using database: {db_name}")

# Knowledge base
db.legal_terms.create_index([("term_normalized", ASCENDING)], unique=True)
db.legal_terms.create_index([("status", ASCENDING)])
db.legal_terms.create_index([("legacy_ids", ASCENDING)], sparse=True)
db.acts_and_laws.create_index([("act_id", ASCENDING), ("section_number", ASCENDING)], unique=True)
db.acts_and_laws.create_index([("content_hash", ASCENDING)])
db.acts_and_laws.create_index([("in_force", ASCENDING)])
db.kb_meta.update_one({"_id": "kb_version"}, {"$setOnInsert": {"version": 1}}, upsert=True)

# Auth + history (same as database.py, so a fresh DB is fully ready)
db.users.create_index([("email", ASCENDING)], unique=True)
db.users.create_index([("username", ASCENDING)], unique=True)
db.users.create_index([("google_id", ASCENDING)], sparse=True)
db.files.create_index([("user_id", ASCENDING)])

print("Indexes and kb_meta ready")
client.close()