"""From columns to article groups: each column is split into article
segments (at headlines and printed rules), and segments are merged across
columns (by shared headline blocks, and by continuations into the next
column)."""

from collections.abc import Callable
from dataclasses import dataclass, field

from bbox import scaled, union_bbox, x_overlap_frac
from columns import ColumnGrid
from models import BBox, TextBlock

# How far a printed rule may reach into the blocks above/below it and
# still count as lying between them (OCR boxes are a little loose).
RULE_GAP_TOLERANCE_PT = 2.0
# A printed rule at least this wide (fraction of the page) is a section
# rule: it closes off a band of the page that articles flow through column
# by column. ALTO often lists one as several pieces, roughly one per
# column; pieces at about the same height with a small gap are joined.
SECTION_RULE_MIN_WIDTH_FRAC = 0.3
SECTION_RULE_MAX_Y_DIFF_PT = 10.0  # scaled
SECTION_RULE_MAX_X_GAP_PT = 20.0  # scaled
# How much of a column's width a section rule must cover to close off that
# column's band. Low because OCR often catches only part of a rule
# (Tageblatt p. 4: one under a two-column article reaches 48% into the
# second column).
SECTION_RULE_MIN_COLUMN_COVER = 0.25
# A block indented by more than this from both of its column's edges is
# centered: a headline set in body size (Tageblatt p. 14), never running
# text continued from the column before.
CENTERED_MIN_INDENT_PT = 10.0  # scaled


@dataclass
class ArticleGroup:
    """One article's blocks while they're being grouped."""

    blocks: list[TextBlock] = field(default_factory=list)
    block_ids: set[int] = field(default_factory=set)
    flow_bbox: BBox | None = None


def _rule_between(above: TextBlock, below: TextBlock, rules: list[BBox]) -> bool:
    """Whether a printed horizontal rule lies in the gap between two
    blocks of one column and across `below` (at least half of the rule,
    or of the block if it's narrower, overlaps it horizontally)."""
    tol = RULE_GAP_TOLERANCE_PT
    for r in rules:
        if r.y0 < above.bbox.y1 - tol or r.y1 > below.bbox.y0 + tol:
            continue
        overlap = min(r.x1, below.bbox.x1) - max(r.x0, below.bbox.x0)
        if overlap >= 0.5 * min(r.x1 - r.x0, below.bbox.x1 - below.bbox.x0):
            return True
    return False


def guess_article_breaks(
    column_blocks: list[TextBlock],
    rules: list[BBox] = (),
    headline_group_x_overlap: float = 0.5,
    headline_group_max_gap_factor: float = 2.5,
) -> list[list[TextBlock]]:
    """Splits a column's blocks into article segments: a new one starts at a
    headline that follows body text, or below a printed rule.

    Consecutive headlines (a kicker above the headline) stay together only
    if aligned AND close: alignment alone lets a wide headline swallow a
    narrower one further down, closeness alone merges unrelated headlines
    sharing a column. No break at a large gap alone: a column resuming below
    a photo has gaps as large as a new article's, so only what's in the gap
    (a headline, a rule) tells them apart."""
    if not column_blocks:
        return []

    articles: list[list[TextBlock]] = []
    current: list[TextBlock] = []
    prev_headline_block: TextBlock | None = None
    for b in column_blocks:
        same_headline_group = False
        if prev_headline_block is not None:
            gap = b.bbox.y0 - prev_headline_block.bbox.y1
            max_gap = b.median_body_size * headline_group_max_gap_factor
            same_headline_group = (
                gap <= max_gap and x_overlap_frac(b.bbox, prev_headline_block.bbox) >= headline_group_x_overlap
            )
        if current and ((b.looks_like_headline and not same_headline_group) or _rule_between(current[-1], b, rules)):
            articles.append(current)
            current = []
        current.append(b)
        prev_headline_block = b if b.looks_like_headline else None
    if current:
        articles.append(current)

    return articles


def _section_rules(rules: list[BBox], page_width: float) -> list[BBox]:
    """The long rules among `rules` (see SECTION_RULE_MIN_WIDTH_FRAC),
    pieces of one printed rule joined into one."""
    max_dy = scaled(SECTION_RULE_MAX_Y_DIFF_PT, page_width)
    max_gap = scaled(SECTION_RULE_MAX_X_GAP_PT, page_width)
    joined: list[BBox] = []
    for r in sorted(rules, key=lambda r: r.x0):
        for i, j in enumerate(joined):
            if abs(r.y0 - j.y0) <= max_dy and r.x0 - j.x1 <= max_gap:
                joined[i] = union_bbox([j, r])
                break
        else:
            joined.append(r)
    return [j for j in joined if j.x1 - j.x0 >= page_width * SECTION_RULE_MIN_WIDTH_FRAC]


