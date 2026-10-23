"""
MongoDB connection
-------------------
One shared MongoClient for auth, file history and the legal knowledge base.

Env vars (see .env):
    MONGO_URI   mongodb+srv://...
    MONGO_DB    database name (default: nyayalipi)
    MONGO_TIMEOUT_MS  connection/DNS timeout in ms (default: 15000)
"""

import os
from types import SimpleNamespace

from pymongo import MongoClient, ASCENDING
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB", "nyayalipi")
MONGO_TIMEOUT_MS = int(os.getenv("MONGO_TIMEOUT_MS", "15000"))


# ---------------------------------------------------------------------------
# Fallback stubs: only used if MongoDB is unreachable at startup
# ---------------------------------------------------------------------------
class _FallbackCursor(list):
    def sort(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self


class _FallbackCollection:
    def __init__(self, name: str):
        self.name = name

    def create_index(self, *args, **kwargs):
        return None

    def find_one(self, *args, **kwargs):
        return None

    def find(self, *args, **kwargs):
        return _FallbackCursor()

    def update_one(self, *args, **kwargs):
        return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)

    def insert_one(self, *args, **kwargs):
        return SimpleNamespace(inserted_id=None)

    def bulk_write(self, *args, **kwargs):
        return SimpleNamespace(upserted_count=0, modified_count=0)

    def count_documents(self, *args, **kwargs):
        return 0

    def distinct(self, *args, **kwargs):
        return []

    def aggregate(self, *args, **kwargs):
        return _FallbackCursor()


# ---------------------------------------------------------------------------
# Connect
# ---------------------------------------------------------------------------
try:
    # Longer timeouts: mongodb+srv:// needs a DNS lookup first, which can be slow
    # on campus / mobile networks. On a good network this still connects in <1s.
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=MONGO_TIMEOUT_MS,
        connectTimeoutMS=MONGO_TIMEOUT_MS,
    )
    client.admin.command("ping")          # fail here, clearly, if Atlas is unreachable
    db = client[MONGO_DB_NAME]

    # Auth + history
    users_collection = db["users"]
    files_collection = db["files"]

    # Knowledge base
    legal_terms_collection = db["legal_terms"]
    acts_collection = db["acts_and_laws"]
    kb_meta_collection = db["kb_meta"]

    # -----------------------------------------------------------------------
    # Indexes — idempotent, cheap if already present
    # -----------------------------------------------------------------------
    users_collection.create_index([("email", ASCENDING)], unique=True)
    users_collection.create_index([("username", ASCENDING)], unique=True)
    users_collection.create_index([("google_id", ASCENDING)], sparse=True)
    files_collection.create_index([("user_id", ASCENDING)])

    legal_terms_collection.create_index([("term_normalized", ASCENDING)], unique=True)
    legal_terms_collection.create_index([("status", ASCENDING)])
    legal_terms_collection.create_index([("legacy_ids", ASCENDING)], sparse=True)
    acts_collection.create_index([("act_id", ASCENDING), ("section_number", ASCENDING)], unique=True)
    kb_meta_collection.update_one({"_id": "kb_version"}, {"$setOnInsert": {"version": 1}}, upsert=True)

    print(f"[DB] Connected to MongoDB, database: {MONGO_DB_NAME}")

except Exception as exc:
    print("=" * 70)
    print(f"[DB] WARNING: MongoDB UNAVAILABLE ({exc})")
    print("[DB] Running on IN-MEMORY STUBS: signups/logins/history/KB will NOT work.")
    print("[DB] Check MONGO_URI, password, Atlas IP access list, DNS, and that the cluster isn't paused.")
    print("=" * 70)
    users_collection = _FallbackCollection("users")
    files_collection = _FallbackCollection("files")
    legal_terms_collection = _FallbackCollection("legal_terms")
    acts_collection = _FallbackCollection("acts_and_laws")
    kb_meta_collection = _FallbackCollection("kb_meta")
    client = None
    db = None