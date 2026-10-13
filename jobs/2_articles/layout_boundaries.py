"""Layout-model labels for the page's text blocks: each block is matched to
the layout region its centre falls in, and the region's label refines the
font-based labels (labels.py). Never used for ordering or grouping.

The layout model (Surya) detects regions well, but labels a headline, a
kicker and a mid-article subhead all SectionHeader -- font size relative
to the body text tells them apart (classify_section_header)."""

from pathlib import Path

import pymupdf

from articles import extract_articles_from_labeled_blocks
from bbox import bbox_overlap_area, x_overlap_frac
from labels import MIN_WORDS_FOR_COLUMN_CLUSTERING, flag_headlines
from layout_cache import LayoutRegion, load_region_cache
from models import Article, BBox, ImageBlock, TextBlock

HEADLINE_MIN_RATIO = 1.7  # font size vs. body median -> real article-starting headline
KICKER_MAX_RATIO = 1.6  # font size vs. body median, bold + non-italic -> candidate kicker
# Real headlines stay short; a bold, oversized lead paragraph also crosses
# HEADLINE_MIN_RATIO but is body text.
HEADLINE_MAX_WORDS = 15
# A block (or a block's headline-size part) this short is a drop cap, never
# a headline.
DROPCAP_MAX_CHARS = 3
# How far below a SectionHeader block (in body font sizes) the next block
# may start for the kicker check (it must be headline-size). Found by
# geometry, not by the layout model's reading order.
KICKER_LOOKAHEAD_MAX_GAP_FACTOR = 4.0

FLOW_LABELS = {"Text", "SectionHeader"}
SKIP_LABELS = {"PageHeader", "PageFooter"}


def to_points(region: LayoutRegion, dpi: float) -> LayoutRegion:
    """Convert a region's bbox from the pixel space it was detected in (a
    page rendered at `dpi`) to PDF point space, matching TextBlock.bbox
    (straight from PyMuPDF, unscaled) so the two can be matched by bbox."""
    scale = dpi / 72
    b = region.bbox
    return LayoutRegion(
        position=region.position,
        label=region.label,
        bbox=BBox(x0=b.x0 / scale, y0=b.y0 / scale, x1=b.x1 / scale, y1=b.y1 / scale),
    )


def load_regions_in_points(cache_path: Path) -> list[LayoutRegion]:
    """Load a pageN.layout.json cache with its regions converted to PDF
    point space, using the DPI the cache records it was rendered at (see
    LayoutRegionCache) -- never an assumed one."""
    cache = load_region_cache(cache_path)
    return [to_points(r, dpi=cache.dpi) for r in cache.regions]


def _block_center_in_bbox(block_bbox: BBox, region_bbox: BBox) -> bool:
    cx = (block_bbox.x0 + block_bbox.x1) / 2
    cy = (block_bbox.y0 + block_bbox.y1) / 2
    return region_bbox.x0 <= cx <= region_bbox.x1 and region_bbox.y0 <= cy <= region_bbox.y1


def match_blocks_to_region(region: LayoutRegion, blocks: list[TextBlock]) -> list[TextBlock]:
    """PyMuPDF text blocks whose center falls inside this region, in
    top-to-bottom reading order. A region can legitimately match zero blocks
    (e.g. a Picture, or a SectionHeader over decorative/unrecognized text)
    or several (a multi-paragraph Text region). Region and blocks must
    already share a coordinate space -- see to_points."""
    matched = [b for b in blocks if _block_center_in_bbox(b.bbox, region.bbox)]
    matched.sort(key=lambda b: (b.bbox.y0, b.bbox.x0))
    return matched


def classify_section_header(
    font_size: float, is_bold: bool, is_italic: bool, body_median: float, next_font_size: float | None
) -> str:
    """ "headline" (starts an article), "kicker" (belongs to the headline
    below it) or "subhead" (stays in the current article)."""
    ratio = font_size / body_median if body_median else 1.0
    if ratio >= HEADLINE_MIN_RATIO:
        return "headline"
    if (
        is_bold
        and not is_italic
        and ratio <= KICKER_MAX_RATIO
        and next_font_size is not None
        and next_font_size / body_median >= HEADLINE_MIN_RATIO
    ):
        return "kicker"
    return "subhead"