def _rule_covers_column(rule: BBox, boundaries: list[float], col: int) -> bool:
    col_extent = BBox(x0=boundaries[col], y0=rule.y0, x1=boundaries[col + 1], y1=rule.y1)
    return x_overlap_frac(rule, col_extent) >= SECTION_RULE_MIN_COLUMN_COVER


def _band(block: TextBlock, col: int, boundaries: list[float], section_rules: list[BBox]) -> tuple[float, float]:
    """(top, bottom) of the band between section rules that `block` starts
    in, by the rules covering its own column (the page edges if none)."""
    tol = RULE_GAP_TOLERANCE_PT
    top = max(
        (r for r in section_rules if r.y1 <= block.bbox.y0 + tol and _rule_covers_column(r, boundaries, col)),
        key=lambda r: r.y1,
        default=None,
    )
    top_y = top.y1 if top is not None else 0.0
    bottom_y = min(
        (
            r.y0
            for r in section_rules
            if r is not top and r.y0 >= top_y - tol and _rule_covers_column(r, boundaries, col)
        ),
        default=float("inf"),
    )
    return top_y, bottom_y


def _segment_continued(
    col_segments: list[list[list[TextBlock]]], col: int, top_y: float, bottom_y: float
) -> list[TextBlock] | None:
    """The lowest segment ending within the band in the nearest column to
    the left of `col` that has body text there (where a band's columns are
    narrower than the page's, grid columns can be empty or hold only
    spanning headlines and fragments: Tageblatt pp. 6, 18)."""
    tol = RULE_GAP_TOLERANCE_PT
    for left in range(col - 1, -1, -1):
        in_band = [s for s in col_segments[left] if top_y + tol < s[-1].bbox.y1 <= bottom_y + tol]
        if any(not b.looks_like_headline and not b.excluded_short for s in in_band for b in s):
            return max(in_band, key=lambda s: s[-1].bbox.y1)
    return None


def _link_column_continuations(
    boundaries: list[float],
    col_segments: list[list[list[TextBlock]]],
    section_rules: list[BBox],
    union: Callable[[int, int], None],
) -> None:
    """Joins an article continued into the next column without a headline:
    within a band between section rules, a headless segment at the top of
    its column continues the segment ending lowest in the column to its
    left. Nothing else links the two.

    The band comes from the segment's own column: OCR often misses pieces
    of a rule (Tageblatt p. 5), or the article on the left runs past it
    (p. 15). A centered first block is an unflagged headline. Does nothing
    without section rules (always the case for PDF text): a modern page
    starts many columns headless with things that aren't continuations.

    `col_segments[i]`: column i's segments, top to bottom."""
    if not section_rules:
        return
    tol = RULE_GAP_TOLERANCE_PT
    # The last boundary is always the page's right edge.
    min_indent = scaled(CENTERED_MIN_INDENT_PT, boundaries[-1])

    def median(values: list[float]) -> float:
        return sorted(values)[len(values) // 2]

    for col in range(1, len(col_segments)):
        body = [b for seg in col_segments[col] for b in seg if not b.looks_like_headline]
        if not body:
            continue
        col_x0, col_x1 = median([b.bbox.x0 for b in body]), median([b.bbox.x1 for b in body])
        for i, seg in enumerate(col_segments[col]):
            first = seg[0]
            if first.looks_like_headline or first.is_caption:
                continue
            if first.bbox.x0 - col_x0 > min_indent and col_x1 - first.bbox.x1 > min_indent:
                continue  # centered: an unflagged headline
            top_y, bottom_y = _band(first, col, boundaries, section_rules)
            if i > 0 and col_segments[col][i - 1][-1].bbox.y1 > top_y + tol:
                continue  # not the top of its column within the band
            continued = _segment_continued(col_segments, col, top_y, bottom_y)
            if continued is not None:
                union(id(first), id(continued[0]))


def merge_column_segments_into_groups(grids: list[ColumnGrid], rules: list[BBox] = ()) -> list[ArticleGroup]:
    """Merges every grid's column segments into article groups (union-find
    over blocks): blocks that share a segment in any column end up in one
    group. Matching segments by their first block instead breaks when
    columns split an article at different points (a neighbour's headline
    wedged into one column), giving duplicate articles."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    segments: list[list[TextBlock]] = []
    for boundaries, columns in grids:
        col_segments = [guess_article_breaks(col, rules) for col in columns]
        for article_blocks in (seg for segs in col_segments for seg in segs):
            segments.append(article_blocks)
            first_id = id(article_blocks[0])
            for b in article_blocks[1:]:
                union(first_id, id(b))
        # The last boundary is always the page's right edge.
        _link_column_continuations(boundaries, col_segments, _section_rules(rules, boundaries[-1]), union)

    groups: dict[int, ArticleGroup] = {}
    for article_blocks in segments:
        for b in article_blocks:
            root = find(id(b))
            group = groups.setdefault(root, ArticleGroup())
            if id(b) not in group.block_ids:
                group.block_ids.add(id(b))
                group.blocks.append(b)

    return list(groups.values())
