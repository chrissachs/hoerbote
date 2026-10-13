"""A synthetic published issue under a temporary DATA_ROOT -- no real
run data."""

import datetime

import pytest

from models import BBox
from published import PublishedArticle, PublishedIssue, PublishedPage, PublishedPageEntry, PublishedSegment
from source_info import SOURCE_INFO_FILE_NAME, Rights, SourceInfo

RUN_ID = "paper-daily-2026-10-02"


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """Page 1 with two segments, page 2 with none."""
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    rd = tmp_path / "issues" / RUN_ID
    (rd / "04_published").mkdir(parents=True)
    article = PublishedArticle(
        article_idx=0, headline="h", category=None, bbox=BBox(x0=0, y0=0, x1=1, y1=1), segments=[0, 1]
    )
    segments = [PublishedSegment(index=i, article_idx=0, sentences=[f"s{i}"]) for i in range(2)]
    for n, segs in [(1, segments), (2, [])]:
        page = PublishedPage(
            page=n, image="x.jpg", aspect_ratio=0.7, tone=None, articles=[article] if segs else [], segments=segs
        )
        (rd / "04_published" / f"page{n}.json").write_text(page.model_dump_json())
    info = SourceInfo(
        paper="paper",
        paper_title="Paper",
        edition="daily",
        date=datetime.date(2026, 10, 2),
        provider="url",
        provider_item_id="i",
        landing_url=None,
        text_source="pdf",
        rights=Rights(statement_url=None, label=None, holder=None, open=False),
        attribution="",
        pages=[],
    )
    (rd / SOURCE_INFO_FILE_NAME).write_text(info.model_dump_json())
    issue = PublishedIssue(
        run_id=RUN_ID,
        **info.model_dump(include={"paper", "paper_title", "edition", "date", "attribution"}),
        pages=[
            PublishedPageEntry(page=1, aspect_ratio=0.7, segment_count=2),
            PublishedPageEntry(page=2, aspect_ratio=0.7, segment_count=0),
        ],
    )
    (rd / "04_published" / "issue.json").write_text(issue.model_dump_json())
    return rd
