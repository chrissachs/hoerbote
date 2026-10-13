"""Font- and position-based block labels (headline, masthead): the baseline
that layout_boundaries refines with the layout model's regions."""

from bbox import scaled
from models import TextBlock

# Shorter blocks are `excluded_short`: they don't anchor the column grid.
MIN_WORDS_FOR_COLUMN_CLUSTERING = 40
# A block near the page top that spans most of the width, or sits flush
# against the left margin, is masthead/dateline furniture.
MASTHEAD_MAX_Y0 = 70.0  # pt, scaled
MASTHEAD_MIN_WIDTH_FRAC = 0.7
MASTHEAD_MAX_X0 = 50.0  # pt, scaled
# Font-size steps above the body median that make a block a headline (any
# block / a bold one).
HEADLINE_FONT_JUMP_PT = 2.5  # scaled
HEADLINE_BOLD_FONT_JUMP_PT = 1.0  # scaled


def flag_headlines(text_blocks: list[TextBlock], page_width: float) -> None:
    """Sets `median_body_size` (one page-wide body-size baseline) and
    `looks_like_headline`: notably larger than body text, or bold and a
    little larger. Never italic (an italic pull-quote can sit between body
    and headline size). Masthead furniture is never a headline, and is
    excluded from the flow: a full-width "headline" would span every column
    and bridge unrelated articles."""
    if not text_blocks:
        return

    body_sizes = [b.max_font_size for b in text_blocks if not b.excluded_short]
    if not body_sizes:
        body_sizes = [b.max_font_size for b in text_blocks]
    median_body = sorted(body_sizes)[len(body_sizes) // 2]
    font_jump = scaled(HEADLINE_FONT_JUMP_PT, page_width)
    bold_font_jump = scaled(HEADLINE_BOLD_FONT_JUMP_PT, page_width)
    masthead_max_y0 = scaled(MASTHEAD_MAX_Y0, page_width)
    masthead_max_x0 = scaled(MASTHEAD_MAX_X0, page_width)
    # The text's own extent, not the page's: what "spans the width" means
    # for a running banner.
    content_width = max(b.bbox.x1 for b in text_blocks)

    for b in text_blocks:
        b.median_body_size = median_body
        b.looks_like_headline = not b.is_italic and (
            b.max_font_size >= median_body + font_jump
            or (b.is_bold and b.max_font_size >= median_body + bold_font_jump)
        )
        # A running banner across the page, or a page/section label flush
        # with the left margin (a top-of-page teaser starts further right).
        is_masthead = b.bbox.y0 <= masthead_max_y0 and (
            (b.bbox.x1 - b.bbox.x0) >= content_width * MASTHEAD_MIN_WIDTH_FRAC or b.bbox.x0 <= masthead_max_x0
        )
        if is_masthead:
            b.looks_like_headline = False
            b.excluded_from_flow = True
