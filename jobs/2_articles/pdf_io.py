"""Reading PDFs with PyMuPDF and low-level page/image handling."""

import pymupdf

from models import BBox, ImageBlock, TextBlock


def extract_page_elements(page: pymupdf.Page) -> tuple[list[TextBlock], list[ImageBlock]]:
    """The page's text blocks (with font info) and image blocks."""
    text_blocks = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] == 0 and (tb := _text_block(block)) is not None:  # 0 = text, 1 = image
            text_blocks.append(tb)
    return text_blocks, _image_blocks(page)


def _text_block(block: dict) -> TextBlock | None:
    block_text = []
    spans_seen: list[tuple[float, str]] = []
    max_font_size = 0.0
    min_font_size = float("inf")
    is_bold = False
    is_italic = False
    for line in block["lines"]:
        for span in line["spans"]:
            block_text.append(span["text"])
            spans_seen.append((span["size"], span["text"]))
            max_font_size = max(max_font_size, span["size"])
            min_font_size = min(min_font_size, span["size"])
            font_lower = span["font"].lower()
            if "bold" in font_lower:
                is_bold = True
            if "italic" in font_lower or "oblique" in font_lower:
                is_italic = True
        block_text.append("\n")

    # Characters set at the block's largest size: tells a drop cap fused
    # onto a normal line (one character) from a short headline-size label.
    max_font_char_count = sum(len(t) for s, t in spans_seen if round(s, 1) == round(max_font_size, 1))

    text = "".join(block_text).strip()
    # Undo PDF line-wrapping: a hyphenated line break rejoins the split
    # word, any other line break is just wrapping and becomes a space.
    text = text.replace("-\n", "").replace("\n", " ")
    if not text:
        return None
    return TextBlock(
        bbox=BBox.from_tuple(block["bbox"]),
        text=text,
        max_font_size=round(max_font_size, 1),
        min_font_size=round(min_font_size, 1),
        max_font_char_count=max_font_char_count,
        is_bold=is_bold,
        is_italic=is_italic,
        word_count=len(text.split()),
    )


def _image_blocks(page: pymupdf.Page) -> list[ImageBlock]:
    # get_images gives xrefs, get_image_rects their placement on this page.
    image_blocks: list[ImageBlock] = []
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
        except Exception:
            rects = []
        for r in rects:
            image_blocks.append(ImageBlock(bbox=BBox(x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1), xref=xref))
    return image_blocks
