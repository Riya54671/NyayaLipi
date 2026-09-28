from pathlib import Path
import fitz
from font_manager import get_font_path

def reconstruct_pdf(input_path: Path, output_path: Path, lines: list[dict],
                     translated_lines: list[str], target_lang: str) -> None:
    doc = fitz.open(str(input_path))
    font_path = str(get_font_path(target_lang))
    font_alias = "customfont"

    # Register the font ONCE, on the first page only — not in a loop over every page
    if len(doc) > 0:
        doc[0].insert_font(fontname=font_alias, fontfile=font_path)

    for line, new_text in zip(lines, translated_lines):
        page = doc[line["page"]]
        rect = fitz.Rect(line["bbox"])
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        size = 11
        while size > 6:
            rc = page.insert_textbox(rect, new_text, fontsize=size,
                                      fontname=font_alias, align=0)
            if rc >= 0:
                break
            size -= 1

    doc.save(str(output_path), garbage=4, deflate=True)