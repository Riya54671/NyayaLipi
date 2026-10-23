"""
pipeline/gemini_summary.py - summary for the audio overview.
"""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")   # same setting kb_updater uses
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_SUMMARY_MAX_TOKENS", "2048"))

SUMMARY_PROMPT_TEMPLATE = """You are summarizing a translated legal document for a short audio overview.

Summarize the following document in {language}, covering, if present: the parties involved,
key dates, monetary amounts, and the main obligations or terms.
Do not add information that is not in the document.
Do not use headings, bullet points, or markdown — write plain flowing sentences only,
since this will be read aloud.
Keep the summary under {max_chars} characters.

Document:
\"\"\"
{document_text}
\"\"\"

Summary:"""


def _truncate_to_last_sentence(text: str, max_chars: int) -> str:
    cut = text[:max_chars]
    last_boundary = max(cut.rfind("."), cut.rfind("।"), cut.rfind("!"), cut.rfind("?"))
    return cut[: last_boundary + 1] if last_boundary > 0 else cut


def _call_gemini(prompt: str) -> str:
    # The key goes in a header, not the URL, so errors never print it.
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY or ""}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": MAX_OUTPUT_TOKENS},
    }
    for attempt in (1, 2, 3):
        resp = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=60)
        if resp.status_code in (429, 500, 503) and attempt < 3:
            time.sleep(1.5 * attempt * attempt)          # 1.5s, then 6s
            continue
        resp.raise_for_status()
        break

    data = resp.json()
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise ValueError(f"Gemini returned no text (finishReason={cand.get('finishReason')})")
    if cand.get("finishReason") == "MAX_TOKENS":          # ran out of tokens: cut at a sentence end
        text = _truncate_to_last_sentence(text, len(text))
    return text


def generate_summary(document_text: str, language: str = "Hindi", max_chars: int = 2000) -> str:
    if not document_text.strip():
        return ""
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        language=language, document_text=document_text, max_chars=max_chars
    )
    summary = _call_gemini(prompt)
    if len(summary) > max_chars:
        summary = _truncate_to_last_sentence(summary, max_chars)
    return summary