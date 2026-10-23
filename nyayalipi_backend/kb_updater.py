"""
kb_updater.py
-------------
Automatic knowledge-base updater for NyayaLipi.

Flow (runs in the background after each translation, see main.py):
  1. Skip documents already scanned this session (hash check).
  2. Regex finds legal-looking phrases (head-noun patterns).
  3. Phrases the KB already knows (approved / pending / rejected) are skipped.
  4. Gemini is called ONCE per document:
       - always, if KB_ALWAYS_ASK_GEMINI=true (catches single-word terms like "estoppel")
       - only when unknown regex candidates exist, if KB_ALWAYS_ASK_GEMINI=false (cheaper)
     It confirms real legal terms and returns a definition + Hindi equivalent (JSON).
  5. Results go to Mongo `legal_terms`:
       - real terms → "approved" if GEMINI_AUTO_APPROVE=true, else "pending"
       - non-terms  → "rejected" (so Gemini is never asked about them again)
  6. If anything was approved, kb_meta.version is bumped → running app hot-reloads.

CLI:
  python kb_updater.py list                 # pending terms, most frequent first
  python kb_updater.py approve "<term>"     # approve one term
  python kb_updater.py approve --all        # approve all pending terms that have a definition
  python kb_updater.py reject "<term>"
  python kb_updater.py enrich               # Gemini writes definitions for pending terms missing one
  python kb_updater.py scan <file.txt>      # run the full flow on a text file
  python kb_updater.py purge [--apply]      # reject generic English words (dry run by default)
  python kb_updater.py translate --lang hi  # Gemini drafts translations for terms lacking one -> review CSV
  python kb_updater.py import-translations <csv> --lang hi   # hand-checked CSV -> reviewed translations
"""

import hashlib
import json
import os
import re
import sys
import argparse
import csv
import random
import time

from dotenv import load_dotenv

import kb_store

load_dotenv()

# ── Settings (.env) ───────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
AUTO_APPROVE = os.getenv("GEMINI_AUTO_APPROVE", "false").lower() == "true"
ALWAYS_ASK_GEMINI = os.getenv("KB_ALWAYS_ASK_GEMINI", "true").lower() == "true"
MAX_CANDIDATES = int(os.getenv("KB_MAX_CANDIDATES", "25"))
MAX_TEXT_CHARS = int(os.getenv("KB_MAX_TEXT_CHARS", "6000"))
MAX_EXTRA_TERMS = int(os.getenv("KB_MAX_EXTRA_TERMS", "10"))

_seen_docs: set[str] = set()   # avoids re-asking Gemini about the same document in one session

_client = None
if GEMINI_API_KEY:
    try:
        from google import genai
        _client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[KB] Gemini client unavailable: {e}")

# ── Candidate detection (head-noun regex) ─────────────────────────────────
HEAD_NOUNS = (
    "deed", "petition", "order", "decree", "notice", "bail", "suit",
    "agreement", "certificate", "warrant", "application", "appeal",
    "award", "clause", "writ", "injunction", "custody", "offence",
    "tribunal", "commission", "lease", "licence", "license", "bond",
)
_HEAD_RE = re.compile(
    r"\b((?:[a-z][a-z\-]+\s){1,2}(?:" + "|".join(HEAD_NOUNS) + r"))\b", flags=re.IGNORECASE)

_STOP_FIRST = {
    "the", "a", "an", "this", "that", "said", "such", "any", "every", "each",
    "his", "her", "their", "its", "our", "your", "my", "no", "of", "in",
    "on", "by", "for", "to", "and", "or", "with", "from", "under", "as",
    "is", "was", "be", "has", "have", "which", "who", "impugned", "above",
    "present", "instant", "same", "further", "other", "first", "second",
    "final", "last", "copy", "filed", "passed", "dated",
}


def extract_candidate_phrases(text: str) -> list[str]:
    out = []
    for m in _HEAD_RE.finditer(text):
        phrase = m.group(1).strip().lower()
        if phrase.split()[0] not in _STOP_FIRST:
            out.append(phrase)
    return list(dict.fromkeys(out))   # dedupe, keep order


def example_sentence(text: str, phrase: str, ctx: int = 80) -> str:
    i = text.lower().find(phrase.lower())
    if i == -1:
        return phrase
    return text[max(0, i - ctx): i + len(phrase) + ctx].strip().replace("\n", " ")


