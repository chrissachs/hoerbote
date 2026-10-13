"""The articles job's records, shared because its report.json (PageReport)
is what the narration and publish jobs read."""

from pydantic import BaseModel, Field, model_serializer, model_validator


class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def from_tuple(cls, t: tuple[float, float, float, float]) -> BBox:
        return cls(x0=t[0], y0=t[1], x1=t[2], y1=t[3])

    @model_validator(mode="before")
    @classmethod
    def _parse_compact(cls, data):
        # Accept the same compact [x0, y0, x1, y1] shape _serialize emits,
        # so a BBox round-trips through model_validate_json without callers
        # having to go through from_tuple by hand.
        if isinstance(data, (list, tuple)):
            return {"x0": data[0], "y0": data[1], "x1": data[2], "y1": data[3]}
        return data

    @model_serializer
    def _serialize(self) -> list[float]:
        # Keep the compact [x0, y0, x1, y1] shape in JSON output.
        return [self.x0, self.y0, self.x1, self.y1]


class ImageBlock(BaseModel):
    bbox: BBox
    xref: int


class TextBlock(BaseModel):
    bbox: BBox
    text: str
    max_font_size: float
    # None when the text source doesn't record it (e.g. ALTO without
    # font styles) -- callers must treat that as "unknown", not
    # "homogeneous".
    min_font_size: float | None = None
    max_font_char_count: int | None = None
    is_bold: bool
    is_italic: bool
    word_count: int

    # Filled in by the articles job's heuristics; not known at
    # extraction time.
    excluded_short: bool = False
    looks_like_headline: bool = False
    median_body_size: float = 0.0
    is_caption: bool = False
    caption_image: ImageBlock | None = None
    columns: list[int] = Field(default_factory=list)
    article_idx: int | None = None
    # True for a block that should never be placed in any article at all --
    # e.g. layout-model-detected page furniture (PageHeader/PageFooter) or noise
    # over an ad/image (Picture/Figure) -- as opposed to excluded_short,
    # which only keeps a block from anchoring the column grid while still
    # letting it flow into whatever article ends up nearby.
    excluded_from_flow: bool = False


class Article(BaseModel):
    article_idx: int
    headline_guess: str
    text: str
    bbox_union: BBox
    columns: list[int]


class PageImage(BaseModel):
    """A picture on the page and the article it belongs to -- its position
    only, the image itself isn't extracted."""

    bbox: BBox
    article_idx: int | None = None


class PageReport(BaseModel):
    page: int
    articles: list[Article]
    images: list[PageImage]
