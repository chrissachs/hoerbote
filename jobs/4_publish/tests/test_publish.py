"""Unit tests for the publish job's reshaping -- synthetic inputs, no run data."""

from models import Article, BBox
from narration import ArticleCategory, NarratedArticle, PageSummary, PageSummarySentence
from publish import build_page, to_page_fraction


def _article(idx: int, bbox: tuple[float, float, float, float]) -> Article:
    return Article(
        article_idx=idx, headline_guess=f"guess {idx}", text="...", bbox_union=BBox.from_tuple(bbox), columns=[0]
    )


def _narration(sentence_idxs: list[int]) -> PageSummary:
    return PageSummary(
        page=1,
        tone="colloquial",
        articles=[
            NarratedArticle(article_idx=i, headline=f"clean {i}", category=ArticleCategory.SPORTS)
            for i in sorted(set(sentence_idxs))
        ],
        sentences=[PageSummarySentence(sentence=f"s{n}", article_idx=i) for n, i in enumerate(sentence_idxs)],
    )


def test_bbox_becomes_clamped_page_fraction():
    frac = to_page_fraction(BBox.from_tuple((-5, 50, 50, 210)), page_width=100, page_height=200)
    assert (frac.x0, frac.y0, frac.x1, frac.y1) == (0.0, 0.25, 0.5, 1.0)


def test_consecutive_sentences_group_into_segments_and_returning_story_gets_own_segment():
    articles = [_article(0, (0, 0, 10, 10)), _article(1, (0, 0, 10, 10)), _article(2, (0, 0, 10, 10))]
    page = build_page(1, articles, _narration([0, 0, 1, 0]), 100, 100, "img.png")

    assert [(s.index, s.article_idx, s.sentences) for s in page.segments] == [
        (0, 0, ["s0", "s1"]),
        (1, 1, ["s2"]),
        (2, 0, ["s3"]),
    ]
    by_idx = {a.article_idx: a for a in page.articles}
    assert by_idx[0].segments == [0, 2]
    assert by_idx[1].segments == [1]
    # Not narrated: no segments, raw headline, no category.
    assert by_idx[2].segments == []
    assert by_idx[2].headline == "guess 2"
    assert by_idx[2].category is None
    assert by_idx[0].headline == "clean 0"


def test_page_without_narration_still_published():
    page = build_page(3, [_article(0, (0, 0, 10, 10))], None, 100, 200, "img.png")
    assert page.segments == []
    assert page.tone is None
    assert page.aspect_ratio == 0.5
    assert page.articles[0].segments == []
