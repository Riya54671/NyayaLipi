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

def extract_pdf_lines_with_boxes(path: Path) -> list[dict]:
    """
    Returns [{page, bbox:(x0,y0,x1,y1), text}, ...] per line, reading order.
    Pages with an embedded text layer use PyMuPDF directly.
    Pages with no text layer (scanned images) are rasterized and OCR'd in parallel.
    """
    import fitz
    import pytesseract
    from pytesseract import Output
    from PIL import Image
    import io
    from concurrent.futures import ThreadPoolExecutor

    pytesseract.pytesseract.tesseract_cmd = r"C:/Users/riya1/AppData/Local/Programs/Tesseract-OCR/tesseract.exe"
    lang = _get_available_langs(pytesseract)

    text_lines = {}      # page_num -> list of line dicts, for pages with a real text layer
    ocr_pages = []        # page_nums that need OCR

    with fitz.open(str(path)) as doc:
        page_pixmaps = {}  # page_num -> rendered image bytes, captured while doc is open

        for page_num, page in enumerate(doc):
            data = page.get_text("dict")
            page_has_text = any(
                span["text"].strip()
                for block in data["blocks"]
                for line in block.get("lines", [])
                for span in line.get("spans", [])
            )

            if page_has_text:
                lines = []
                for block in data["blocks"]:
                    for line in block.get("lines", []):
                        spans = line.get("spans", [])
                        if not spans:
                            continue
                        text = "".join(s["text"] for s in spans).strip()
                        if not text:
                            continue
                        x0 = min(s["bbox"][0] for s in spans)
                        y0 = min(s["bbox"][1] for s in spans)
                        x1 = max(s["bbox"][2] for s in spans)
                        y1 = max(s["bbox"][3] for s in spans)
                        lines.append({"page": page_num, "bbox": (x0, y0, x1, y1), "text": text})
                text_lines[page_num] = lines
            else:
                # Render now, while the document is still open — OCR itself
                # happens later, in parallel, outside this loop.
                pix = page.get_pixmap(dpi=300)
                page_pixmaps[page_num] = pix.tobytes("png")
                ocr_pages.append(page_num)

    def _ocr_one_page(page_num):
        img = Image.open(io.BytesIO(page_pixmaps[page_num]))
        img = _preprocess_image(img)

        ocr_data = pytesseract.image_to_data(
            img, lang=lang, config="--psm 6 --oem 3", output_type=Output.DICT
        )

        line_groups = {}
        for i in range(len(ocr_data["text"])):
            word = ocr_data["text"][i].strip()
            if not word:
                continue
            key = (ocr_data["block_num"][i], ocr_data["par_num"][i], ocr_data["line_num"][i])
            line_groups.setdefault(key, []).append(i)

        page_lines = []
        for key in sorted(line_groups.keys()):
            idxs = line_groups[key]
            words = [ocr_data["text"][i] for i in idxs]
            lefts = [ocr_data["left"][i] for i in idxs]
            tops = [ocr_data["top"][i] for i in idxs]
            rights = [ocr_data["left"][i] + ocr_data["width"][i] for i in idxs]
            bottoms = [ocr_data["top"][i] + ocr_data["height"][i] for i in idxs]
            page_lines.append({
                "page": page_num,
                "bbox": (min(lefts), min(tops), max(rights), max(bottoms)),
                "text": " ".join(words),
            })
        return page_num, page_lines

    if ocr_pages:
        print(f"[Extractor] OCR'ing {len(ocr_pages)} scanned page(s) in parallel")
        workers = min(len(ocr_pages), 4)  # Tesseract is CPU-heavy, don't over-subscribe
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for page_num, page_lines in executor.map(_ocr_one_page, ocr_pages):
                text_lines[page_num] = page_lines

    # Reassemble in correct page order
    lines = []
    for page_num in sorted(text_lines.keys()):
        lines.extend(text_lines[page_num])

    print(lines)

    return lines


def _extract_pdf(path: Path) -> str:
    lines = extract_pdf_lines_with_boxes(path)
    return "\n".join(l["text"] for l in lines)


def extract_image_lines_with_boxes(path: Path) -> list[dict]:
    """Returns [{bbox:(x0,y0,x1,y1), text}, ...] per OCR line."""
    import pytesseract
    from pytesseract import Output
    from PIL import Image

    pytesseract.pytesseract.tesseract_cmd = r"C:/Users/riya1/AppData/Local/Programs/Tesseract-OCR/tesseract.exe"
    img = Image.open(str(path))
    img = _preprocess_image(img)
    lang = _get_available_langs(pytesseract)
    data = pytesseract.image_to_data(img, lang=lang, config="--psm 6 --oem 3", output_type=Output.DICT)

    line_groups = {}
    for i in range(len(data["text"])):
        word = data["text"][i].strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        line_groups.setdefault(key, []).append(i)

    lines = []
    for key in sorted(line_groups.keys()):
        idxs = line_groups[key]
        words = [data["text"][i] for i in idxs]
        lefts = [data["left"][i] for i in idxs]
        tops = [data["top"][i] for i in idxs]
        rights = [data["left"][i] + data["width"][i] for i in idxs]
        bottoms = [data["top"][i] + data["height"][i] for i in idxs]
        lines.append({"bbox": (min(lefts), min(tops), max(rights), max(bottoms)),
                      "text": " ".join(words)})
    return lines


def _extract_image_ocr(path: Path) -> str:
    lines = extract_image_lines_with_boxes(path)
    if not lines:
        raise ValueError(f"OCR returned empty text for {path.name}.")
    return "\n".join(l["text"] for l in lines)