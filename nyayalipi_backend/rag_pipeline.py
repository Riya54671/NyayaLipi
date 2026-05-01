"""
rag_pipeline.py
---------------
RAG Layer — responsibility is ONLY:
  1. InLegal NER         → find named entities in extracted text
  2. Aho-Corasick        → match legal terms from knowledge base
  3. FAISS               → retrieve English context per matched term
  4. build_system_prompt → return prompt string to translator.py

Language detection is NOT done here.
Translation is NOT done here.
Both of those are translator.py's job.

Install:
    pip install pyahocorasick faiss-cpu sentence-transformers numpy
"""

import json
import re
import numpy as np
from pathlib import Path

import ahocorasick
import faiss
from sentence_transformers import SentenceTransformer

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
KB_PATH  = BASE_DIR / "legal_kb.json"
NER_PATH = BASE_DIR / "ner.json"          # your file is called ner.json


# ══════════════════════════════════════════════════════════════════════════════
#  1. LOADERS
# ══════════════════════════════════════════════════════════════════════════════

def load_knowledge_base(path: Path = KB_PATH) -> list[dict]:
    """
    Loads legal_kb.json
    Each entry must have: { "id": str, "term": str, "text": str }
    """
    if not path.exists():
        raise FileNotFoundError(f"Knowledge base not found: {path}")
    with open(path, encoding="utf-8") as f:
        kb = json.load(f)
    print(f"[RAG] Loaded {len(kb)} KB entries from {path.name}")
    return kb


# Fallback NER patterns if ner.json is missing
_FALLBACK_NER = {
    "COURT": [
        r"\bSupreme Court\b", r"\bHigh Court\b", r"\bDistrict Court\b",
        r"\bSessions Court\b", r"\bMagistrate Court\b", r"\bTribunal\b",
    ],
    "SECTION": [
        r"\bSection\s+\d+[A-Za-z]?\b", r"\bArticle\s+\d+\b",
        r"\bClause\s+\d+\b", r"\bRule\s+\d+\b",
    ],
    "ACT": [
        r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+Act(?:,\s*\d{4})?\b",
        r"\bIPC\b", r"\bCrPC\b", r"\bCPC\b",
    ],
    "CASE_REF": [
        r"\bAIR\s+\d{4}\s+[A-Z]+\s+\d+\b",
        r"\b\(\d{4}\)\s+\d+\s+SCC\s+\d+\b",
        r"\bWrit\s+Petition\s+(?:Civil|Criminal)?\s*No\.\s*\d+\b",
    ],
    "PERSON_ROLE": [
        r"\bpetitioner\b", r"\brespondent\b", r"\bappellant\b",
        r"\bdefendant\b", r"\bplaintiff\b", r"\baccused\b",
        r"\bcomplainant\b",
    ],
    "DATE": [
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|"
        r"June|July|August|September|October|November|December),?\s+\d{4}\b",
    ],
}