def _nearest_block_below(b: TextBlock, candidates: list[TextBlock], max_gap: float) -> TextBlock | None:
    """Closest block below `b` that overlaps it horizontally and starts
    within `max_gap` of its bottom edge."""
    below = [
        c
        for c in candidates
        if c is not b and -2 <= c.bbox.y0 - b.bbox.y1 <= max_gap and x_overlap_frac(b.bbox, c.bbox) > 0
    ]
    return min(below, key=lambda c: c.bbox.y0) if below else None


def _nearest_block_above(b: TextBlock, candidates: list[TextBlock]) -> TextBlock | None:
    """Closest block above `b` that overlaps it horizontally, however far."""
    above = [c for c in candidates if c is not b and c.bbox.y1 <= b.bbox.y0 + 2 and x_overlap_frac(b.bbox, c.bbox) > 0]
    return max(above, key=lambda c: c.bbox.y1) if above else None


# A block in a non-flow region (e.g. Picture) is still text if this much of
# it also lies in a Text/SectionHeader region: the model drew a Picture
# over plain text.
MIN_TEXT_RESCUE_OVERLAP_FRAC = 0.3
# The gap above a block (in body font sizes) from which _flag_isolated_blocks
# checks whether it's isolated; ordinary paragraph gaps never come close.
ISOLATION_MIN_GAP_FACTOR = 10.0


def _flag_isolated_blocks(text_blocks: list[TextBlock], body_median: float, ad_region_excluded_ids: set[int]) -> None:
    """Excludes a block below a large gap (ISOLATION_MIN_GAP_FACTOR) that is
    empty across the whole page: ad/furniture boilerplate in a dead zone.
    Gap size alone can't tell (a column resuming below a photo has a gap as
    large), but there the rest of the page carries on beside the gap.

    Goes top to bottom, so an excluded fragment no longer anchors the next
    one's gap (two adjacent fragments would otherwise vouch for each other).
    Blocks in `ad_region_excluded_ids` (Picture/Figure regions) don't count
    as content; blocks excluded for other reasons do: those may be real
    text a mislabeled region hides, and skipping them would widen the loss."""
    isolation_min_gap = body_median * ISOLATION_MIN_GAP_FACTOR
    isolation_excluded_ids: set[int] = set()

    def _counts_as_real(c: TextBlock) -> bool:
        return not (id(c) in ad_region_excluded_ids or id(c) in isolation_excluded_ids)

    ordered = sorted((b for b in text_blocks if not b.excluded_from_flow), key=lambda b: b.bbox.y0)
    for b in ordered:
        if b.excluded_from_flow or b.is_caption or b.looks_like_headline:
            continue
        live = [c for c in text_blocks if c is not b and _counts_as_real(c)]
        prev = _nearest_block_above(b, live)
        prev_edge = prev.bbox.y1 if prev is not None else 0.0
        if b.bbox.y0 - prev_edge < isolation_min_gap:
            continue
        span_has_other_content = any(
            len(c.text.strip()) >= DROPCAP_MAX_CHARS and c.bbox.y0 < b.bbox.y0 and c.bbox.y1 > prev_edge for c in live
        )
        if not span_has_other_content:
            b.excluded_from_flow = True
            isolation_excluded_ids.add(id(b))


def _overlaps_flow_region(block: TextBlock, regions: list[LayoutRegion]) -> bool:
    block_area = (block.bbox.x1 - block.bbox.x0) * (block.bbox.y1 - block.bbox.y0)
    if block_area <= 0:
        return False
    return any(
        r.label in FLOW_LABELS and bbox_overlap_area(block.bbox, r.bbox) / block_area >= MIN_TEXT_RESCUE_OVERLAP_FRAC
        for r in regions
    )


