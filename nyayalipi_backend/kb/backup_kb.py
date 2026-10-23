# kb/backup_kb.py — export collections to dated JSON files (free clusters have no backups)
# Run from nyayalipi_backend/: python kb/backup_kb.py

import os
from datetime import date
from pathlib import Path

from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
db = MongoClient(os.environ["MONGO_URI"])[os.environ["MONGO_DB"]]

out = Path(__file__).resolve().parent / "backups" / date.today().isoformat()
out.mkdir(parents=True, exist_ok=True)

for name in ["legal_terms", "acts_and_laws", "kb_meta", "files"]:
    docs = list(db[name].find())
    (out / f"{name}.json").write_text(json_util.dumps(docs, indent=1), encoding="utf-8")
    print(f"{name}: {len(docs)} documents → {out / (name + '.json')}")

print("\nNote: 'users' is not backed up here because it contains password hashes. "
      "Back it up separately and store it securely if needed.")