"""
tts.py
---------------
Text-to-Speech using Sarvam AI's Bulbul TTS API.
"""

import os
import base64
import time
import requests
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from collections import deque

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
MAX_TTS_CHARS = int(os.getenv("TTS_MAX_CHARS", "500"))
TTS_WORKERS = int(os.getenv("TTS_WORKERS", "8"))

_LANG_TO_CODE = {
    "English": "en-IN", "Hindi": "hi-IN", "Tamil": "ta-IN", "Telugu": "te-IN",
    "Kannada": "kn-IN", "Malayalam": "ml-IN", "Marathi": "mr-IN", "Bengali": "bn-IN",
    "Gujarati": "gu-IN", "Punjabi": "pa-IN", "Odia": "od-IN", "Assamese": "as-IN",
}

_LANG_TO_DEFAULT_SPEAKER = {code: "shubh" for code in _LANG_TO_CODE.values()}


class RateLimiter:
    def __init__(self, max_calls=55, period=60):
        self.max_calls = max_calls
        self.period = period
        self.calls = deque()

    def wait(self):
        now = time.time()
        while self.calls and self.calls[0] < now - self.period:
            self.calls.popleft()
        if len(self.calls) >= self.max_calls:
            time.sleep(max(self.period - (now - self.calls[0]), 0))
        self.calls.append(time.time())


_tts_limiter = RateLimiter()


def _resolve_lang_code(language: str) -> str:
    v = language.strip()
    if v in _LANG_TO_CODE:
        return _LANG_TO_CODE[v]
    if "-" in v:
        return v
    titled = v.title()
    if titled in _LANG_TO_CODE:
        return _LANG_TO_CODE[titled]
    print(f"[TTS] Unknown language '{language}', defaulting to hi-IN")
    return "hi-IN"


def _chunk_text(text: str, max_chars: int) -> list[str]:
    import re
    if len(text) <= max_chars:
        return [text]

    sentences = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = [s.strip() for s in re.split(r'(?<=[।.!?])\s+', line) if s.strip()]
        sentences.extend(parts if parts else [line])

    chunks, current = [], ""
    for sentence in sentences:
        if len(sentence) > max_chars:
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


def _call_bulbul(text, lang_code, speaker, pitch, pace, loudness) -> bytes:
    payload = {
        "inputs": [text],
        "target_language_code": lang_code,
        "speaker": speaker,
        "pitch": pitch,
        "pace": pace,
        "loudness": loudness,
        "speech_sample_rate": 24000,
        "enable_preprocessing": True,
        "model": "bulbul:v3",
    }
    headers = {"Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY}

    resp = requests.post(SARVAM_TTS_URL, json=payload, headers=headers, timeout=60)
    if resp.status_code != 200:
        print(f"[TTS] Error body: {resp.text}")
    resp.raise_for_status()

    data = resp.json()
    audios = data.get("audios", [])
    if not audios:
        raise ValueError(f"No audio in Bulbul response: {data}")
    return base64.b64decode(audios[0])


def _merge_wav_chunks(wav_chunks: list[bytes]) -> bytes:
    import wave, io
    if len(wav_chunks) == 1:
        return wav_chunks[0]

    frames_list, params = [], None
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
    text: str, speaker: str = "shubh", language: str = "Hindi",
    pitch: float = 0, pace: float = 1.0, loudness: float = 1.5,
) -> bytes:
    if not text.strip():
        print("[TTS] Empty text, skipping.")
        return b""

    lang_code = _resolve_lang_code(language)
    resolved_speaker = speaker if speaker else _LANG_TO_DEFAULT_SPEAKER.get(lang_code, "shubh")
    chunks = _chunk_text(text, MAX_TTS_CHARS)
    print(f"[TTS] {len(chunks)} chunk(s) to synthesize")

    def _synth(indexed_chunk):
        i, chunk = indexed_chunk
        _tts_limiter.wait()
        try:
            return _call_bulbul(chunk, lang_code, resolved_speaker, pitch, pace, loudness)
        except Exception as e:
            print(f"[TTS] Chunk {i+1} failed: {e}, skipping")
            return None

    with ThreadPoolExecutor(max_workers=TTS_WORKERS) as executor:
        results = list(executor.map(_synth, enumerate(chunks)))

    wav_chunks = [r for r in results if r is not None]
    failed_count = len(chunks) - len(wav_chunks)

    if not wav_chunks:
        raise RuntimeError("[TTS] All chunks failed — no audio generated")

    return _merge_wav_chunks(wav_chunks), len(chunks), failed_count