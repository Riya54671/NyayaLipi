# kb/migrate_users_files.py — copy users + files from local MongoDB to Atlas, keeping every _id
# Run from nyayalipi_backend/:
#   python kb/migrate_users_files.py --dry-run     (shows what would be copied)
#   python kb/migrate_users_files.py               (actually copies)
# Safe to re-run: documents are upserted by _id, so nothing is duplicated.

import os
import sys

from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne
from pymongo.errors import BulkWriteError

load_dotenv()

OLD_URI = os.getenv("OLD_MONGO_URI", "mongodb://localhost:27017")
OLD_DB = os.getenv("OLD_MONGO_DB", "nyayalipi")
NEW_URI = os.environ["MONGO_URI"]
NEW_DB = os.environ["MONGO_DB"]
COLLECTIONS = ["users", "files"]
DRY_RUN = "--dry-run" in sys.argv

old = MongoClient(OLD_URI, serverSelectionTimeoutMS=5000)
new = MongoClient(NEW_URI, serverSelectionTimeoutMS=10000)
old.admin.command("ping")
new.admin.command("ping")
src, dst = old[OLD_DB], new[NEW_DB]
print(f"Source: {OLD_URI} / {OLD_DB}")
print(f"Target: Atlas / {NEW_DB}")
print("MODE: DRY RUN (nothing will be written)\n" if DRY_RUN else "MODE: COPY\n")

for name in COLLECTIONS:
    docs = list(src[name].find())
    already = dst[name].count_documents({})
    print(f"{name}: {len(docs)} in local DB, {already} already in Atlas")
    if DRY_RUN or not docs:
        continue

    ops = [ReplaceOne({"_id": d["_id"]}, d, upsert=True) for d in docs]
    try:
        res = dst[name].bulk_write(ops, ordered=False)
        print(f"  copied: {res.upserted_count} new, {res.modified_count} updated")
    except BulkWriteError as e:
        details = e.details
        print(f"  copied: {details.get('nUpserted', 0)} new, {details.get('nModified', 0)} updated")
        for err in details.get("writeErrors", [])[:10]:
            # Usually a unique-index clash: someone already signed up on Atlas with the same email/username
            print(f"  CONFLICT: {err.get('errmsg', '')[:160]}")

if not DRY_RUN:
    print("\nVerification:")
    for name in COLLECTIONS:
        print(f"  {name}: local {src[name].count_documents({})}  |  Atlas {dst[name].count_documents({})}")
    orphans = dst.files.count_documents({"user_id": {"$nin": dst.users.distinct("_id")}})
    print(f"  files whose user doesn't exist in Atlas: {orphans}")