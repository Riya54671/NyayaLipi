from pathlib import Path


def _create_docx_from_text(output_path: Path, translated_text: str) -> None:
    """Write translated text into a fresh .docx — used for all input types
    since we're not reconstructing original layout, just delivering clean text."""
    from docx import Document

    doc = Document()
    lines = translated_text.split("\n") if translated_text else [""]
    for line in lines:
        doc.add_paragraph(line)  # empty lines become empty paragraphs — preserves spacing
    doc.save(str(output_path))


def replace_text_in_document(
    output_path,
    translated_text,
    file_type,
    target_lang="English",
) -> None:
    """
    Writes the translated document output.
    Regardless of source file type (pdf, docx, image), output is a clean .docx
    containing the translated text — no layout reconstruction.
    """
    if file_type == ".txt":
        Path(output_path).write_text(translated_text, encoding="utf-8")
    elif file_type == ".docx":
        _create_docx_from_text(output_path, translated_text)
    elif file_type in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}:
        _create_docx_from_text(output_path, translated_text)
    else:
        raise ValueError(f"Unsupported file type for output: {file_type}")