"""
rag_pipeline.py
---------------
RAG Layer — responsibility is ONLY:
  1. InLegal NER         → structural entities (courts, acts, sections...) from in-code patterns
  2. Aho-Corasick        → legal terms from the MongoDB knowledge base
  3. FAISS               → retrieve English context per matched term
  4. build_system_prompt → return prompt string to translator.py

The KB is loaded from Mongo (approved terms only) and hot-reloaded in a
background thread whenever kb_meta.version changes — no restart needed.
"""

import os
import re
import threading
import time
from pathlib import Path

import pickle
import ahocorasick
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from concurrent.futures import ThreadPoolExecutor
from timing import timed
from masking import mask_sensitive_terms

import kb_store
from kb_store import GENERIC_STOPLIST

BASE_DIR = Path(__file__).parent
MODEL_NAME = "all-MiniLM-L6-v2"
KB_REFRESH_SECONDS = int(os.getenv("KB_REFRESH_SECONDS", "60"))
FAISS_CACHE_DIR = BASE_DIR / "faiss_cache"
FAISS_CACHE_DIR.mkdir(exist_ok=True, parents=True)


# ══════════════════════════════════════════════════════════════════════════════
#  0. GENERIC-WORD FILTER
#  Common English words that must never count as "legal terms": they inflate
#  term density (routing) and waste the max_terms retrieval slots. Applied once
#  at KB load, so Aho-Corasick, FAISS, routing and prompts all see the clean KB.
#  The real fix is also to purge these from the legal_terms collection and gate
#  the Gemini auto-add path (yes/no "is this a legal term of art?").
# ══════════════════════════════════════════════════════════════════════════════

# GENERIC_STOPLIST lives in kb_store.py (shared with kb_updater.py).

def filter_generic(kb: list[dict]) -> list[dict]:
    kept = [e for e in kb if e["term"].lower().strip() not in GENERIC_STOPLIST]
    dropped = len(kb) - len(kept)
    if dropped:
        print(f"[RAG] Filtered {dropped} generic terms from KB")
    return kept


def _specificity(term: str) -> tuple[int, int]:
    """Rank terms so multi-word / longer (more specific) ones are retrieved first."""
    return (len(term.split()), len(term))


# ══════════════════════════════════════════════════════════════════════════════
#  1. NER PATTERNS (structural regexes — code, not data, so they live here)
# ══════════════════════════════════════════════════════════════════════════════

NER_PATTERNS = {
    "COURT": [r"\bSupreme Court\b", r"\bHigh Court\b", r"\bDistrict Court\b",
              r"\bSessions Court\b", r"\bMagistrate Court\b", r"\bTribunal\b"],
    "SECTION": [r"\bSection\s+\d+[A-Za-z]?\b", r"\bArticle\s+\d+\b",
                r"\bClause\s+\d+\b", r"\bRule\s+\d+\b"],
    "ACT": [r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+Act(?:,\s*\d{4})?\b",
            r"\bIPC\b", r"\bCrPC\b", r"\bCPC\b"],
    "CASE_REF": [r"\bAIR\s+\d{4}\s+[A-Z]+\s+\d+\b", r"\b\(\d{4}\)\s+\d+\s+SCC\s+\d+\b"],
    "PERSON_ROLE": [r"\bpetitioner\b", r"\brespondent\b", r"\bappellant\b",
                    r"\bdefendant\b", r"\bplaintiff\b", r"\baccused\b", r"\bcomplainant\b"],
    # DATE is intentionally absent: NER runs on masked text, where dates are already
    # [[DATE_n]] tokens, so a date pattern here could never fire.
}

# Honorific list must match masking.py's name pattern — update both together.
NAME_PATTERN = re.compile(
    r"\b(?:Mr\.?|Mrs\.?|Ms\.?|Shri\.?|Smt\.?|Sau\.?|Kum\.?|Dr\.?|Adv\.?)\s+"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b"
)


class InLegalNER:
    def __init__(self, patterns: dict[str, list[str]]):
        # ACT patterns rely on capitalisation ("Maharashtra Rent Control Act"). With
        # IGNORECASE, [A-Z][a-z]+ matches ANY word, so the pattern would swallow a whole
        # run of words ending in "act" (e.g. half a sentence). Keep ACT case-sensitive.
        self.patterns = {label: [re.compile(p, 0 if label == "ACT" else re.IGNORECASE) for p in regexes]
                         for label, regexes in patterns.items()}

    def extract(self, text: str) -> dict[str, list[str]]:
        entities: dict[str, list[str]] = {}
        for label, compiled_list in self.patterns.items():
            seen, unique = set(), []
            for pattern in compiled_list:
                for match in pattern.findall(text):
                    clean = match.strip() if isinstance(match, str) else " ".join(match).strip()
                    if clean and clean.lower() not in seen:
                        seen.add(clean.lower())
                        unique.append(clean)
            if unique:
                entities[label] = unique
        return entities


