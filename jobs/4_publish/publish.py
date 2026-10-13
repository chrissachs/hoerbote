"""Builds a page's frontend-ready JSON (shared/published.py) from its
articles and narration."""

from models import Article, BBox
from narration import PageSummary
from published import PublishedArticle, PublishedPage, PublishedSegment


def to_page_fraction(bbox: BBox, page_width: float, page_height: float) -> BBox:
    """PDF-point bbox -> fractions of the page, clamped to 0-1 (a block can
    poke slightly past the page edge). Rounded to 4 decimals -- still
    sub-pixel on any realistic screen, and keeps the JSON readable."""

    def clamp(v: float) -> float:
        return round(min(max(v, 0.0), 1.0), 4)

    return BBox(
        x0=clamp(bbox.x0 / page_width),
        y0=clamp(bbox.y0 / page_height),
        x1=clamp(bbox.x1 / page_width),
        y1=clamp(bbox.y1 / page_height),
    )


def build_segments(narration: PageSummary) -> list[PublishedSegment]:
    """Groups consecutive sentences about the same article into one
    segment. An article the overview returns to later gets a second,
    separate segment -- play order is the narration's own order."""
    segments: list[PublishedSegment] = []
    for s in narration.sentences:
        if segments and segments[-1].article_idx == s.article_idx:
            segments[-1].sentences.append(s.sentence)
        else:
            segments.append(PublishedSegment(index=len(segments), article_idx=s.article_idx, sentences=[s.sentence]))
    return segments


def build_page(
    page_num: int,
    articles: list[Article],
    narration: PageSummary | None,
    page_width: float,
    page_height: float,
    image: str,
) -> PublishedPage:
    segments = build_segments(narration) if narration else []
    narrated = {a.article_idx: a for a in narration.articles} if narration else {}

    published_articles = []
    for article in articles:
        n = narrated.get(article.article_idx)
        published_articles.append(
            PublishedArticle(
                article_idx=article.article_idx,
                headline=n.headline if n else article.headline_guess,
                category=n.category if n else None,
                bbox=to_page_fraction(article.bbox_union, page_width, page_height),
                segments=[s.index for s in segments if s.article_idx == article.article_idx],
            )
        )

    known = {a.article_idx for a in articles}
    unknown = sorted({s.article_idx for s in segments} - known)
    if unknown:
        raise ValueError(
            f"page {page_num}: narration refers to article_idx {unknown}, which the articles job's "
            f"report.json doesn't have -- it was likely re-run after the narration job; re-run that."
        )

    return PublishedPage(
        page=page_num,
        image=image,
        aspect_ratio=round(page_width / page_height, 4),
        tone=narration.tone if narration else None,
        articles=published_articles,
        segments=segments,
    )