def _valid(term: str) -> bool:
    t = (term or "").strip()
    return bool(t) and t[0].isalpha() and len(t.split()) <= 6 and not re.search(r"[\[\]\*\d{};]", t)


# ── Gemini (one call per document) ────────────────────────────────────────
_PROMPT = """You are an expert in Indian law. Below is text from a legal document and a list of
candidate phrases found in it.

For EACH candidate, decide whether it is a genuine legal term or concept (not a generic phrase).
Also add up to {max_extra} OTHER genuine legal terms from the text that are not in the candidate list
(single words like "estoppel" or phrases like "res judicata" both count).

For every genuine legal term give:
- a concise plain-English definition (1–2 sentences, Indian legal context)
- its standard Hindi legal equivalent (Devanagari)

Return ONLY JSON in exactly this shape:
{{"terms": [{{"term": "...", "is_legal_term": true, "definition": "...", "hindi": "..."}}]}}
For candidates that are not legal terms, include them with "is_legal_term": false and empty strings.

CANDIDATES:
{candidates}

TEXT:
{text}
"""


_TRANSIENT = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded", "high demand")


def _generate_with_backoff(tries: int = 4, **kwargs):
    """generate_content with exponential backoff on busy/rate-limit errors only."""
    for attempt in range(tries):
        try:
            return _client.models.generate_content(**kwargs)
        except Exception as e:
            if attempt == tries - 1 or not any(m in str(e) for m in _TRANSIENT):
                raise
            wait = (2 ** attempt) + random.random()
            print(f"[KB] Gemini busy ({str(e)[:60]}); retrying in {wait:.1f}s")
            time.sleep(wait)


def _ask_gemini(text: str, candidates: list[str]) -> list[dict]:
    prompt = _PROMPT.format(
        max_extra=MAX_EXTRA_TERMS,
        candidates="\n".join(f"- {c}" for c in candidates) or "- (none)",
        text=text[:MAX_TEXT_CHARS],
    )
    resp = _generate_with_backoff(
        model=GEMINI_MODEL, contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0.1},
    )
    raw = (resp.text or "").strip().removeprefix("```json").removesuffix("```").strip()
    data = json.loads(raw)
    return data.get("terms", []) if isinstance(data, dict) else []


# ── Main entry point (called from main.py as a background task) ────────────
def process_document(english_text: str, matched_terms: list[str] | None = None) -> None:
    """Non-fatal: any failure is logged and the user's request is unaffected."""
    try:
        if not english_text or not english_text.strip():
            return

        doc_hash = hashlib.sha256(english_text.encode("utf-8")).hexdigest()
        if doc_hash in _seen_docs:
            print("[KB] Same document already scanned this session — Gemini not called.")
            return
        _seen_docs.add(doc_hash)

        known = kb_store.known_terms()
        unknown = [p for p in extract_candidate_phrases(english_text)
                   if kb_store.normalize(p) not in known][:MAX_CANDIDATES]

        if not unknown and not ALWAYS_ASK_GEMINI:
            print("[KB] No unknown candidates — Gemini not called.")
            return

        if not _client:
            for p in unknown:   # no key: still log for manual review
                kb_store.upsert_term(p, status="pending", source="regex",
                                     example=example_sentence(english_text, p))
            print(f"[KB] {len(unknown)} candidates logged as pending (no GEMINI_API_KEY).")
            return

        results = _ask_gemini(english_text, unknown)

        approved = pending = rejected = skipped = 0
        for r in results:
            term = (r.get("term") or "").strip()
            if not _valid(term):
                continue
            norm = kb_store.normalize(term)
            if norm in known:          # Gemini returned something the KB already has
                skipped += 1
                continue
            known.add(norm)            # avoid double-counting duplicates within one response

            if norm in kb_store.GENERIC_STOPLIST:   # generic English word: never a KB term, never ask again
                if kb_store.upsert_term(term, status="rejected", source="stoplist"):
                    rejected += 1
                continue

            definition = (r.get("definition") or "").strip()
            if r.get("is_legal_term") and definition:
                status = "approved" if AUTO_APPROVE else "pending"
                created = kb_store.upsert_term(
                    term, context=definition, status=status, source="gemini",
                    hindi=(r.get("hindi") or "").strip(),
                    example=example_sentence(english_text, term),
                )
                if created:
                    if status == "approved":
                        approved += 1
                    else:
                        pending += 1
            else:
                if kb_store.upsert_term(term, status="rejected", source="gemini"):
                    rejected += 1

        if approved:
            kb_store.bump_version()
        print(f"[KB] Gemini: +{approved} approved, +{pending} pending, "
              f"+{rejected} rejected, {skipped} already known")
    except Exception as e:
        print(f"[KB] process_document failed (non-fatal): {e}")


