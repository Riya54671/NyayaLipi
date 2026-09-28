"""
glossary.py
-----------
Glossary lookup: term IDs (from files.term_ids) → [{term, text}] for the frontend.
Reads directly from legal_kb.json — no separate Mongo glossary collection.
"""

import json
from pathlib import Path

KB_PATH = Path(__file__).parent / "legal_kb.json"


class Glossary:
    def __init__(self, kb_path: Path = KB_PATH):
        self.kb_path = kb_path
        self.reload()

    def reload(self) -> None:
        """Load KB into a dict keyed by id → O(1) lookup per term."""
        with open(self.kb_path, encoding="utf-8") as f:
            kb = json.load(f)
        self.by_id = {e["id"]: e for e in kb}

    def get_terms_by_ids(self, term_ids: list[str]) -> list[dict]:
        """
        ["kb_052", "kb_121", "kb_031"] → [{"term": "lessor", "text": "..."}, {"term": "injunction", ...}]
        Duplicate terms (same term, two IDs) are merged into one entry.
        Unknown IDs are skipped.
        """
        merged: dict[str, dict] = {}
        for tid in term_ids:
            entry = self.by_id.get(tid)
            if not entry:
                continue
            key = entry["term"].lower()
            if key in merged:
                if entry["text"] not in merged[key]["text"]:
                    merged[key]["text"] += " " + entry["text"]
            else:
                merged[key] = {"term": entry["term"], "text": entry["text"]}
        return list(merged.values())


glossary = Glossary()   # import this one instance everywhere