"""
pipeline/translator.py
"""

import os
import requests
from dotenv import load_dotenv
import os

load_dotenv()
from rag_pipeline import RAGPipeline

_rag = RAGPipeline()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"
CHUNK_SIZE = int(os.getenv("TRANSLATION_CHUNK_CHARS", "900"))  

_NAME_TO_CODE: dict[str, str] = {
    "English":   "en-IN",
    "Hindi":     "hi-IN",
    "Tamil":     "ta-IN",
    "Telugu":    "te-IN",
    "Kannada":   "kn-IN",
    "Malayalam": "ml-IN",
    "Marathi":   "mr-IN",
    "Bengali":   "bn-IN",
    "Gujarati":  "gu-IN",
    "Punjabi":   "pa-IN",
    "Odia":      "od-IN",
    "Assamese":  "as-IN",
    "Urdu":      "ur-IN",
}

_SHORT_TO_CODE: dict[str, str] = {
    "en": "en-IN", "hi": "hi-IN", "ta": "ta-IN", "te": "te-IN",
    "kn": "kn-IN", "ml": "ml-IN", "mr": "mr-IN", "bn": "bn-IN",
    "gu": "gu-IN", "pa": "pa-IN", "or": "od-IN", "as": "as-IN",
    "ur": "ur-IN",
}
def _restore_arabic_numerals(text: str) -> str:
    """Convert Devanagari numerals back to Arabic numerals."""
    devanagari_map = {
        '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
        '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'
    }
    for dev, arabic in devanagari_map.items():
        text = text.replace(dev, arabic)
    return text

_CODE_TO_NAME: dict[str, str] = {v: k for k, v in _NAME_TO_CODE.items()}
SUPPORTED_LANGUAGES = set(_NAME_TO_CODE.values())

english_pivot_chunks = []
def resolve_lang_code(value: str) -> str:
    v = value.strip()
    if "-" in v and v in SUPPORTED_LANGUAGES:
        return v
    if "-" in v:
        return v
    if v in _NAME_TO_CODE:
        return _NAME_TO_CODE[v]
    if v.lower() in _SHORT_TO_CODE:
        return _SHORT_TO_CODE[v.lower()]
    titled = v.title()
    if titled in _NAME_TO_CODE:
        return _NAME_TO_CODE[titled]
    raise ValueError(f"Unsupported language '{value}'. Supported: {sorted(_NAME_TO_CODE.keys())}")


def resolve_lang_name(value: str) -> str:
    try:
        code = resolve_lang_code(value)
        return _CODE_TO_NAME.get(code, value.strip().title())
    except ValueError:
        return value.strip().title()


from rag_pipeline import RAGPipeline

def translate_text(text, source_language, target_language,
                   system_prompt=None, rag=None) -> dict:

    if not text.strip():
        return {"translated_text": text, "legal_terms": [], "entities": {}}

    src_code = resolve_lang_code(source_language)
    tgt_code = resolve_lang_code(target_language)

    if src_code != "en-IN" and tgt_code != "en-IN":
        print(f"[Translator] Non-English pair detected, pivoting through English")

        # Pass 1 — source → English (no RAG, just get the pivot)
        english_result = translate_text(text, src_code, "en-IN")
        english_text   = english_result["translated_text"]

        # RAG on English pivot
        if rag:
            tgt_name    = resolve_lang_name(tgt_code)
            rag_result  = rag.process(
                extracted_text  = text,
                target_language = tgt_name,
                translated_text = english_text,
            )
            print(f"[RAG] Terms found: {rag_result['legal_terms']}")
            sp          = rag_result["system_prompt"]
            legal_terms = rag_result["legal_terms"]
            entities    = rag_result["entities"]
        else:
            sp          = None
            legal_terms = []
            entities    = {}

        # Pass 2 — English → target with legal context
        result = translate_text(english_text, "en-IN", tgt_code,
                                system_prompt=sp)
        return {
            "translated_text": result["translated_text"],
            "legal_terms":     legal_terms,
            "entities":        entities,
        }

    # Single pass (either side is English)
    chunks = _chunk_text(text, CHUNK_SIZE)
    translated_chunks = []

    for i, chunk in enumerate(chunks):
        print(f"[Translator] Chunk {i+1}/{len(chunks)} ({len(chunk)} chars) — {src_code} → {tgt_code}")
        try:
            result = _call_sarvam(chunk, src_code, tgt_code, system_prompt)
            if result:
                translated_chunks.append(result)
        except Exception as e:
            print(f"[Translator] Chunk {i+1} failed: {e}, skipping")

    final = " ".join(translated_chunks) if translated_chunks else text
    print(f"[TRANSLATED OUTPUT]:\n{final}\n")
    return {"translated_text": final, "legal_terms": [], "entities": {}}

def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into sentence-level chunks under max_chars."""
    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 5]

    merged_lines = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 <= max_chars:
            current = (current + " " + line).strip()
        else:
            if current:
                merged_lines.append(current)
            current = line
    if current:
        merged_lines.append(current)

    chunks = []
    for line in merged_lines:
        if len(line) <= max_chars:
            chunks.append(line)
        else:
            sentences = line.replace("। ", "।\n").replace(". ", ".\n").split("\n")
            current = ""
            for sentence in sentences:
                if len(current) + len(sentence) + 1 <= max_chars:
                    current = (current + " " + sentence).strip()
                else:
                    if current:
                        chunks.append(current)
                    current = sentence
            if current:
                chunks.append(current)
    return chunks if chunks else [text]


def _call_sarvam(text: str, src_code: str, tgt_code: str,system_prompt:str) -> str:
    """Call Sarvam /translate endpoint."""
  
    
    payload = {
        "input": text,
        "source_language_code": src_code,
        "target_language_code": tgt_code,
        "speaker_gender": "Male",
        "mode": "formal",
        "model": "mayura:v1",
        "enable_preprocessing": False,
        
    }
    if system_prompt:
        payload["instructions"] = system_prompt[:500]

    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": SARVAM_API_KEY,
    }

    resp = requests.post(SARVAM_TRANSLATE_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    translated = data.get("translated_text", "").strip()
    if not translated:
        raise ValueError(f"Empty response from Sarvam: {data}")
    translated = _restore_arabic_numerals(translated) 
    return translated