from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from font_manager import get_font_path

def _fit_font(draw, text, box_w, box_h, font_path, max_size=40, min_size=10):
    size = max_size
    while size > min_size:
        font = ImageFont.truetype(str(font_path), size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= box_w and h <= box_h:
            return font
        size -= 1
    return ImageFont.truetype(str(font_path), min_size)

def reconstruct_image(input_path: Path, output_path: Path, lines: list[dict],
                       translated_lines: list[str], target_lang: str) -> None:
    img = Image.open(str(input_path)).convert("RGB")
    draw = ImageDraw.Draw(img)
    font_path = get_font_path(target_lang)

    for line, new_text in zip(lines, translated_lines):
        x0, y0, x1, y1 = line["bbox"]
        # sample a background pixel just outside the box, blank the region
        bg = img.getpixel((max(x0 - 2, 0), max(y0 - 2, 0)))
        draw.rectangle([x0, y0, x1, y1], fill=bg)
        box_w, box_h = x1 - x0, y1 - y0
        font = _fit_font(draw, new_text, box_w, box_h, font_path)
        draw.text((x0, y0), new_text, font=font, fill=(0, 0, 0))

    img.save(str(output_path))