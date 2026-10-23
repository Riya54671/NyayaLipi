"""translator_v1_baseline.py - the published NyayaLipi v1 pipeline (NO routing), kept as the
baseline for the paper. Every English->target chunk goes to the Sarvam LLM with the RAG system
prompt; only names/dates/amounts are masked. Run it with:  $env:TRANSLATOR_MODULE="translator_v1_baseline"
"""
import os
import time
import requests
from dotenv import load_dotenv
from timing import timed
import re
load_dotenv()
from concurrent.futures import ThreadPoolExecutor
from sarvamai import SarvamAI
from rag_pipeline import RAGPipeline
from masking import unmask_sensitive_terms

MAX_WORKERS = int(os.getenv("TRANSLATION_WORKERS", "4"))


SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"
CHUNK_SIZE = int(os.getenv("TRANSLATION_CHUNK_CHARS", "900"))
_llm = None


def _get_llm():
    global _llm
    if SARVAM_API_KEY is None or not str(SARVAM_API_KEY).strip():
        raise RuntimeError("SARVAM_API_KEY is not set. Configure the API key before running translation.")
    if _llm is None:
        _llm = SarvamAI(api_subscription_key=SARVAM_API_KEY)
    return _llm

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
    
def _translate_one_chunk(args):
    i, total, chunk, src_code, tgt_code, system_prompt, force_llm = args
    print(f"[Translator] Chunk {i+1}/{total} ({len(chunk)} chars) — {src_code} → {tgt_code}")
    use_llm = force_llm or (src_code == "en-IN" and tgt_code != "en-IN")
    route = "sarvam_llm" if use_llm else "sarvam_mayura"
    t0 = time.perf_counter()
    for attempt in (1, 2):
        try:
            if use_llm:
                out = _call_sarvam_llm(chunk, resolve_lang_name(tgt_code), system_prompt)
            else:
                out = _call_sarvam(chunk, src_code, tgt_code, system_prompt)
            return out, route, round(time.perf_counter() - t0, 3)
        except Exception as e:
            print(f"[Translator] Chunk {i+1} attempt {attempt} failed: {e}")
    print(f"[Translator] Chunk {i+1} failed twice, keeping original text")
    return chunk, "failed", round(time.perf_counter() - t0, 3)

@timed("translate_pivot_to_english")
def _translate_pass(text, src_code, tgt_code, system_prompt=None, force_llm=False, log=None) -> str:
    chunks = _chunk_text(text, CHUNK_SIZE)
    jobs = [(i, len(chunks), c, src_code, tgt_code, system_prompt, force_llm)
            for i, c in enumerate(chunks)]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        results = list(ex.map(_translate_one_chunk, jobs))
    if log is not None:                      # same shape as the v2 routing_log
        log.extend({"chunk": i, "route": r[1], "seconds": r[2]} for i, r in enumerate(results))
    return " ".join(r[0] for r in results)

def _has_repetition_loop(text: str, threshold: float = 0.15) -> bool:
    words = text.split()
    if len(words) < 10:
        return False
    from collections import Counter
    most_common_count = Counter(words).most_common(1)[0][1]
    return (most_common_count / len(words)) > threshold