def apply_layout_labels(
    regions: list[LayoutRegion], text_blocks: list[TextBlock], image_blocks: list[ImageBlock], page_width: float
) -> None:
    """Labels every block: the font-based labels first (so a block the model
    found no region for still gets them), then refined by its region:
    - Text/SectionHeader: headline/kicker/subhead by font size, whichever
      of the two labels the model chose (a kicker gets either about equally
      often). A kicker counts as a headline, so it groups with the headline
      below it.
    - Caption: a caption, of the image it overlaps most.
    - PageHeader/PageFooter, Picture/Figure, Table, ...: excluded from the
      flow -- usually ads, listings or furniture, which pollute far more
      articles than keeping them rescues.
    Mutates `text_blocks`."""
    for b in text_blocks:
        b.excluded_short = b.word_count < MIN_WORDS_FOR_COLUMN_CLUSTERING
    flag_headlines(text_blocks, page_width)
    body_median = text_blocks[0].median_body_size if text_blocks else 0.0

    # Excluded for a Picture/Figure region: the one non-flow label known to
    # be ad noise (see _flag_isolated_blocks).
    ad_region_excluded_ids: set[int] = set()
    for region in regions:
        bs = match_blocks_to_region(region, text_blocks)
        if not bs or region.label in SKIP_LABELS:
            for b in bs:
                b.excluded_from_flow = True
        elif region.label == "Caption":
            for b in bs:
                _label_caption(b, image_blocks)
        elif region.label not in FLOW_LABELS:
            for b in bs:
                if not _overlaps_flow_region(b, regions):
                    b.excluded_from_flow = True
                    if region.label in ("Picture", "Figure"):
                        ad_region_excluded_ids.add(id(b))
        else:
            candidates = [c for c in text_blocks if not c.excluded_from_flow]
            for b in bs:
                _label_section_header(b, candidates, body_median)

    _flag_isolated_blocks(text_blocks, body_median, ad_region_excluded_ids)


def _label_caption(b: TextBlock, image_blocks: list[ImageBlock]) -> None:
    b.is_caption = True
    best_img, best_area = None, 0.0
    for img in image_blocks:
        area = bbox_overlap_area(b.bbox, img.bbox)
        if area > best_area:
            best_area, best_img = area, img
    if best_img is not None:
        b.caption_image = best_img


def _label_section_header(b: TextBlock, candidates: list[TextBlock], body_median: float) -> None:
    """Headline/kicker/subhead for a block in a Text/SectionHeader region."""
    next_block = _nearest_block_below(b, candidates, body_median * KICKER_LOOKAHEAD_MAX_GAP_FACTOR)
    next_font = next_block.max_font_size if next_block else None
    role = classify_section_header(b.max_font_size, b.is_bold, b.is_italic, body_median, next_font)
    if role == "headline" and (len(b.text.strip()) < DROPCAP_MAX_CHARS or b.word_count > HEADLINE_MAX_WORDS):
        # A split-off drop cap or a whole paragraph: headline-size, but not a
        # headline. (Kickers may be long or short, so they're left alone.)
        role = "subhead"
    if (
        role == "headline"
        and b.min_font_size is not None
        and b.min_font_size / body_median <= KICKER_MAX_RATIO
        and b.max_font_char_count is not None
        and b.max_font_char_count < DROPCAP_MAX_CHARS
    ):
        # A drop cap fused with a body line into one block: max_font_size is
        # just the one big glyph. A headline whose big part is most of its
        # characters stays one.
        role = "subhead"
    b.looks_like_headline = role in ("headline", "kicker")


def extract_articles_via_layout_model(
    text_blocks: list[TextBlock],
    image_blocks: list[ImageBlock],
    page: pymupdf.Page,
    page_num: int,
    page_width: float,
    cache_dir: Path,
    rules: list[BBox] = (),
) -> tuple[list[float], list[Article]]:
    """(column_boundaries, articles) for one page; mutates `text_blocks`.
    Raises if the layout job's cache for the page is missing: this job
    never runs the model itself."""
    cache_path = cache_dir / f"page{page_num}.layout.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"{cache_path} does not exist -- the layout job must produce it before the articles job can run."
        )
    regions = load_regions_in_points(cache_path)
    apply_layout_labels(regions, text_blocks, image_blocks, page_width)
    return extract_articles_from_labeled_blocks(text_blocks, image_blocks, page_width, rules)
