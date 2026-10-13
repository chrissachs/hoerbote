"""A page's text from ALTO XML (OCR of a scan): the same TextBlock list as
pdf_io.extract_page_elements, so nothing after the reader knows the
difference.

What differs from the PDF reader:
- Coordinates are scan pixels; scaled to PDF points by the page width
  ratio (PDF page and ALTO page have the same aspect ratio).
- ALTO's own TextBlocks are too coarse (headline, subhead and body often
  one block), so blocks are rebuilt from lines: consecutive lines of one
  ALTO block that fall into the same layout region (by line centre) form
  one TextBlock. That keeps PDF-like paragraph blocks, split wherever the
  layout model saw a boundary.
- Font sizes: ALTO's FONTSIZE is points on the original paper, but the
  heuristics mix font sizes with box geometry (e.g. "a gap of 2.5x the body
  size"), so both must be PDF points. The scan's resolution isn't in the
  ALTO, so the factor is measured per page: in PDF text a line's box is
  as high as its font size (checked on a modern PDF: ratio 1.0), so it's the
  median of line height (PDF points) / FONTSIZE -- ~0.5 on the Berliner
  Tageblatt.
- No embedded images: the scan is one picture, and nothing after this job
  uses extracted images anyway.
- Printed rules: ALTO lists them as GraphicalElements, which the PDF
  reader has no counterpart for. extract_alto_rules returns the
  horizontal ones; articles break at them."""

import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from layout_cache import LayoutRegion
from models import BBox, TextBlock

# A GraphicalElement at least this many times wider than high is a
# printed horizontal rule (separator line), not a picture or a stain.
RULE_MIN_ASPECT = 8


@dataclass
class _Line:
    bbox: BBox
    words: list[str]
    # (font size, characters) per word, for max_font_char_count.
    sizes: list[tuple[float, int]]
    # Characters in bold words: a block counts as bold only when most of
    # its text is (a bold dateline alone doesn't make a paragraph bold).
    bold_chars: int
    italic: bool


@dataclass
class _Group:
    region: int | None
    lines: list[_Line] = field(default_factory=list)


def _local(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c) == name]


def _styles(root: ET.Element) -> dict[str, tuple[float | None, str]]:
    """TextStyle id -> (font size, FONTSTYLE)."""
    out = {}
    for el in root.iter():
        if _local(el) == "TextStyle":
            size = el.get("FONTSIZE")
            out[el.get("ID")] = (float(size) if size else None, el.get("FONTSTYLE", ""))
    return out


def _style_of(el: ET.Element, styles: dict, inherited: tuple[float | None, str]) -> tuple[float | None, str]:
    # STYLEREFS can list several ids (text style + paragraph style); the
    # first known text style wins, else the enclosing element's.
    for ref in (el.get("STYLEREFS") or "").split():
        if ref in styles:
            return styles[ref]
    return inherited


