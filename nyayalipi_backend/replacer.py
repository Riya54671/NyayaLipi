from pathlib import Path

from layout_image import reconstruct_image
from layout_pdf import reconstruct_pdf


def _replace_txt(output_path, translated_text):
    Path(output_path).write_text(translated_text, encoding="utf-8")


def _replace_docx(input_path, output_path, original_text, translated_text):
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx") from exc

    doc = Document(str(input_path))

    def replace_in_paragraph(paragraph):
        if original_text and original_text in paragraph.text:
            paragraph.text = paragraph.text.replace(original_text, translated_text)
            return True
        return False

    replaced = False
    for paragraph in doc.paragraphs:
        replaced = replace_in_paragraph(paragraph) or replaced

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    replaced = replace_in_paragraph(paragraph) or replaced

    if not replaced:
        doc = Document()
        for line in translated_text.splitlines() or [""]:
            doc.add_paragraph(line)

    doc.save(str(output_path))


def replace_text_in_document(
    input_path, output_path, original_text, translated_text, file_type,
    lines=None, target_lang="English",
) -> None:
    if file_type == ".txt":
        _replace_txt(output_path, translated_text)
    elif file_type == ".docx":
        _replace_docx(input_path, output_path, original_text, translated_text)
    elif file_type == ".pdf":
        _replace_pdf(input_path, output_path, translated_text, lines, target_lang)
    elif file_type in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}:
        _replace_image(input_path, output_path, translated_text, lines, target_lang)
    else:
        raise ValueError(f"Unsupported file type for replacement: {file_type}")


def _replace_pdf(input_path, output_path, translated_text, lines, target_lang):
    trans_lines = translated_text.split("\n")
    if lines and len(trans_lines) == len(lines):
        reconstruct_pdf(input_path, output_path, lines, trans_lines, target_lang)
    else:
        # fallback: counts mismatched, don't guess wrong placements
        Path(output_path).write_text(translated_text, encoding="utf-8")


def _replace_image(input_path, output_path, translated_text, lines, target_lang):
    trans_lines = translated_text.split("\n")
    if lines and len(trans_lines) == len(lines):
        reconstruct_image(input_path, output_path, lines, trans_lines, target_lang)
    else:
        Path(output_path).write_text(translated_text, encoding="utf-8")