# ══════════════════════════════════════════════════════════════════════════════
#  2. AHO-CORASICK MATCHER (terms + variants from Mongo)
# ══════════════════════════════════════════════════════════════════════════════

class AhoCorasickMatcher:
    """Whole-word matching; variants (e.g. 'cognisable' / 'cognizable') map to the same term."""

    _NOUN_CONTEXT = {
        "will": {"a", "the", "his", "her", "their", "its", "last", "said",
                 "registered", "valid", "this", "such", "earlier", "unregistered"},
    }

    def __init__(self, kb: list[dict]):
        self.term_to_ids: dict[str, list[str]] = {}
        self.display: dict[str, str] = {}
        for entry in kb:
            main = entry["term"].lower().strip()
            for key in [main] + [v.lower().strip() for v in entry.get("variants", []) if v]:
                self.term_to_ids.setdefault(key, []).append(entry["id"])
                self.display.setdefault(key, entry["term"])

        self.automaton = ahocorasick.Automaton()
        for key in self.term_to_ids:
            self.automaton.add_word(key, key)
        self.empty = len(self.term_to_ids) == 0
        if not self.empty:
            self.automaton.make_automaton()
        print(f"[RAG] Aho-Corasick built with {len(self.term_to_ids)} keys.")

    @staticmethod
    def _is_word_char(c: str) -> bool:
        return c.isalnum() or c == "_"

    def find_terms(self, text: str) -> list[str]:
        if self.empty:
            return []
        lower = text.lower()
        found: dict[str, None] = {}
        for end, key in self.automaton.iter(lower):
            start = end - len(key) + 1
            if start > 0 and self._is_word_char(lower[start - 1]):
                continue
            if end + 1 < len(lower) and self._is_word_char(lower[end + 1]):
                continue
            ctx = self._NOUN_CONTEXT.get(key)
            if ctx is not None:
                prev = lower[:start].split()
                if not prev or prev[-1].strip(".,;:'\"()") not in ctx:
                    continue
            found.setdefault(self.display[key], None)
        return list(found)


# ══════════════════════════════════════════════════════════════════════════════
#  3. FAISS INDEX
# ══════════════════════════════════════════════════════════════════════════════

def cleanup_old_faiss_caches(cache_dir: Path, keep_version: int) -> None:
    """Delete faiss_v*.index / .meta.pkl files for versions other than keep_version."""
    for p in Path(cache_dir).glob("faiss_v*"):
        m = re.match(r"faiss_v(\d+)\.", p.name)
        if m and int(m.group(1)) != keep_version:
            try:
                p.unlink()
            except OSError as e:
                print(f"[RAG] Could not remove old cache {p.name}: {e}")


class FAISSLegalIndex:
    def __init__(self, kb: list[dict], model: SentenceTransformer, version: int = None, cache_dir: Path = None):
        self.kb = kb
        self.model = model
        if cache_dir is None:
            cache_dir = FAISS_CACHE_DIR
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(exist_ok=True, parents=True)
        texts = [e["text"] for e in kb]
        if not texts:
            self.index = None
            print("[RAG] FAISS: KB empty, index not built.")
            return

        cache_path = (cache_dir / f"faiss_v{version}.index") if (cache_dir and version is not None) else None
        meta_path = (cache_dir / f"faiss_v{version}.meta.pkl") if (cache_dir and version is not None) else None

        if cache_path and cache_path.exists() and meta_path and meta_path.exists():
            with open(meta_path, "rb") as f:
                cached_ids = pickle.load(f)
            # only reuse if the cached KB id list matches exactly — avoids silently
            # serving a stale index if version bookkeeping ever drifts
            if cached_ids == [e["id"] for e in kb]:
                print(f"[RAG] Loading persisted FAISS index for version {version}")
                self.index = faiss.read_index(str(cache_path))
                return
            print(f"[RAG] Cached index for version {version} doesn't match KB contents — rebuilding")

        print(f"[RAG] Building FAISS index over {len(texts)} entries...")
        emb = np.array(self.model.encode(texts, show_progress_bar=False, batch_size=64), dtype="float32")
        self.index = faiss.IndexFlatL2(emb.shape[1])
        self.index.add(emb)
        print("[RAG] FAISS index ready.")

        if cache_path:
            faiss.write_index(self.index, str(cache_path))
            with open(meta_path, "wb") as f:
                pickle.dump([e["id"] for e in kb], f)

    def retrieve_batch(self, queries: list[str], top_k: int = 2) -> list[list[dict]]:
        if not queries or self.index is None:
            return [[] for _ in queries]
        vecs = np.array(self.model.encode(queries, show_progress_bar=False), dtype="float32")
        distances, indices = self.index.search(vecs, top_k)
        out = []
        for row_d, row_i in zip(distances, indices):
            out.append([{**self.kb[i], "score": float(d)}
                        for d, i in zip(row_d, row_i) if 0 <= i < len(self.kb)])
        return out

    def retrieve(self, query: str, top_k: int = 2) -> list[dict]:
        return self.retrieve_batch([query], top_k)[0]


