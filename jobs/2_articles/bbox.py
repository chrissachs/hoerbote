"""Bounding-box math and page units for the grouping heuristics."""

from models import BBox

# Absolute point values in the heuristics (distances, and the few absolute
# font-size steps) were tuned on modern newspaper pages 992.12 pt wide and
# are stated at that width: scaled() converts one to the page at hand, so a
# smaller page -- e.g. a scanned 1926 issue at 576 pt, where text is
# proportionally smaller too -- gets proportionally smaller gaps. Fractions
# and multiples of the body font size need no scaling.
REFERENCE_PAGE_WIDTH_PT = 992.12


def scaled(points: float, page_width: float) -> float:
    return points * page_width / REFERENCE_PAGE_WIDTH_PT


def x_overlap_frac(bbox_a: BBox, bbox_b: BBox) -> float:
    """Overlap as a fraction of the narrower block's width. 1.0 = one fully
    contains the other's x-range; 0 = no horizontal overlap."""
    overlap = min(bbox_a.x1, bbox_b.x1) - max(bbox_a.x0, bbox_b.x0)
    if overlap <= 0:
        return 0.0
    return overlap / min(bbox_a.x1 - bbox_a.x0, bbox_b.x1 - bbox_b.x0)


def compute_column_overlaps(bbox: BBox, boundaries: list[float]) -> dict[int, float]:
    """Horizontal overlap fraction of `bbox` against every column (only
    columns with positive overlap are included)."""
    n = len(boundaries) - 1
    fracs = {}
    for i in range(n):
        c0, c1 = boundaries[i], boundaries[i + 1]
        overlap = min(bbox.x1, c1) - max(bbox.x0, c0)
        if overlap > 0:
            fracs[i] = overlap / (c1 - c0)
    return fracs


def nearest_column(bbox: BBox, boundaries: list[float]) -> int:
    """Column with the largest horizontal overlap against `bbox`."""
    n = len(boundaries) - 1
    best_i, best_overlap = 0, None
    for i in range(n):
        c0, c1 = boundaries[i], boundaries[i + 1]
        overlap = min(bbox.x1, c1) - max(bbox.x0, c0)
        if best_overlap is None or overlap > best_overlap:
            best_overlap, best_i = overlap, i
    return best_i


def union_bbox(bboxes: list[BBox]) -> BBox:
    return BBox(
        x0=min(b.x0 for b in bboxes),
        y0=min(b.y0 for b in bboxes),
        x1=max(b.x1 for b in bboxes),
        y1=max(b.y1 for b in bboxes),
    )


def bbox_overlap_area(a: BBox, b: BBox) -> float:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    if x1 <= x0 or y1 <= y0:
        return 0
    return (x1 - x0) * (y1 - y0)


def scale_bbox(bbox: BBox, scale: float) -> list[float]:
    return [
        round(bbox.x0 * scale, 1),
        round(bbox.y0 * scale, 1),
        round(bbox.x1 * scale, 1),
        round(bbox.y1 * scale, 1),
    ]
