"""Synthetic published issues under a temporary DATA_ROOT -- no real run
data. The restricted run has a page; the Tageblatt run is
the openly licensed one."""

import datetime

import pytest

from models import BBox
from published import PublishedArticle, PublishedIssue, PublishedPage, PublishedPageEntry, PublishedSegment
from source_info import SOURCE_INFO_FILE_NAME, Rights, SourceInfo

OPEN_RUN_ID = "berliner-tageblatt-morning-1926-10-08"
RESTRICTED_RUN_ID = "restricted-daily-2026-10-02"
NOT_FETCHED_RUN_ID = "2026-09-02"


def source_info(open_rights: bool) -> str:
    return SourceInfo(
        paper="p",
        paper_title="P",
        edition="morning",
        date=datetime.date(1926, 10, 8),
        provider="x",
        provider_item_id="x",
        landing_url=None,
        text_source="pdf",
        rights=Rights(statement_url=None, label=None, holder=None, open=open_rights),
        attribution="a",
        pages=[],
    ).model_dump_json()


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    run = tmp_path / "issues" / RESTRICTED_RUN_ID
    (run / "04_published").mkdir(parents=True)
    (run / "01_layout").mkdir()
    (run / "01_layout" / "page1.png").write_bytes(b"\x89PNG fake")
    (run / "04_published" / "page1.thumb.jpg").write_bytes(b"\xff\xd8 fake")
    page = PublishedPage(
        page=1,
        image="01_layout/page1.png",
        thumbnail="04_published/page1.thumb.jpg",
        aspect_ratio=0.6863,
        tone="colloquial",
        articles=[
            PublishedArticle(
                article_idx=0, headline="h", category=None, bbox=BBox(x0=0, y0=0, x1=0.5, y1=0.5), segments=[0]
            )
        ],
        segments=[PublishedSegment(index=0, article_idx=0, sentences=["s"])],
    )
    (run / "04_published" / "page1.json").write_text(page.model_dump_json())
    issue = PublishedIssue(
        run_id=RESTRICTED_RUN_ID,
        paper="restricted",
        paper_title="Restricted Daily",
        edition="daily",
        date=datetime.date(2026, 10, 2),
        attribution="not for the list",
        pages=[PublishedPageEntry(page=1, aspect_ratio=0.6863, segment_count=1)],
    )
    (run / "04_published" / "issue.json").write_text(issue.model_dump_json())
    # An older issue (sorted by date, not the paper name); a published
    # issue fetch didn't make (no 00_source.json) and a run that hasn't been
    # published -- neither listed.
    for other_id, date in [(OPEN_RUN_ID, datetime.date(1926, 10, 8)), (NOT_FETCHED_RUN_ID, datetime.date(2026, 9, 2))]:
        other = tmp_path / "issues" / other_id / "04_published"
        other.mkdir(parents=True)
        other_issue = issue.model_copy(update={"run_id": other_id, "date": date, "pages": []})
        (other / "issue.json").write_text(other_issue.model_dump_json())
    (tmp_path / "issues" / "restricted-daily-2026-10-03").mkdir()
    (run / SOURCE_INFO_FILE_NAME).write_text(source_info(open_rights=False))
    (tmp_path / "issues" / OPEN_RUN_ID / SOURCE_INFO_FILE_NAME).write_text(source_info(open_rights=True))
    return tmp_path
