# kb/check_kb.py — summary of what's in the KB
# Run from nyayalipi_backend/: python kb/check_kb.py

import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
db = MongoClient(os.environ["MONGO_URI"])[os.environ["MONGO_DB"]]

stats = db.command("dbstats")
meta = db.kb_meta.find_one({"_id": "kb_version"}) or {}

print(f"Database: {os.environ['MONGO_DB']}  |  KB version: {meta.get('version')}")
print(f"Size: data {stats['dataSize']/1e6:.2f} MB, storage {stats['storageSize']/1e6:.2f} MB, "
      f"indexes {stats['indexSize']/1e6:.2f} MB  (free tier limit: 512 MB)")

# Sections
print(f"\nSections: {db.acts_and_laws.count_documents({})} "
      f"(in force: {db.acts_and_laws.count_documents({'in_force': True})}, "
      f"repealed: {db.acts_and_laws.count_documents({'in_force': False})})")
for row in db.acts_and_laws.aggregate([
    {"$group": {"_id": "$act_name", "sections": {"$sum": 1}}},
    {"$sort": {"_id": 1}},
]):
    print(f"  {row['_id']}: {row['sections']}")

# Terms
print(f"\nTerms: {db.legal_terms.count_documents({})}")
print("  by status:")
for row in db.legal_terms.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]):
    print(f"    {row['_id']}: {row['n']}")
print("  by source:")
for row in db.legal_terms.aggregate([{"$group": {"_id": "$source", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]):
    print(f"    {row['_id']}: {row['n']}")
print(f"  defined in 2+ acts: {db.legal_terms.count_documents({'definitions.1': {'$exists': True}})}")
print(f"  with Hindi translation: {db.legal_terms.count_documents({'translations.hi': {'$exists': True, '$ne': ''}})}")
print(f"  with legacy kb_XXX ids: {db.legal_terms.count_documents({'legacy_ids.0': {'$exists': True}})}")
print(f"  pending without definition: "
      f"{db.legal_terms.count_documents({'status': 'pending', 'context': {'$in': ['', None]}})}")

# App data
print(f"\nUsers: {db.users.count_documents({})}  |  Files: {db.files.count_documents({})}")