"""
kb_store.py
-----------
Single place for all knowledge-base reads/writes in MongoDB.
rag_pipeline, kb_updater and glossary all go through here.
"""

import re
from datetime import datetime, timezone

from database import legal_terms_collection as terms_col, kb_meta_collection as meta_col

# Common English words that must never count as "legal terms": they inflate term density
# (routing) and waste retrieval slots. Used by rag_pipeline (filter at load) and
# kb_updater (reject at auto-add, `purge` command).
# NOTE: 'contract', 'claim', 'deposit' etc. ARE legal words but too common to be useful
# signals on their own. Remove them from the set if you want them counted; multi-word
# entries ("security deposit", "breach of contract") are never filtered.
GENERIC_STOPLIST = {
    "paid", "given", "month", "day", "use", "main", "name", "law", "state",
    "rules", "services", "transfer", "charged", "owner", "property", "signed",
    "agreement", "contract", "claim", "district", "electricity", "apartment",
    "regulations", "deposit","control","act",
}


def now():
    return datetime.now(timezone.utc)


def normalize(term: str) -> str:
    return re.sub(r"\s+", " ", (term or "").strip().lower())


# ── Version (drives hot reload) ───────────────────────────────────────────
def get_version() -> int:
    doc = meta_col.find_one({"_id": "kb_version"}) or {}
    return int(doc.get("version", 0))


def bump_version() -> None:
    meta_col.update_one({"_id": "kb_version"},
                        {"$inc": {"version": 1}, "$set": {"updated_on": now()}}, upsert=True)


# ── Reads ─────────────────────────────────────────────────────────────────
def load_approved_entries() -> list[dict]:
    """Approved terms in the shape the RAG pipeline expects:
    {id, term, text, variants, translations}.
    'text' prefers the plain-language explanation (from legal_kb.json), else the statutory context.
    'translations' is {lang_key: vetted target-language term}, e.g. {"hi": "...", "mr": "..."}."""
    entries = []
    cursor = terms_col.find({"status": "approved"},
                            {"term": 1, "context": 1, "plain_text": 1, "variants": 1, "translations": 1})
    for d in cursor:
        text = (d.get("plain_text") or d.get("context") or "").strip()
        entries.append({
            "id": str(d["_id"]),
            "term": d["term"],
            "text": text or d["term"],
            "variants": d.get("variants") or [],
            "translations": d.get("translations") or {},
        })
    return entries


def known_terms() -> set[str]:
    """Every term the KB has ever seen (approved, pending, rejected) → never re-sent to Gemini."""
    return {d["term_normalized"] for d in terms_col.find({}, {"term_normalized": 1})}


def term_status(term: str) -> str | None:
    """'approved' / 'pending' / 'rejected', or None if the KB has never seen the term."""
    d = terms_col.find_one({"term_normalized": normalize(term)}, {"status": 1})
    return d.get("status") if d else None


def terms_missing_translation(lang: str, limit: int | None = None) -> list[dict]:
    """Approved terms with no vetted translation for `lang` (e.g. 'hi'), most-seen first."""
    key = f"translations.{lang}"
    cursor = terms_col.find(
        {"status": "approved", "$or": [{key: {"$exists": False}}, {key: ""}, {key: None}]},
        {"term": 1, "context": 1, "plain_text": 1, "seen_count": 1},
    ).sort("seen_count", -1)
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


# ── Writes ────────────────────────────────────────────────────────────────
def upsert_term(term: str, *, context: str = "", status: str = "pending", source: str = "gemini",
                hindi: str = "", example: str = "") -> bool:
    """Insert a new term or count another sighting of an existing one.
    Never downgrades an existing term's status or overwrites its definition.
    Returns True if a NEW term was created."""
    norm = normalize(term)
    if not norm:
        return False
    t = now()
    res = terms_col.update_one(
        {"term_normalized": norm},
        {
            "$setOnInsert": {
                "term": term.strip(),
                "lemma": norm,
                "variants": [],
                "context": context,
                "translations": {"hi": hindi} if hindi else {},
                "status": status,
                "source": source,
                "example": example,
                "definitions": [],
                "added_on": t,
            },
            "$inc": {"seen_count": 1},
            "$set": {"last_seen": t},
        },
        upsert=True,
    )
    return res.upserted_id is not None


def set_translation(term: str, lang: str, translation: str, *, source: str = "gemini",
                    reviewed: bool = False, bump: bool = False) -> bool:
    """Store a target-language rendering of `term` for `lang` ('hi', 'mr', ...).
    Provenance goes in translations_meta so unreviewed machine output can be told apart
    from hand-checked entries. Pass bump=True only for a single write; for a batch,
    call bump_version() once at the end (a bump triggers a full KB/FAISS rebuild)."""
    translation = (translation or "").strip()
    if not translation:
        return False
    res = terms_col.update_one(
        {"term_normalized": normalize(term)},
        {"$set": {
            f"translations.{lang}": translation,
            f"translations_meta.{lang}": {"source": source, "reviewed": reviewed, "on": now()},
            "updated_on": now(),
        }},
    )
    if res.matched_count and bump:
        bump_version()
    return res.matched_count > 0


def set_status(term: str, status: str, context: str | None = None) -> bool:
    update = {"status": status, "updated_on": now()}
    if context:
        update["context"] = context
    res = terms_col.update_one({"term_normalized": normalize(term)}, {"$set": update})
    return res.matched_count > 0


def pending_terms(limit: int = 100) -> list[dict]:
    return list(terms_col.find({"status": "pending"},
                               {"term": 1, "context": 1, "source": 1, "seen_count": 1, "example": 1})
                .sort("seen_count", -1).limit(limit))