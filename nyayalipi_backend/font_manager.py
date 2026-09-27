from pathlib import Path

FONT_MAP = {
    "Hindi": "NotoSansDevanagari-Regular.ttf",
    "Tamil": "NotoSansTamil-Regular.ttf",
    "Telugu": "NotoSansTelugu-Regular.ttf",
    "Malayalam": "NotoSansMalayalam-Regular.ttf",
    "Kannada": "NotoSansKannada-Regular.ttf",
    "Bengali": "NotoSansBengali-Regular.ttf",
    "Gujarati": "NotoSansGujarati-Regular.ttf",
    "Punjabi": "NotoSansGurmukhi-Regular.ttf",
    "Marathi": "NotoSansDevanagari-Regular.ttf",
    "English": "NotoSans-Regular.ttf",
}
FONT_DIR = Path(__file__).parent / "assets" / "fonts"

def get_font_path(target_lang: str) -> Path:
    filename = FONT_MAP.get(target_lang, "NotoSans-Regular.ttf")
    return FONT_DIR / filename