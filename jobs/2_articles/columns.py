"""The page's column grid: column boundaries from where body blocks start,
local grids for photo strips, and every flow block assigned to its
column(s)."""

from bbox import compute_column_overlaps, nearest_column, scaled, x_overlap_frac
from models import ImageBlock, TextBlock

# Two block x0s further apart than this start a new column.
COLUMN_GAP_TOLERANCE_PT = 20.0  # scaled
# A block wider than this can't anchor the column grid -- it's either a
# headline (handled separately) or an anomaly like an ad disclaimer line.
MAX_COLUMN_ANCHOR_WIDTH_FRAC = 0.5
# A headline is often narrower than the columns it introduces, so its
# outermost column can land just under headline_touch_frac. Edge rescue
# (resolve_headline_column_spans) takes it if either holds: a fraction alone
# misses cases on wide-column pages, absolute points on narrow-column ones.
HEADLINE_EDGE_EXTEND_MIN_FRAC = 0.2
HEADLINE_EDGE_EXTEND_MIN_ABS_PT = 30.0  # scaled

# Photo strips (see detect_column_zones). Images whose top edges are this
# close are candidates for one row; within a row they may overlap
# horizontally by this fraction of the narrower one.
IMAGE_ROW_Y0_TOLERANCE = 20.0  # pt, scaled
MAX_ROW_X_OVERLAP_FRAC = 0.2
MIN_IMAGES_FOR_ROW = 2
# Smaller images (an icon inside an ad, a rule rendered as an image) don't
# count as photos.
MIN_PHOTO_DIMENSION = 80.0  # pt, scaled
# A zone starts this far above its photo row, to take a heading with it.
ZONE_Y_PADDING = 15.0  # pt, scaled
# A zone needs this many blocks, which on their own must still form more
# than one column (else it's just one oddly narrow block).
MIN_ZONE_BLOCKS = 2

ColumnGrid = tuple[list[float], list[list[TextBlock]]]


def compute_column_boundaries(
    blocks: list[TextBlock], page_width: float, tolerance: float | None = None
) -> list[float]:
    """Column dividers at gaps between block x0s larger than `tolerance`.

    A divider sits midway between the previous column's rightmost extent and
    the next column's x0, not between the two x0s: columns are often
    narrower than the distance between their left edges, and an x0 midpoint
    would land inside the wider column's text.

    `blocks` should be the ones trusted to reflect the real grid (no short
    furniture text); assign_to_columns then places every block."""
    if not blocks:
        return [0, page_width]
    if tolerance is None:
        tolerance = scaled(COLUMN_GAP_TOLERANCE_PT, page_width)

    ordered = sorted(blocks, key=lambda b: b.bbox.x0)
    boundaries = [0.0]
    cluster_max_x1 = ordered[0].bbox.x1
    prev_x0 = ordered[0].bbox.x0
    for b in ordered[1:]:
        if b.bbox.x0 - prev_x0 > tolerance:
            boundaries.append((cluster_max_x1 + b.bbox.x0) / 2)
            cluster_max_x1 = b.bbox.x1
        else:
            cluster_max_x1 = max(cluster_max_x1, b.bbox.x1)
        prev_x0 = b.bbox.x0
    boundaries.append(page_width)
    return sorted(set(boundaries))


