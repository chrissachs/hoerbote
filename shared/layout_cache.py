"""The layout -> articles contract: one 01_layout/page{N}.layout.json per
page, the regions the layout model found."""

from pathlib import Path

from pydantic import BaseModel

from models import BBox

# The DPI pages are rendered at for layout detection. A lower DPI silently
# drops small text (kicker lines, subheads) with no error, just an empty
# gap. Only the producer's default: whatever DPI a cache was actually
# rendered at is recorded in it (see LayoutRegionCache), and readers take
# it from there rather than assuming this value.
LAYOUT_RENDER_DPI = 192


class LayoutRegion(BaseModel):
    position: int  # 0-indexed reading order
    label: str  # Text, SectionHeader, Picture, Caption, PageHeader, ...
    bbox: BBox


class LayoutRegionCache(BaseModel):
    """On-disk format of a pageN.layout.json cache. Records the source PDF
    and the DPI the page was rendered at when `regions` were detected
    (their bboxes are in that pixel space), so a reader converts them using
    the DPI they were actually rendered at rather than an assumed one --
    a mismatch would silently misalign regions against their matched text
    blocks."""

    source_pdf: str
    dpi: float
    regions: list[LayoutRegion]


def save_region_cache(path: Path, regions: list[LayoutRegion], source_pdf: str, dpi: float) -> None:
    path.write_text(LayoutRegionCache(source_pdf=source_pdf, dpi=dpi, regions=regions).model_dump_json(indent=2))


def load_region_cache(path: Path) -> LayoutRegionCache:
    """Load a pageN.layout.json cache. Returns the whole cache, not just its
    regions, so the caller converts bboxes using `cache.dpi` (see
    LayoutRegionCache)."""
    return LayoutRegionCache.model_validate_json(path.read_text())