def _region_of(bbox: BBox, regions: list[LayoutRegion]) -> int | None:
    """Index of the smallest region containing the line's centre (regions
    can nest/overlap; the smallest is the most specific)."""
    cx, cy = (bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2
    best, best_area = None, float("inf")
    for i, r in enumerate(regions):
        b = r.bbox
        if b.x0 <= cx <= b.x1 and b.y0 <= cy <= b.y1:
            area = (b.x1 - b.x0) * (b.y1 - b.y0)
            if area < best_area:
                best, best_area = i, area
    return best


def _read_lines(text_block: ET.Element, styles: dict, scale: float) -> list[_Line]:
    block_style = _style_of(text_block, styles, (None, ""))
    lines = []
    for tl in _children(text_block, "TextLine"):
        line_style = _style_of(tl, styles, block_style)
        words, sizes, bold_chars, italic = [], [], 0, False
        for s in _children(tl, "String"):
            subs_type = s.get("SUBS_TYPE")
            if subs_type == "HypPart2":
                continue  # already emitted whole with its HypPart1
            word = s.get("SUBS_CONTENT") if subs_type == "HypPart1" and s.get("SUBS_CONTENT") else s.get("CONTENT", "")
            if not word:
                continue
            size, fontstyle = _style_of(s, styles, line_style)
            style = f"{s.get('STYLE', '')} {fontstyle}"
            if "bold" in style:
                bold_chars += len(word)
            italic = italic or "italic" in style
            words.append(word)
            if size:
                sizes.append((size, len(word)))
        if not words:
            continue
        x, y, w, h = (float(tl.get(k)) * scale for k in ("HPOS", "VPOS", "WIDTH", "HEIGHT"))
        lines.append(_Line(BBox(x0=x, y0=y, x1=x + w, y1=y + h), words, sizes, bold_chars, italic))
    return lines


def _font_scale(lines: list[_Line]) -> float:
    """PDF points per ALTO font point on this page (see module docstring);
    1.0 when no line states a size."""
    ratios = [(line.bbox.y1 - line.bbox.y0) / max(s for s, _ in line.sizes) for line in lines if line.sizes]
    return statistics.median(ratios) if ratios else 1.0


def _to_text_block(lines: list[_Line], font_scale: float) -> TextBlock:
    text = " ".join(w for line in lines for w in line.words)
    sizes = [(s * font_scale, n) for line in lines for s, n in line.sizes]
    max_size = max((s for s, _ in sizes), default=0.0)
    min_size = min((s for s, _ in sizes), default=None)
    return TextBlock(
        bbox=BBox(
            x0=min(line.bbox.x0 for line in lines),
            y0=min(line.bbox.y0 for line in lines),
            x1=max(line.bbox.x1 for line in lines),
            y1=max(line.bbox.y1 for line in lines),
        ),
        text=text,
        max_font_size=round(max_size, 1),
        min_font_size=round(min_size, 1) if min_size is not None else None,
        max_font_char_count=sum(n for s, n in sizes if s == max_size),
        is_bold=sum(line.bold_chars for line in lines) * 2 > sum(len(w) for line in lines for w in line.words),
        is_italic=any(line.italic for line in lines),
        word_count=len(text.split()),
    )


def extract_alto_text_blocks(alto_path: Path, page_width_pt: float, regions: list[LayoutRegion]) -> list[TextBlock]:
    """`regions` in PDF points (layout_boundaries.load_regions_in_points),
    used only to split ALTO's coarse blocks -- classification stays
    apply_layout_labels' job, exactly as for PDF text."""
    root = ET.parse(alto_path).getroot()
    page = next(el for el in root.iter() if _local(el) == "Page")
    scale = page_width_pt / float(page.get("WIDTH"))
    styles = _styles(root)

    alto_blocks = [_read_lines(tb, styles, scale) for tb in root.iter() if _local(tb) == "TextBlock"]
    font_scale = _font_scale([line for lines in alto_blocks for line in lines])

    blocks: list[TextBlock] = []
    for lines in alto_blocks:
        groups: list[_Group] = []
        for line in lines:
            region = _region_of(line.bbox, regions)
            if not groups or groups[-1].region != region:
                groups.append(_Group(region))
            groups[-1].lines.append(line)
        blocks.extend(_to_text_block(g.lines, font_scale) for g in groups)
    return blocks


def extract_alto_rules(alto_path: Path, page_width_pt: float) -> list[BBox]:
    """The page's printed horizontal rules, in PDF points. In the papers
    seen so far (Berliner Tageblatt) they separate articles: short ones
    between items in a column, long ones between page sections."""
    root = ET.parse(alto_path).getroot()
    page = next(el for el in root.iter() if _local(el) == "Page")
    scale = page_width_pt / float(page.get("WIDTH"))
    rules = []
    for el in root.iter():
        if _local(el) != "GraphicalElement":
            continue
        x, y, w, h = (float(el.get(k)) * scale for k in ("HPOS", "VPOS", "WIDTH", "HEIGHT"))
        if w >= h * RULE_MIN_ASPECT:
            rules.append(BBox(x0=x, y0=y, x1=x + w, y1=y + h))
    return rules