def _split_for_retrieval(text: str, max_chars: int = 700) -> list[str]:
    """Split a document into paragraph-sized windows. all-MiniLM-L6-v2 truncates at
    ~256 tokens, so embedding the whole document only reflects its first ~200 words."""
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    windows, cur = [], ""
    for p in paras:
        if cur and len(cur) + 1 + len(p) > max_chars:
            windows.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        windows.append(cur)
    # a single huge paragraph (no newlines): fall back to fixed windows
    out = []
    for w in windows:
        if len(w) <= max_chars * 2:
            out.append(w)
        else:
            out.extend(w[i:i + max_chars] for i in range(0, len(w), max_chars))
    return out or [text]


# ══════════════════════════════════════════════════════════════════════════════
#  4. SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

def build_system_prompt(target_language: str, legal_terms: list[str],
                        entities: dict[str, list[str]], retrieved_chunks: list[dict],
                        max_chunks: int = 4) -> str:
    lines = [
        "You are a professional legal document translator.",
        f"Translate the following text accurately into {target_language}.",
        "",
        "RULES:",
        "- Preserve all legal terminology with precision.",
        "- Do NOT translate: proper nouns, case names, section numbers, act names.",
        "- Maintain formal register appropriate for legal documents.",
        "- Do NOT alter, translate, or remove any token in the form [[NAME_0]], [[DATE_0]], "
        "[[AMOUNT_0]], etc. — copy them exactly as they appear, in the same position.",
        "- Preserve all numbering, structure, and formatting.",
        "- Keep all numbers, amounts and dates in Arabic numerals (1,2,3 NOT १,२,३).",
        "",
    ]
    if legal_terms:
        lines.append(f"LEGAL TERMS IN THIS DOCUMENT ({len(legal_terms)}): " + ", ".join(legal_terms[:15]))
    for label, values in entities.items():
        if values and label != "LEGAL_TERMS":
            lines.append(f"{label}: {', '.join(values[:4])}")
    if retrieved_chunks:
        lines += ["", "LEGAL DEFINITIONS FOR REFERENCE (use for accurate translation):"]
        for i, chunk in enumerate(retrieved_chunks[:max_chunks], 1):
            lines.append(f"  [{i}] {chunk['term'].upper()}: {chunk['text'][:400]}")
    lines += ["", f"When a legal term has no direct {target_language} equivalent, "
                  f"transliterate it and add a brief parenthetical explanation in {target_language}."]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  5. RAG PIPELINE (hot-reloading)
# ══════════════════════════════════════════════════════════════════════════════

