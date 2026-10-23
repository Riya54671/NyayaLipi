"""
glossary.py
-----------
Glossary lookup: term IDs (from files.term_ids) → [{term, text, hindi}] for the frontend.
Reads from MongoDB `legal_terms`. Supports both new ids (Mongo ObjectId strings)
and old 'kb_XXX' ids from files saved before the migration.
"""

from bson import ObjectId

from database import legal_terms_collection as terms_col


class Glossary:
    def reload(self) -> None:
        """Kept for compatibility; Mongo is always current, nothing to reload."""

    def get_terms_by_ids(self, term_ids: list[str]) -> list[dict]:
        if not term_ids:
            return []
        oids = [ObjectId(t) for t in term_ids if ObjectId.is_valid(t)]
        legacy = [t for t in term_ids if not ObjectId.is_valid(t)]

        query = {"$or": [{"_id": {"$in": oids}}, {"legacy_ids": {"$in": legacy}}]}
        merged: dict[str, dict] = {}
        for d in terms_col.find(query, {"term": 1, "plain_text": 1, "context": 1, "translations": 1}):
            key = d["term"].lower()
            if key not in merged:
                merged[key] = {
                    "term": d["term"],
                    "text": d.get("plain_text") or d.get("context") or "",
                    "hindi": (d.get("translations") or {}).get("hi", ""),
                }
        return list(merged.values())


glossary = Glossary()   # import this one instance everywhere