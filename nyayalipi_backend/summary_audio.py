from gemini_summary import generate_summary
from tts import synthesize_audio_bulbul


def generate_summary_audio(translated_text: str, language: str, speaker: str = "shubh"):
    """Returns (audio_bytes, total_chunks, failed_chunks), the same shape main.py already unpacks."""
    summary = generate_summary(translated_text, language=language)
    if not summary:
        return b"", 0, 0
    return synthesize_audio_bulbul(text=summary, speaker=speaker, language=language)