class RAGPipeline:
    def __init__(self, ner_path=None):
        # ner_path kept only so existing callers don't break; patterns now live in code.
        self.ner = InLegalNER(NER_PATTERNS)
        self.FAISS_CACHE_DIR = FAISS_CACHE_DIR
        self.FAISS_CACHE_DIR.mkdir(exist_ok=True, parents=True)
        print(f"[RAG] Loading embedding model ({MODEL_NAME})...")
        self.model = SentenceTransformer(MODEL_NAME)   # loaded once, reused on every rebuild
        self._lock = threading.Lock()
        self._rebuilding = False
        self._last_check = 0.0
        self._term_cache: dict[str, list[dict]] = {}
        self._build(kb_store.get_version())
        self._detect_pool = ThreadPoolExecutor(max_workers=2)

    # -- build / reload --------------------------------------------------------

    def _build(self, version: int) -> None:
        kb = kb_store.load_approved_entries()
        print(f"[RAG] Loaded {len(kb)} approved KB terms from MongoDB (version {version})")
        kb = filter_generic(kb)
        aho = AhoCorasickMatcher(kb)
        index = FAISSLegalIndex(kb, self.model, version=version, cache_dir=FAISS_CACHE_DIR)
        # per-term surface forms + vetted translations, for glossary substitution
        term_info = {
            e["term"].lower().strip(): {
                "forms": [e["term"]] + [v for v in e.get("variants", []) if v],
                "translations": e.get("translations") or {},
            }
            for e in kb
        }
        with self._lock:
            self.aho, self.faiss, self.version = aho, index, version
            self.term_info = term_info
            self._term_cache = {}
        cleanup_old_faiss_caches(FAISS_CACHE_DIR, keep_version=version)

    def _rebuild_bg(self, version: int) -> None:
        try:
            self._build(version)
        except Exception as e:
            print(f"[RAG] Background rebuild failed: {e}")
        finally:
            self._rebuilding = False

    def refresh_if_changed(self) -> None:
        """Cheap check (one tiny Mongo read, at most every KB_REFRESH_SECONDS)."""
        t = time.time()
        if self._rebuilding or t - self._last_check < KB_REFRESH_SECONDS:
            return
        self._last_check = t
        try:
            v = kb_store.get_version()
        except Exception as e:
            print(f"[RAG] Version check failed: {e}")
            return
        if v != self.version:
            print(f"[RAG] KB changed ({self.version} → {v}); rebuilding in background")
            self._rebuilding = True
            threading.Thread(target=self._rebuild_bg, args=(v,), daemon=True).start()

    # -- per-request -----------------------------------------------------------
    @timed("rag_process")
    def process(self, extracted_text: str, target_language: str, top_k: int = 2,
                max_terms: int = 5, translated_text: str = None,
                lang_key: str | None = None) -> dict:
        self.refresh_if_changed()
        with self._lock:
            aho, index, cache, term_info = self.aho, self.faiss, self._term_cache, self.term_info

        analysis_text = translated_text or extracted_text
        masked_text, name_mapping = mask_sensitive_terms(analysis_text)

        future_entities = self._detect_pool.submit(self.ner.extract, masked_text)
        future_terms = self._detect_pool.submit(aho.find_terms, masked_text)
        entities = future_entities.result()
        legal_terms = future_terms.result()
        if legal_terms:
            entities["LEGAL_TERMS"] = legal_terms
        print(f"[RAG] Terms found: {legal_terms}")

        # Glossary substitution inputs: found terms that have a vetted translation
        # for the target language (lang_key e.g. 'hi', 'mr').
        term_translations: dict[str, dict] = {}
        if lang_key:
            for t in legal_terms:
                info = term_info.get(t.lower().strip())
                tr = ((info or {}).get("translations") or {}).get(lang_key, "")
                if tr and tr.strip():
                    term_translations[t] = {"forms": info["forms"], "translation": tr.strip()}
            missing = [t for t in legal_terms if t not in term_translations]
            print(f"[RAG] Glossary: {len(term_translations)} term(s) will be substituted "
                  f"for '{lang_key}'" + (f"; no translation yet for {missing}" if missing else ""))

        # Document-level context: one retrieval per paragraph window (top-1 each),
        # not one embedding of the whole (truncated) document.
        windows = _split_for_retrieval(masked_text)
        doc_chunks = [r[0] for r in index.retrieve_batch(windows, top_k=1) if r]

        # Spend the max_terms slots on the most specific terms, not match order.
        terms_to_query = sorted(legal_terms, key=_specificity, reverse=True)[:max_terms]
        uncached = [t for t in terms_to_query if t not in cache]
        for term, res in zip(uncached, index.retrieve_batch(uncached, top_k=top_k)):
            cache[term] = res

        retrieved, seen_ids = [], set()
        # term-specific definitions first so they survive the max_chunks cut in the prompt
        for chunk in [c for t in terms_to_query for c in cache.get(t, [])] + doc_chunks:
            if chunk["id"] not in seen_ids:
                retrieved.append(chunk)
                seen_ids.add(chunk["id"])

        return {
            "legal_terms": legal_terms,
            "entities": entities,
            "retrieved_chunks": retrieved,
            "system_prompt": build_system_prompt(target_language, legal_terms, entities, retrieved),
            "masked_text": masked_text,
            "name_mapping": name_mapping,   # pass through to translator.py; unmask_sensitive_terms() on its output
            "term_translations": term_translations,   # {term: {"forms": [...], "translation": str}}
        }


if __name__ == "__main__":
    pipeline = RAGPipeline()
    sample = ("This affidavit is filed before the Hon'ble High Court in Writ Petition Civil No. 1234 "
              "of 2024. The petitioner submits that the respondent violated the injunction. The accused "
              "is charged with a cognizable offence and seeks anticipatory bail.")
    result = pipeline.process(sample, target_language="Hindi")
    print("Terms:", result["legal_terms"])
    print("Entities:", result["entities"])
    print(result["system_prompt"])