def resolve_headline_column_spans(
    headline_blocks: list[TextBlock], boundaries: list[float], headline_touch_frac: float = 0.45
) -> list[list[int] | None]:
    """Which columns each headline spans.

    A column the headline only brushes can be genuine centered spanning or
    spillover from a competing headline in the same row; overlap alone
    can't tell. So when two headlines overlap in y and touch the same
    column, the larger overlap wins it. Then edge rescue extends each span
    outward while the next column is still owned and clears
    HEADLINE_EDGE_EXTEND_MIN_FRAC / _ABS_PT."""
    overlaps = [compute_column_overlaps(b.bbox, boundaries) for b in headline_blocks]
    owned = [set(f.keys()) for f in overlaps]

    for i, bi in enumerate(headline_blocks):
        for j, bj in enumerate(headline_blocks):
            if i == j:
                continue
            if bi.bbox.y1 <= bj.bbox.y0 or bj.bbox.y1 <= bi.bbox.y0:
                continue  # y-ranges don't overlap: not competing
            for col in set(overlaps[i]) & set(overlaps[j]):
                if overlaps[i][col] < overlaps[j][col] or (overlaps[i][col] == overlaps[j][col] and i > j):
                    owned[i].discard(col)

    # The last boundary is always the page's right edge.
    min_abs = scaled(HEADLINE_EDGE_EXTEND_MIN_ABS_PT, boundaries[-1])

    def _clears_edge_rescue(frac: float, width: float) -> bool:
        return frac >= HEADLINE_EDGE_EXTEND_MIN_FRAC or frac * width >= min_abs

    spans: list[list[int] | None] = []
    for i in range(len(headline_blocks)):
        touched = sorted(c for c in owned[i] if overlaps[i][c] >= headline_touch_frac)
        if not touched:
            spans.append(None)
            continue
        lo, hi = touched[0], touched[-1]
        while lo - 1 in owned[i] and _clears_edge_rescue(overlaps[i][lo - 1], boundaries[lo] - boundaries[lo - 1]):
            lo -= 1
        while hi + 1 in owned[i] and _clears_edge_rescue(overlaps[i][hi + 1], boundaries[hi + 2] - boundaries[hi + 1]):
            hi += 1
        spans.append(list(range(lo, hi + 1)))
    return spans


def assign_to_columns(
    blocks: list[TextBlock], boundaries: list[float], headline_touch_frac: float = 0.45
) -> list[list[TextBlock]]:
    """Blocks per column, top to bottom; one list per column, empty ones
    included. Body text goes to its nearest column, a headline to every
    column it spans (the same block object in each list; segments are later
    merged by identity). Sets each block's `columns`."""
    n = len(boundaries) - 1
    columns: list[list[TextBlock]] = [[] for _ in range(n)]

    headline_blocks = [b for b in blocks if b.looks_like_headline]
    spans_by_id: dict[int, list[int] | None] = {}
    if headline_blocks:
        for b, span in zip(
            headline_blocks,
            resolve_headline_column_spans(headline_blocks, boundaries, headline_touch_frac),
            strict=True,
        ):
            spans_by_id[id(b)] = span

    for b in blocks:
        if b.looks_like_headline:
            spanned = spans_by_id[id(b)] or [nearest_column(b.bbox, boundaries)]
        else:
            spanned = [nearest_column(b.bbox, boundaries)]
        b.columns = spanned
        for i in spanned:
            columns[i].append(b)

    for col in columns:
        col.sort(key=lambda b: b.bbox.y0)

    return columns


def build_column_grids(
    flow_blocks: list[TextBlock], image_blocks: list[ImageBlock], page_width: float
) -> tuple[list[float], list[ColumnGrid]]:
    """The page's main column boundaries, and (boundaries, columns) for the
    main grid plus one per photo-strip zone."""
    # Only substantial, single-column body blocks anchor the grid; the rest
    # (short ones, headlines, anything anomalously wide like a one-line ad
    # disclaimer, which would distort the x0 clustering) are still placed
    # by the boundaries the anchors establish.
    content_blocks = [
        b
        for b in flow_blocks
        if not b.excluded_short
        and not b.looks_like_headline
        and (b.bbox.x1 - b.bbox.x0) <= page_width * MAX_COLUMN_ANCHOR_WIDTH_FRAC
    ]
    boundaries, zone_bounds = detect_column_zones(content_blocks, image_blocks, page_width)

    zone_grids: list[ColumnGrid] = []
    zoned_ids: set[int] = set()
    for zone_y0, zone_x0 in zone_bounds:
        zone_blocks = [
            b
            for b in flow_blocks
            if id(b) not in zoned_ids
            and b.bbox.y0 >= zone_y0
            and b.bbox.x0 >= zone_x0
            # A wide headline is left to the main grid's span resolution; a
            # narrow one belongs to the zone.
            and not (b.looks_like_headline and (b.bbox.x1 - b.bbox.x0) > page_width * MAX_COLUMN_ANCHOR_WIDTH_FRAC)
        ]
        if not zone_blocks:
            continue
        zoned_ids.update(id(b) for b in zone_blocks)
        zone_boundaries = compute_column_boundaries(zone_blocks, page_width)
        zone_grids.append((zone_boundaries, assign_to_columns(zone_blocks, zone_boundaries)))

    main_flow_blocks = [b for b in flow_blocks if id(b) not in zoned_ids]
    return boundaries, [(boundaries, assign_to_columns(main_flow_blocks, boundaries))] + zone_grids


