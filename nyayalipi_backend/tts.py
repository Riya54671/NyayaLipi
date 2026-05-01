"""
pipeline/tts.py
---------------
Text-to-Speech using Sarvam AI's Bulbul TTS API.
Endpoint: POST https://api.sarvam.ai/text-to-speech

Env vars:
    SARVAM_API_KEY      default: sk_9lwdwj67_GsziofLYOHUsjPdof0lTAGMS
    TTS_MAX_CHARS       default: 500 (Bulbul limit per request is 500 chars)
"""

import os
import base64
import requests
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()


SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
MAX_TTS_CHARS = int(os.getenv("TTS_MAX_CHARS", "500")) 

# ---------------------------------------------------------------------------
# Bulbul speaker options per language
# Pick the best default speaker for each language
# ---------------------------------------------------------------------------

# All available Bulbul speakers (for reference):
# anushka, manisha, vidya, arya (female)
# abhilash, karun, hitesh (male)

_LANG_TO_CODE: dict[str, str] = {
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
}

# Default speakers per language — these voices are verified to work well
_LANG_TO_DEFAULT_SPEAKER: dict[str, str] = {
    "en-IN": "anushka",
    "hi-IN": "anushka",
    "ta-IN": "anushka",
    "te-IN": "anushka",
    "kn-IN": "anushka",
    "ml-IN": "anushka",
    "mr-IN": "anushka",
    "bn-IN": "anushka",
    "gu-IN": "anushka",
    "pa-IN": "anushka",
    "od-IN": "anushka",
    "as-IN": "anushka",
}


def _resolve_lang_code(language: str) -> str:
    """Accept display name or BCP-47 code and return Bulbul-compatible code."""
    v = language.strip()
    if v in _LANG_TO_CODE:
        return _LANG_TO_CODE[v]
    # already a BCP-47 code like hi-IN
    if "-" in v:
        return v
    # title-case fallback
    titled = v.title()
    if titled in _LANG_TO_CODE:
        return _LANG_TO_CODE[titled]
    # default to Hindi if unknown
    print(f"[TTS] Unknown language '{language}', defaulting to hi-IN")
    return "hi-IN"


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """
    Split text into chunks under max_chars.
    Tries to split at sentence boundaries first.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    # Split at sentence-ending punctuation
    sentences = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split on । (Devanagari danda), . ! ?
        parts = [s.strip() for s in __import__('re').split(r'(?<=[।.!?])\s+', line) if s.strip()]
        sentences.extend(parts if parts else [line])

    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            # Single sentence too long — hard split
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(sentence), max_chars):
                chunks.append(sentence[i:i + max_chars])
        elif len(current) + len(sentence) + 1 <= max_chars:
            current = (current + " " + sentence).strip()
        else:
            if current:
                chunks.append(current)
            current = sentence

    if current:
        chunks.append(current)

    return chunks if chunks else [text]


def _call_bulbul(text: str, lang_code: str, speaker: str, pitch: float, pace: float, loudness: float) -> bytes:
    """Call Sarvam Bulbul TTS and return raw WAV bytes."""
    payload = {
        "inputs": [text],
        "target_language_code": lang_code,
        "speaker": speaker,
        "pitch": pitch,
        "pace": pace,
        "loudness": loudness,
        "speech_sample_rate": 24000,
        "enable_preprocessing": True,
        "model": "bulbul:v2",
    }

    headers = {
        "Content-Type": "application/json",
        "api-subscription-key": SARVAM_API_KEY,
    }

    resp = requests.post(SARVAM_TTS_URL, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    audios = data.get("audios", [])
    if not audios:
        raise ValueError(f"No audio in Bulbul response: {data}")

    # Bulbul returns base64-encoded WAV
    return base64.b64decode(audios[0])


def _merge_wav_chunks(wav_chunks: list[bytes]) -> bytes:
    """Concatenate multiple WAV byte blobs into one valid WAV file."""
    import wave
    import io

    if len(wav_chunks) == 1:
        return wav_chunks[0]

    frames_list = []
    params = None

    for chunk in wav_chunks:
        with wave.open(io.BytesIO(chunk), "rb") as wf:
            if params is None:
                params = wf.getparams()
            frames_list.append(wf.readframes(wf.getnframes()))

    out_buf = io.BytesIO()
    with wave.open(out_buf, "wb") as wf:
        wf.setparams(params)
        for frames in frames_list:
            wf.writeframes(frames)

    return out_buf.getvalue()


def synthesize_audio_bulbul(
    text: str,
    output_path: Path,
    speaker: str = "anushka",
    language: str = "Hindi",
    pitch: float = 0,
    pace: float = 1.0,
    loudness: float = 1.5,
) -> None:
    """
    Main entry point. Synthesizes text to WAV using Sarvam Bulbul TTS.
    Handles chunking and merging automatically.
    """
    if not text.strip():
        print("[TTS] Empty text, skipping.")
        return

    lang_code = _resolve_lang_code(language)
    resolved_speaker = speaker if speaker else _LANG_TO_DEFAULT_SPEAKER.get(lang_code, "anushka")

    print(f"[TTS] Bulbul — language={language} ({lang_code}), speaker={resolved_speaker}")

    chunks = _chunk_text(text, MAX_TTS_CHARS)
    print(f"[TTS] {len(chunks)} chunk(s) to synthesize")

    wav_chunks = []
    for i, chunk in enumerate(chunks):
        print(f"[TTS] Chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
        try:
            wav_bytes = _call_bulbul(chunk, lang_code, resolved_speaker, pitch, pace, loudness)
            wav_chunks.append(wav_bytes)
        except Exception as e:
            print(f"[TTS] Chunk {i+1} failed: {e}, skipping")

    if not wav_chunks:
        raise RuntimeError("[TTS] All chunks failed — no audio generated")

    final_wav = _merge_wav_chunks(wav_chunks)

    output_path = output_path.with_suffix(".wav")
    output_path.write_bytes(final_wav)
    print(f"[TTS] Saved WAV → {output_path}")