def load_ner_patterns(path: Path = NER_PATH) -> dict[str, list[str]]:
    """Loads ner.json. Falls back to built-in patterns if file missing."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            patterns = json.load(f)
        print(f"[RAG] Loaded NER patterns: {list(patterns.keys())}")
        return patterns
    print("[RAG] ner.json not found — using fallback NER patterns.")
    return _FALLBACK_NER


# ══════════════════════════════════════════════════════════════════════════════
#  2. InLegal NER
#     Extracts named entities (courts, acts, sections etc.) via regex.
#     In production: swap with fine-tuned InLegal-BERT model.
# ══════════════════════════════════════════════════════════════════════════════

class InLegalNER:
    def __init__(self, patterns: dict[str, list[str]]):
        self.patterns = patterns

    def extract(self, text: str) -> dict[str, list[str]]:
        """
        Runs all regex patterns over text.
        Returns { "COURT": [...], "ACT": [...], ... }
        Only includes entity types that actually found something.
        """
        entities: dict[str, list[str]] = {}
        for label, regexes in self.patterns.items():
            seen, unique = set(), []
            for pattern in regexes:
                for match in re.findall(pattern, text, flags=re.IGNORECASE):
                    clean = match.strip()
                    if clean.lower() not in seen:
                        seen.add(clean.lower())
                        unique.append(clean)
            if unique:
                entities[label] = unique
        return entities


# ══════════════════════════════════════════════════════════════════════════════
#  3. AHO-CORASICK MATCHER
#     Scans extracted text for all legal terms in the KB in one pass O(n).
#     Terms come from legal_kb.json — add a term there, it's matched here.
# ══════════════════════════════════════════════════════════════════════════════

class AhoCorasickMatcher:
    def __init__(self, kb: list[dict]):
        self.automaton = ahocorasick.Automaton()
        for idx, entry in enumerate(kb):
            self.automaton.add_word(entry["term"].lower(), (idx, entry["term"]))
        self.automaton.make_automaton()
        print(f"[RAG] Aho-Corasick built with {len(kb)} terms.")

    def find_terms(self, text: str) -> list[str]:
        """
        Returns list of legal terms found in text, preserving original case.
        e.g. "habeas corpus", "injunction", "suo motu"
        """
        found: dict[str, str] = {}
        for _, (_, term) in self.automaton.iter(text.lower()):
            found[term.lower()] = term
        return list(found.values())


# ══════════════════════════════════════════════════════════════════════════════
#  4. FAISS INDEX
#     Builds a vector index over all KB entries at startup.
#     Given a legal term, retrieves the most relevant KB definitions.
# ══════════════════════════════════════════════════════════════════════════════

class FAISSLegalIndex:
    MODEL_NAME = "all-MiniLM-L6-v2"   # 80MB, fully offline, no GPU needed

    def __init__(self, kb: list[dict]):
        self.kb    = kb
        self.texts = [entry["text"] for entry in kb]

        print(f"[RAG] Loading embedding model ({self.MODEL_NAME})...")
        self.model = SentenceTransformer(self.MODEL_NAME)

        print(f"[RAG] Building FAISS index over {len(self.texts)} entries...")
        embeddings = self.model.encode(self.texts, show_progress_bar=False)
        embeddings = np.array(embeddings, dtype="float32")

        self.index = faiss.IndexFlatL2(embeddings.shape[1])
        self.index.add(embeddings)
        print(f"[RAG] FAISS index ready.")

    def retrieve(self, query: str, top_k: int = 2) -> list[dict]:
        """
        Returns top_k KB entries most semantically similar to query.
        Each result: { id, term, text, score }
        """
        vec = np.array(
            self.model.encode([query], show_progress_bar=False),
            dtype="float32"
        )
        distances, indices = self.index.search(vec, top_k)
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if 0 <= idx < len(self.kb):
                results.append({**self.kb[idx], "score": float(dist)})
        return results


# ══════════════════════════════════════════════════════════════════════════════
#  5. SYSTEM PROMPT BUILDER
#     This is what gets passed to translator.py → injected into Sarvam API.
# ══════════════════════════════════════════════════════════════════════════════

def build_system_prompt(
    target_language: str,
    legal_terms: list[str],
    entities: dict[str, list[str]],
    retrieved_chunks: list[dict],
    max_chunks: int = 4,
) -> str:
    """
    Builds the system prompt for the Sarvam API call.

    Structure:
      [1] Role + translation instructions
      [2] Legal terms and entities found in this document
      [3] FAISS-retrieved definitions for accurate translation
    """
    lines = [
    f"You are a professional legal document translator.",
    f"Translate the following text accurately into {target_language}.",
    "",
    "RULES:",
    "- Preserve all legal terminology with precision.",
    "- Do NOT translate: proper nouns, case names, section numbers, act names.",
    "- Maintain formal register appropriate for legal documents.",
    "- Preserve all numbering, structure, and formatting.",
    "- Keep all numbers, amounts and dates in Arabic numerals (1,2,3 NOT १,२,३).",  # ← ADD
    "",
]

    # Section 2 — what RAG found in this specific document
    if legal_terms:
        lines.append(
            f"LEGAL TERMS IN THIS DOCUMENT ({len(legal_terms)}): "
            + ", ".join(legal_terms[:15])
        )

    for label, values in entities.items():
        if values:
            lines.append(f"{label}: {', '.join(values[:4])}")

    # Section 3 — FAISS retrieved definitions
    if retrieved_chunks:
        lines.append("")
        lines.append("LEGAL DEFINITIONS FOR REFERENCE (use for accurate translation):")
        for i, chunk in enumerate(retrieved_chunks[:max_chunks], 1):
            lines.append(f"  [{i}] {chunk['term'].upper()}: {chunk['text']}")

    lines += [
        "",
        f"When a legal term has no direct {target_language} equivalent, "
        "transliterate it and add a brief parenthetical explanation in "
        f"{target_language}.",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  6. RAG PIPELINE — main class
#     Call rag.process(extracted_text, target_language)
#     Get back system_prompt → pass to translator.py
# ══════════════════════════════════════════════════════════════════════════════

class RAGPipeline:
    """
    Wires together: NER → Aho-Corasick → FAISS → system prompt.
    Does NOT do language detection (that's translator.py).
    Does NOT call Sarvam API (that's translator.py).
    """

    def __init__(self, kb_path: Path = KB_PATH, ner_path: Path = NER_PATH):
        kb              = load_knowledge_base(kb_path)
        ner_patterns    = load_ner_patterns(ner_path)
        self.ner        = InLegalNER(ner_patterns)
        self.aho        = AhoCorasickMatcher(kb)
        self.faiss      = FAISSLegalIndex(kb)

    def process(
        self,
        extracted_text: str,
        target_language: str,
        top_k: int = 2,
        max_terms: int = 5,
        translated_text: str = None,   
    ) -> dict:
        """
        Args:
            extracted_text:  text from extractor.py
            target_language: e.g. "Hindi" — comes from Flutter dropdown
            top_k:           FAISS results per term
            max_terms:       max terms sent to FAISS (keep low for speed)

        Returns:
            {
              "legal_terms":      ["affidavit", "injunction", ...],
              "entities":         {"COURT": [...], "ACT": [...], ...},
              "retrieved_chunks": [{id, term, text, score}, ...],
              "system_prompt":    "You are a professional legal..."
            }

        → Pass result["system_prompt"] directly to translator.py
        """
        analysis_text = translated_text if translated_text else extracted_text
        print(f"[RAG DEBUG] analysis_text preview: {analysis_text[:200]}")

       # Step 1 — InLegal NER
        entities = self.ner.extract(analysis_text)       # ← change extracted_text to analysis_text

    # Step 2 — Aho-Corasick
        legal_terms = self.aho.find_terms(analysis_text)    # ← change extracted_text to analysis_text
        print(f"[RAG] Terms found: {legal_terms}")

    # Step 3 — FAISS
        retrieved: list[dict] = []
        seen_ids: set[str]    = set()
        # General retrieval on full text first (catches context beyond term list)
        for chunk in self.faiss.retrieve(analysis_text, top_k=2):
            if chunk["id"] not in seen_ids:
                retrieved.append(chunk)
                seen_ids.add(chunk["id"])

        # Targeted retrieval per matched term
        for term in legal_terms[:max_terms]:
            for chunk in self.faiss.retrieve(term, top_k=top_k):
                if chunk["id"] not in seen_ids:
                    retrieved.append(chunk)
                    seen_ids.add(chunk["id"])

        # Step 4 — Build system prompt → goes to translator.py → Sarvam API
        system_prompt = build_system_prompt(
            target_language  = target_language,
            legal_terms      = legal_terms,
            entities         = entities,
            retrieved_chunks = retrieved,
        )

        return {
            "legal_terms":      legal_terms,
            "entities":         entities,
            "retrieved_chunks": retrieved,
            "system_prompt":    system_prompt,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  QUICK TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pipeline = RAGPipeline()

    sample = """
    This affidavit is filed before the Hon'ble High Court of Madras in
    connection with Writ Petition Civil No. 1234 of 2024. The petitioner
    submits that the respondent violated the injunction granted under Section 9
    of the Arbitration and Conciliation Act, 1996. The accused has committed
    contempt of court. Habeas corpus petition is filed as a suo motu action.
    """

    result = pipeline.process(sample, target_language="Hindi")

    print(f"\nLegal Terms     : {result['legal_terms']}")
    print(f"Entities        : {result['entities']}")
    print(f"Retrieved chunks: {len(result['retrieved_chunks'])}")
    print(f"\nSYSTEM PROMPT:\n{'-'*50}")
    print(result["system_prompt"])