def _cluster_image_rows(images: list[ImageBlock], y0_tolerance: float) -> list[list[ImageBlock]]:
    """Images in side-by-side rows: top edges within `y0_tolerance`, and
    hardly overlapping horizontally (MAX_ROW_X_OVERLAP_FRAC). Not "one ends
    near where the next starts": that also matches unrelated images that
    just happen to meet at the same height."""
    ordered = sorted(images, key=lambda i: i.bbox.y0)
    rows: list[list[ImageBlock]] = []
    for img in ordered:
        row = next(
            (
                r
                for r in rows
                if abs(img.bbox.y0 - r[0].bbox.y0) <= y0_tolerance
                and all(x_overlap_frac(img.bbox, other.bbox) <= MAX_ROW_X_OVERLAP_FRAC for other in r)
            ),
            None,
        )
        if row is not None:
            row.append(img)
        else:
            rows.append([img])
    return rows


def _photo_images(image_blocks: list[ImageBlock], page_width: float) -> list[ImageBlock]:
    """Images big enough to be photos, minus any nested inside another (a
    logo within an ad isn't a second photo next to it)."""
    min_photo = scaled(MIN_PHOTO_DIMENSION, page_width)
    photos = [
        img
        for img in image_blocks
        if (img.bbox.x1 - img.bbox.x0) >= min_photo and (img.bbox.y1 - img.bbox.y0) >= min_photo
    ]
    return [
        img
        for img in photos
        if not any(
            other is not img
            and other.bbox.x0 <= img.bbox.x0
            and other.bbox.y0 <= img.bbox.y0
            and other.bbox.x1 >= img.bbox.x1
            and other.bbox.y1 >= img.bbox.y1
            for other in photos
        )
    ]


def detect_column_zones(
    content_blocks: list[TextBlock], image_blocks: list[ImageBlock], page_width: float, tolerance: float | None = None
) -> tuple[list[float], list[tuple[float, float]]]:
    """Splits off zones below a row of side-by-side photos (a photo strip),
    whose narrower local columns would otherwise fragment the page's grid.
    Anchored on images, not block widths: PyMuPDF sometimes fuses
    neighbouring captions into one wide block.

    Returns (main_boundaries, zone_bounds), the boundaries recomputed without
    the zoned blocks. A zone is (y0, x0), its top-left corner; it runs to the
    page's bottom-right (a strip's text has no clean lower edge), with x0
    snapped to the main grid. Headlines are never zoned."""
    main_boundaries = compute_column_boundaries(content_blocks, page_width, tolerance)
    if len(main_boundaries) <= 2:
        return main_boundaries, []

    zone_bounds: list[tuple[float, float]] = []
    zoned_ids: set[int] = set()
    rows = _cluster_image_rows(_photo_images(image_blocks, page_width), scaled(IMAGE_ROW_Y0_TOLERANCE, page_width))
    for row in rows:
        if len(row) < MIN_IMAGES_FOR_ROW:
            continue
        leftmost = min(row, key=lambda img: img.bbox.x0)
        zone_y0 = min(img.bbox.y0 for img in row) - scaled(ZONE_Y_PADDING, page_width)
        # The boundary left of the leftmost image, not nearest_column: an
        # image straddling a (not yet corrected) divider can snap to the
        # column on its right and cut off content left of it.
        zone_x0 = max((b for b in main_boundaries[:-1] if b <= leftmost.bbox.x0), default=main_boundaries[0])

        zone_blocks = [
            b
            for b in content_blocks
            if id(b) not in zoned_ids and not b.looks_like_headline and b.bbox.y0 >= zone_y0 and b.bbox.x0 >= zone_x0
        ]
        if len(zone_blocks) < MIN_ZONE_BLOCKS:
            continue
        if len(compute_column_boundaries(zone_blocks, page_width, tolerance)) <= 2:
            continue  # still just one column locally -- not a real sub-grid
        zone_bounds.append((zone_y0, zone_x0))
        zoned_ids.update(id(b) for b in zone_blocks)

    if not zoned_ids:
        return main_boundaries, []

    remaining = [b for b in content_blocks if id(b) not in zoned_ids]
    main_boundaries = compute_column_boundaries(remaining, page_width, tolerance)
    return main_boundaries, zone_bounds