def translate_text(text, source_language, target_language,
                   system_prompt=None, rag=None) -> dict:
    if not text.strip():
        return {"translated_text": text, "legal_terms": [], "entities": {}, "english_text": text, "routing_log": []}
    src_code = resolve_lang_code(source_language)
    tgt_code = resolve_lang_code(target_language)

    # 1. Get English text (the KB and RAG are English-only)
    if src_code == "en-IN":
        english_text = text
    else:
        print("[Translator] Pivoting source → English")
        english_text = _translate_pass(text, src_code, "en-IN")

    # 2. Run RAG once, on the English text
    sp, legal_terms, entities = system_prompt, [], {}
    masked_text, name_mapping = english_text, {}
    if rag:
        rag_result = rag.process(
            extracted_text=english_text,
            target_language=resolve_lang_name(tgt_code),
            lang_key=tgt_code.split("-")[0],
        )
        sp = rag_result["system_prompt"]
        legal_terms = rag_result["legal_terms"]
        entities = rag_result["entities"]
        masked_text = rag_result["masked_text"]
        name_mapping = rag_result["name_mapping"]
        print(f"[RAG] Terms found: {legal_terms}")

    # 3. English → target (skipped when the target is English)
    routing_log = []
    if tgt_code == "en-IN":
        final = masked_text
    else:
        final = _translate_pass(masked_text, "en-IN", tgt_code, sp, force_llm=True, log=routing_log)

     # 4. Restore real names into the translated output
    final = unmask_sensitive_terms(final, name_mapping)

    print("\n[Routing Summary] baseline (no routing): "
          f"LLM {sum(r['route']=='sarvam_llm' for r in routing_log)}, "
          f"failed {sum(r['route']=='failed' for r in routing_log)}\n")
    return {"translated_text": final, "legal_terms": legal_terms, "entities": entities,
            "english_text": english_text, "routing_log": routing_log}
    

def _chunk_text(text: str, max_chars: int) -> list[str]:
    """
    Split text into chunks, never breaking inside a sentence, and
    preserving line breaks so clause numbers/headings survive.
    """
    # Keep every line, including short ones (clause numbers, headings)
    lines = [l for l in text.split("\n")]

    chunks = []
    current = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            # blank line — preserve as a paragraph break if there's room
            if len(current) + 1 <= max_chars:
                current += "\n"
            continue

        # split the line into sentences, never mid-sentence
        sentences = [s.strip() for s in re.split(r'(?<=[।.!?])\s+', stripped) if s.strip()]
        if not sentences:
            sentences = [stripped]

        for sentence in sentences:
            candidate = (current + "\n" + sentence).strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                # a single sentence longer than max_chars is kept whole anyway —
                # better an oversized chunk than a mid-sentence cut
                current = sentence

    if current.strip():
        chunks.append(current)

    return chunks if chunks else [text]
        

def _call_sarvam_llm(text: str, tgt_name: str, system_prompt: str | None) -> str:
    sys_msg = (system_prompt or f"You are a professional legal translator into {tgt_name}.")
    sys_msg += (
        "\n\nTranslate the user's text. Output ONLY the translation, "
        "with no notes or explanations. Keep the same number of lines."
    )
    # sarvam-105b reasons before answering and reasoning tokens count against max_tokens, so with
    # reasoning on a 4096 budget can be used up before any text is produced (finish_reason=length,
    # content=None). Translation needs no reasoning: it is switched off (reasoning_effort=None, per
    # the Sarvam model docs) unless LLM_REASONING_EFFORT is set to e.g. "low".
    effort = os.getenv("LLM_REASONING_EFFORT", "none").strip().lower()
    kwargs = dict(
        model="sarvam-105b",
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": text},
        ],
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
    )
    kwargs["reasoning_effort"] = None if effort in ("none", "off", "") else effort
    resp = _get_llm().chat.completions(**kwargs)
    print(f"[LLM usage] {getattr(resp, 'usage', None)}")

    msg = resp.choices[0].message
    content = msg.content
    if content is None:
        print(f"[LLM DEBUG] finish_reason={resp.choices[0].finish_reason}")
        print(f"[LLM DEBUG] Full message object: {msg}")
        raise ValueError("LLM returned no content")

    return _restore_arabic_numerals(content.strip())

def _call_sarvam(text: str, src_code: str, tgt_code: str,system_prompt:str) -> str:
    """Call Sarvam /translate endpoint."""
    if SARVAM_API_KEY is None or not str(SARVAM_API_KEY).strip():
        raise RuntimeError("SARVAM_API_KEY is not set. Configure the API key before running translation.")

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
    if _has_repetition_loop(translated):
        raise ValueError(f"Repetition loop detected in output: {translated[:100]}...")
    return translated