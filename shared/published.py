"""The publish -> backend contract: 04_published/issue.json plus one
page{N}.json per page, pre-computed so neither the backend nor the
frontend derives anything. No voices here: the audio job picks them, which
keeps TTS config out of the narration and publish jobs."""

import datetime

from pydantic import BaseModel

from models import BBox
from narration import ArticleCategory


class PublishedSegment(BaseModel):
    """A run of consecutive narration sentences about one article: where
    the voice switches, and the unit audio is rendered and cached in."""

    # Position in play order; the key of the backend's audio route.
    index: int
    article_idx: int
    sentences: list[str]


class PublishedArticle(BaseModel):
    article_idx: int
    # The narration's cleaned headline when narrated, else the articles
    # job's raw headline_guess (noisier: can be a kicker or a section label).
    headline: str
    # None when not narrated: only narrated articles get a category.
    category: ArticleCategory | None
    # Fractions of the page (0-1), so it fits a page image of any size:
    # [x0, y0, x1, y1] in JSON.
    bbox: BBox
    # PublishedSegment.index values about this article, in play order;
    # empty = not narrated (the frontend knows what's clickable). Usually
    # one, more when the narration returns to a story later.
    segments: list[int]


class PublishedPage(BaseModel):
    page: int
    # Page image and its thumbnail, relative to the run directory -- the
    # backend serves them, the frontend never sees these paths.
    image: str
    thumbnail: str | None = None
    # Page width / height, so the frontend can lay out the page before
    # the image has loaded.
    aspect_ratio: float
    # The narration's tone (None if the page has no narration).
    tone: str | None
    articles: list[PublishedArticle]
    segments: list[PublishedSegment]


class PublishedPageEntry(BaseModel):
    """One page's line in the issue index -- enough for page navigation
    without loading every page{N}.json."""

    page: int
    aspect_ratio: float
    segment_count: int


class PublishedIssue(BaseModel):
    run_id: str
    # From the run's 00_source.json.
    paper: str
    paper_title: str
    edition: str
    date: datetime.date
    # Credit line for the content (rights holder, licence).
    attribution: str
    pages: list[PublishedPageEntry]