# ── CLI ───────────────────────────────────────────────────────────────────
def _cmd_list():
    rows = kb_store.pending_terms(200)
    print(f"{len(rows)} pending terms:")
    for r in rows:
        has_def = "✓" if r.get("context") else "✗ (no definition)"
        print(f"  [{r.get('seen_count', 1):>3}x] {r['term']:<40} {r.get('source', ''):<8} {has_def}")


def _cmd_approve(args):
    if args and args[0] == "--all":
        n = 0
        for r in kb_store.pending_terms(10_000):
            if r.get("context") and kb_store.set_status(r["term"], "approved"):
                n += 1
        if n:
            kb_store.bump_version()
        print(f"Approved {n} terms (terms without a definition were skipped; run 'enrich' first).")
    elif args:
        if kb_store.set_status(args[0], "approved"):
            kb_store.bump_version()
            print(f"Approved: {args[0]}")
        else:
            print(f"Not found: {args[0]}")
    else:
        print('Usage: python kb_updater.py approve "<term>"  |  approve --all')


def _cmd_reject(args):
    if not args:
        print('Usage: python kb_updater.py reject "<term>"')
        return
    print(f"Rejected: {args[0]}" if kb_store.set_status(args[0], "rejected") else f"Not found: {args[0]}")


def _cmd_enrich():
    """Ask Gemini for definitions of pending terms that have none (batched, 40 per call)."""
    if not _client:
        print("GEMINI_API_KEY not set.")
        return
    todo = [r["term"] for r in kb_store.pending_terms(10_000) if not r.get("context")]
    print(f"{len(todo)} pending terms need definitions")
    for i in range(0, len(todo), 40):
        batch = todo[i:i + 40]
        try:
            results = _ask_gemini("(no document; define each candidate)", batch)
        except Exception as e:
            print(f"  batch {i // 40 + 1} failed: {e}")
            continue
        for r in results:
            term = (r.get("term") or "").strip()
            if r.get("is_legal_term") and (r.get("definition") or "").strip():
                kb_store.set_status(term, "pending", context=r["definition"].strip())
            elif term:
                kb_store.set_status(term, "rejected")
        print(f"  batch {i // 40 + 1}: {len(results)} processed")


# ── Offline maintenance commands (never in the request path) ──────────────
LANG_NAMES = {
    "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
    "ml": "Malayalam", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi",
    "od": "Odia", "as": "Assamese", "ur": "Urdu",
}


def _translation_prompt(term: str, context: str, lang_name: str) -> str:
    return (
        f"Give the standard {lang_name} equivalent of the English legal term below, as used in "
        f"Indian statutes and courts (prefer the official legal glossary terminology, e.g. the "
        f"Commission for Scientific and Technical Terminology / Legislative Department usage, "
        f"over a literal word-for-word rendering).\n\n"
        f"Term: {term}\n"
        f"Meaning (for disambiguation only): {context[:300]}\n\n"
        f"Rules: answer with ONLY the {lang_name} term, in {lang_name} script, no explanation, "
        f"no transliteration in brackets, no quotes. If the term has no established {lang_name} "
        f"legal equivalent, answer exactly: NONE"
    )


def _cmd_purge(args):
    """Reject generic English words (kb_store.GENERIC_STOPLIST). Rejected, not deleted, so
    known_terms() keeps them from being re-added. Dry run unless --apply."""
    ap = argparse.ArgumentParser(prog="kb_updater.py purge")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(args)
    hits = []
    for t in sorted(kb_store.GENERIC_STOPLIST):
        status = kb_store.term_status(t)
        if status in ("approved", "pending"):
            hits.append((t, status))
    print(f"{len(hits)} generic term(s) currently live in the KB:")
    for t, status in hits:
        print(f"  {t}  ({status})")
    if not a.apply:
        print("Dry run only. Re-run with --apply to reject them.")
        return
    for t, _ in hits:
        kb_store.set_status(t, "rejected")
    if hits:
        kb_store.bump_version()
        print("Rejected; KB version bumped, RAG reloads in the background.")


