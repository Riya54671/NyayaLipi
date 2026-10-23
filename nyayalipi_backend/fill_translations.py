"""
fill_translations.py
--------------------
Offline batch job: generate a target-language rendering for every approved KB term
that lacks one, store it in Mongo (unreviewed), and write a CSV for hand-checking.

Run OUTSIDE the request path (Gemini 503s and latency must never block a translation):

    python fill_translations.py --lang hi --limit 200
    python fill_translations.py --lang mr

Then open translations_review_<lang>.csv, fix wrong entries (the most frequent terms
first), and re-import / edit them in Mongo with reviewed=True.
"""

import argparse
import csv
import random
import time

import kb_store

LANG_NAMES = {
    "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
    "ml": "Malayalam", "bn": "Bengali", "gu": "Gujarati", "pa": "Punjabi",
    "od": "Odia", "as": "Assamese", "ur": "Urdu",
}


def gemini_generate(prompt: str) -> str:
    """Uses the same Gemini client and model kb_updater.py already configures
    (GEMINI_API_KEY / GEMINI_MODEL in .env). Raises on failure so call_with_backoff retries."""
    import kb_updater                       # loads .env and builds kb_updater._client
    if kb_updater._client is None:
        raise RuntimeError("GEMINI_API_KEY is not set (or the Gemini client failed to start).")
    resp = kb_updater._client.models.generate_content(
        model=kb_updater.GEMINI_MODEL, contents=prompt, config={"temperature": 0.0},
    )
    return (resp.text or "").strip()


def build_prompt(term: str, context: str, lang_name: str) -> str:
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


def call_with_backoff(prompt: str, tries: int = 4) -> str:
    for attempt in range(tries):
        try:
            return gemini_generate(prompt)
        except NotImplementedError:
            raise
        except Exception as e:
            if attempt == tries - 1:
                raise
            wait = (2 ** attempt) + random.random()
            print(f"  Gemini error ({e}); retrying in {wait:.1f}s")
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", required=True, help="language key: hi, mr, ta, ...")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    lang_name = LANG_NAMES.get(args.lang, args.lang)
    todo = kb_store.terms_missing_translation(args.lang, limit=args.limit)
    print(f"{len(todo)} approved terms missing a '{args.lang}' translation")

    rows, written = [], 0
    for d in todo:
        term = d["term"]
        context = (d.get("plain_text") or d.get("context") or "")
        try:
            out = call_with_backoff(build_prompt(term, context, lang_name)).strip().strip('"\'')
        except NotImplementedError:
            raise
        except Exception as e:
            print(f"  skipped {term!r}: {e}")
            continue
        if not out or out.upper() == "NONE" or "\n" in out or len(out) > 80:
            print(f"  skipped {term!r}: unusable output {out[:40]!r}")
            continue
        if kb_store.set_translation(term, args.lang, out, source="gemini", reviewed=False):
            written += 1
            rows.append([term, out, d.get("seen_count", 0)])
            print(f"  {term} -> {out}")

    if written:
        kb_store.bump_version()       # one bump for the whole batch -> hot reload picks it up
        path = f"translations_review_{args.lang}.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig opens cleanly in Excel
            w = csv.writer(f)
            w.writerow(["term", f"{args.lang}_translation", "seen_count"])
            w.writerows(sorted(rows, key=lambda r: -r[2]))
        print(f"Wrote {written} translations (unreviewed). Review: {path}")


if __name__ == "__main__":
    main()