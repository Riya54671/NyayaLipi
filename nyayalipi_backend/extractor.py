"""
pipeline/extractor.py
---------------------
Extract plain text from .docx, .pdf, and .txt files.
"""

from pathlib import Path

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


def extract_text_from_file(path: Path) -> str:
    """
    Dispatch to the right extractor based on file extension.
    Returns a single plain-text string.
    """
    ext = path.suffix.lower()
    if ext == ".docx":
        return _extract_docx(path)
    elif ext == ".pdf":
        return _extract_pdf(path)
    elif ext == ".txt":
        return _extract_txt(path)
    elif ext in SUPPORTED_IMAGE_EXTENSIONS:
        return _extract_image_ocr(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")



# ---------------------------------------------------------------------------
# Extractor implementations
# ---------------------------------------------------------------------------

def _extract_docx(path: Path) -> str:
    """Extract text from a .docx file preserving paragraph order."""
    try:
        from docx import Document  # python-docx
    except ImportError as e:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx") from e

    doc = Document(str(path))
    paragraphs = [para.text for para in doc.paragraphs]
    return "\n".join(paragraphs)


def _extract_pdf(path: Path) -> str:
    """Extract text from a PDF using pymupdf (better Indian language support)."""
    try:
        import fitz  # pip install pymupdf
    except ImportError as e:
        raise RuntimeError("pymupdf is not installed. Run: pip install pymupdf") from e

    full_text = []
    with fitz.open(str(path)) as doc:
        for i, page in enumerate(doc):
            text = page.get_text("text")
            print(f"[DEBUG] Page {i+1}: {len(text)} chars")
            if text.strip():
                full_text.append(text.strip())

    return "\n".join(full_text)

def _extract_txt(path: Path) -> str:
    """Read plain text file."""
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_image_ocr(path: Path) -> str:
    """
    Extract text from an image using Tesseract.
    Uses ALL installed Indian language packs combined for best accuracy.
    Language identification is left to Sarvam /text-lid — not Tesseract OSD.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise RuntimeError("Run: pip install pytesseract pillow") from e

    # Must be outside/after the try-except, NOT inside it
    pytesseract.pytesseract.tesseract_cmd = r"C:/Users/riya1/AppData/Local/Programs/Tesseract-OCR/tesseract.exe"

    img = Image.open(str(path))
    img = _preprocess_image(img)

    # Use all installed language packs — Sarvam handles lang detection, not us
    lang = _get_available_langs(pytesseract)
    print(f"[OCR] Using langs: '{lang}' for {path.name}")

    text = pytesseract.image_to_string(img, lang=lang, config="--psm 6 --oem 3")
    cleaned = text.strip()
    print(f"[OCR] Extracted {len(cleaned)} chars from {path.name}")

    if not cleaned:
        raise ValueError(f"OCR returned empty text for {path.name}.")

    return cleaned


def _get_available_langs(pytesseract) -> str:
    """
    Dynamically build lang string from whatever .traineddata files
    are actually installed — no hardcoding.
    """
    INDIAN_LANGS = ["hin", "tam", "tel", "kan", "mal", "ben", "guj", "pan", "ori", "mar"]
    try:
        installed = pytesseract.get_languages()
        print(f"[OCR] Installed Tesseract langs: {installed}")
        available = [l for l in INDIAN_LANGS if l in installed]
        if not available:
            return "eng"
        return "+".join(["eng"] + available)
    except Exception as e:
        print(f"[OCR] Could not get installed langs: {e}, falling back to eng+hin")
        return "eng+hin"


def _preprocess_image(img):
    from PIL import ImageEnhance, ImageFilter
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img = img.convert("L")
    img = img.filter(ImageFilter.SHARPEN)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)
    return img