def _cmd_translate(args):
    """Gemini drafts a target-language rendering for approved terms that lack one. Stored
    UNREVIEWED; a CSV is written for hand-checking. (New terms already get a Hindi
    equivalent from process_document; this fills gaps and other languages.)"""
    ap = argparse.ArgumentParser(prog="kb_updater.py translate")
    ap.add_argument("--lang", required=True, help="language key: hi, mr, ta, ...")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(args)
    if not _client:
        print("GEMINI_API_KEY not set.")
        return
    lang_name = LANG_NAMES.get(a.lang, a.lang)
    todo = kb_store.terms_missing_translation(a.lang, limit=a.limit)
    print(f"{len(todo)} approved terms missing a '{a.lang}' translation")
    rows = []
    for d in todo:
        term = d["term"]
        context = d.get("plain_text") or d.get("context") or ""
        try:
            resp = _generate_with_backoff(
                model=GEMINI_MODEL, contents=_translation_prompt(term, context, lang_name),
                config={"temperature": 0.0},
            )
            out = (resp.text or "").strip().strip("\"'")
        except Exception as e:
            print(f"  skipped {term!r}: {e}")
            continue
        if not out or out.upper() == "NONE" or "\n" in out or len(out) > 80:
            print(f"  skipped {term!r}: unusable output {out[:40]!r}")
            continue
        if kb_store.set_translation(term, a.lang, out, source="gemini", reviewed=False):
            rows.append([term, out, d.get("seen_count") or 0])
            print(f"  {term} -> {out}")
    if rows:
        kb_store.bump_version()          # one bump for the whole batch
        path = f"translations_review_{a.lang}.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig opens cleanly in Excel
            w = csv.writer(f)
            w.writerow(["term", f"{a.lang}_translation", "seen_count"])
            w.writerows(sorted(rows, key=lambda r: -r[2]))
        print(f"Wrote {len(rows)} unreviewed translations. Hand-check {path}, then run:\n"
              f"  python kb_updater.py import-translations {path} --lang {a.lang}")


def _cmd_import_translations(args):
    """Import a hand-checked CSV as REVIEWED, human-sourced translations. Every row left in
    the file counts as reviewed: delete rows you did not check; an empty cell skips the term."""
    ap = argparse.ArgumentParser(prog="kb_updater.py import-translations")
    ap.add_argument("csv_path")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(args)
    col = f"{a.lang}_translation"
    done = skipped = missing = 0
    with open(a.csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if "term" not in (reader.fieldnames or []) or col not in reader.fieldnames:
            raise SystemExit(f"CSV needs columns 'term' and '{col}'; found {reader.fieldnames}")
        for row in reader:
            term = (row.get("term") or "").strip()
            tr = (row.get(col) or "").strip()
            if not term or not tr:
                skipped += 1
            elif a.dry_run:
                print(f"  would set {term!r} -> {tr!r}")
                done += 1
            elif kb_store.set_translation(term, a.lang, tr, source="human", reviewed=True):
                done += 1
            else:
                missing += 1
                print(f"  term not found in KB: {term!r}")
    print(f"{'Would import' if a.dry_run else 'Imported'} {done}; skipped {skipped} empty; {missing} not found")
    if done and not a.dry_run:
        kb_store.bump_version()
        print("KB version bumped; RAG reloads in the background.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "list":
        _cmd_list()
    elif cmd == "approve":
        _cmd_approve(args)
    elif cmd == "reject":
        _cmd_reject(args)
    elif cmd == "enrich":
        _cmd_enrich()
    elif cmd == "purge":
        _cmd_purge(args)
    elif cmd == "translate":
        _cmd_translate(args)
    elif cmd == "import-translations":
        _cmd_import_translations(args)
    elif cmd == "scan" and args:
        with open(args[0], encoding="utf-8") as f:
            process_document(f.read())
    else:
        print(__doc__)