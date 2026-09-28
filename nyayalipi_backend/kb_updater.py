"""
kb_updater.py
-------------
Semi-automatic knowledge-base updater for NyayaLipi.

Why semi-automatic: a legal KB feeds the translation prompt, so a wrong
definition becomes a wrong translation. The system finds new terms
automatically; a human approves the definition before it goes live
(human-in-the-loop).

Flow:
  1. scan     → every processed document is scanned for legal phrases
                that are NOT in legal_kb.json → added to pending_terms.json
                with a frequency count and an example sentence.
  2. review   → a person opens pending_terms.json, writes the "text"
                (definition) and sets "status": "approved" (or "rejected").
  3. approve  → approved terms get the next kb_XXX ID and are appended to
                legal_kb.json (validated, backed up, atomic write).
                Returns the new entries so a running RAGPipeline can
                hot-add them via rag.add_entries(new) — no full rebuild.

CLI:
  python kb_updater.py validate            # check legal_kb.json integrity
  python kb_updater.py scan  <file.txt>    # detect candidates in a text file
  python kb_updater.py list                # show pending candidates
  python kb_updater.py approve             # merge approved terms into the KB

In code (e.g. main.py, right after rag.process):
  from kb_updater import record_candidates
  record_candidates(analysis_text)
"""

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR     = Path(__file__).parent
KB_PATH      = BASE_DIR / "legal_kb.json"
NER_PATH     = BASE_DIR / "ner.json"
PENDING_PATH = BASE_DIR / "pending_terms.json"
BACKUP_DIR   = BASE_DIR / "kb_backups"

ID_RE = re.compile(r"^kb_(\d{3,})$")

# Legal "head nouns": a phrase ending in one of these is likely a legal term,
# e.g. "partition deed", "transfer petition", "maintenance order".
HEAD_NOUNS = (
    "deed", "petition", "order", "decree", "notice", "bail", "suit",
    "agreement", "certificate", "warrant", "application", "appeal",
    "award", "clause", "writ", "injunction", "custody", "offence",
    "tribunal", "commission", "lease", "licence", "license", "bond",
)
_HEAD_RE = re.compile(
    r"\b((?:[a-z][a-z\-]+\s){1,2}(?:" + "|".join(HEAD_NOUNS) + r"))\b",
    flags=re.IGNORECASE,
)

# First words that make a phrase generic rather than a term ("the said order")
_STOP_FIRST = {
    "the", "a", "an", "this", "that", "said", "such", "any", "every", "each",
    "his", "her", "their", "its", "our", "your", "my", "no", "of", "in",
    "on", "by", "for", "to", "and", "or", "with", "from", "under", "as",
    "is", "was", "be", "has", "have", "which", "who", "impugned", "above",
    "present", "instant", "same", "further", "other", "first", "second",
    "final", "last", "copy", "filed", "passed", "dated",
}


# ── IO helpers ────────────────────────────────────────────────────────────

def _load(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write to a temp file then rename: a crash can never leave a half-written KB."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def dump_kb(kb: list[dict], path: Path = KB_PATH) -> None:
    """Writes the KB in the original one-entry-per-line style (clean git diffs)."""
    lines = [
        json.dumps({"id": e["id"], "term": e["term"], "text": e["text"]}, ensure_ascii=False)
        .replace('{"', '{ "').replace('"}', '" }')
        for e in kb
    ]
    _atomic_write_text(path, "[\n  " + ",\n  ".join(lines) + "\n]\n")


# ── Validation ────────────────────────────────────────────────────────────

def validate_kb(kb: list[dict]) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings). Errors must be fixed; warnings are informational."""
    errors, warnings = [], []
    seen_ids, seen_terms = set(), {}
    for i, e in enumerate(kb):
        for field in ("id", "term", "text"):
            if not isinstance(e.get(field), str) or not e[field].strip():
                errors.append(f"entry #{i}: missing/empty '{field}'")
        extra = set(e) - {"id", "term", "text"}
        if extra:
            errors.append(f"entry #{i}: unexpected fields {sorted(extra)}")
        eid = e.get("id", "")
        if not ID_RE.match(eid):
            errors.append(f"entry #{i}: bad id format '{eid}' (expected kb_NNN)")
        if eid in seen_ids:
            errors.append(f"duplicate id {eid}")
        seen_ids.add(eid)
        t = e.get("term", "").lower().strip()
        if t in seen_terms:
            warnings.append(f"term '{t}' appears in {seen_terms[t]} and {eid} (merged at lookup)")
        else:
            seen_terms[t] = eid
    return errors, warnings


def next_id(kb: list[dict]) -> str:
    """IDs are permanent and never reused: always max + 1."""
    n = max((int(ID_RE.match(e["id"]).group(1)) for e in kb if ID_RE.match(e["id"])), default=0)
    return f"kb_{n + 1:03d}"


# ── Candidate detection ──────────────────────────────────────────

def _extract_candidate_phrases(text: str) -> list[str]:
    """Finds legal-looking phrases via head-noun regex, filtering generic starts."""
    candidates = []
    for match in _HEAD_RE.finditer(text):
        phrase = match.group(1).strip().lower()
        first_word = phrase.split()[0]
        if first_word in _STOP_FIRST:
            continue
        candidates.append(phrase)
    return candidates


def _example_sentence(text: str, phrase: str, context_chars: int = 80) -> str:
    """Grabs a short snippet of text around the first occurrence of `phrase`."""
    idx = text.lower().find(phrase)
    if idx == -1:
        return phrase
    start = max(0, idx - context_chars)
    end = min(len(text), idx + len(phrase) + context_chars)
    return text[start:end].strip().replace("\n", " ")


def record_candidates(text: str) -> None:
    """
    Scans `text` for legal-looking phrases not already in legal_kb.json,
    and logs them to pending_terms.json for human review.
    Non-fatal by design — callers should wrap this in try/except.
    """
    kb = _load(KB_PATH, [])
    known_terms = {e["term"].lower().strip() for e in kb}

    candidates = _extract_candidate_phrases(text)
    if not candidates:
        return

    pending = _load(PENDING_PATH, {})
    now = datetime.now(timezone.utc).isoformat()

    changed = False
    for phrase in candidates:
        if phrase in known_terms:
            continue  # already a real KB entry

        if phrase in pending:
            pending[phrase]["count"] += 1
            pending[phrase]["last_seen"] = now
        else:
            pending[phrase] = {
                "term": phrase,
                "count": 1,
                "example": _example_sentence(text, phrase),
                "first_seen": now,
                "last_seen": now,
                "status": "pending",
            }
        changed = True

    if changed:
        _atomic_write_text(PENDING_PATH, json.dumps(pending, indent=2, ensure_ascii=False))