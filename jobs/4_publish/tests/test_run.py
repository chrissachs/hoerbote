"""run.py end to end on a synthetic run dir: report.json + narration +
page images -> 04_published/ (issue index and one file per page)."""

import datetime
import json

import pymupdf
import pytest
from PIL import Image
from test_publish import _article, _narration

import run
from published import PublishedIssue, PublishedPage
from source_info import Rights, SourceInfo

RUN_ID = "paper-morning-1926-10-08"


@pytest.fixture
def rd(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    rd = tmp_path / "issues" / RUN_ID
    (rd / "02_articles").mkdir(parents=True)
    (rd / "03_rewritten").mkdir()
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=100, height=200)
    doc.save(rd / "00_source.pdf")
    pages = [
        {"page": n, "articles": [_article(0, (0, 0, 50, 100)).model_dump(mode="json")], "images": []} for n in (1, 2)
    ]
    (rd / "02_articles" / "report.json").write_text(json.dumps(pages))
    # Only page 1 has narration (page 2: e.g. all ads).
    (rd / "03_rewritten" / "page1.narration.json").write_text(_narration([0, 0]).model_dump_json())
    info = SourceInfo(
        paper="paper",
        paper_title="Das Blatt",
        edition="morning",
        date=datetime.date(1926, 10, 8),
        provider="ddb",
        provider_item_id="i",
        landing_url=None,
        text_source="alto",
        rights=Rights(statement_url=None, label=None, holder=None, open=True),
        attribution="Das Blatt, 08.10.1926",
        pages=[],
    )
    (rd / "00_source.json").write_text(info.model_dump_json())
    return rd


def test_issue_published(rd):
    stale = rd / "04_published" / "page9.json"
    stale.parent.mkdir()
    stale.write_text("{}")
    run.run(RUN_ID)

    out = rd / "04_published"
    issue = PublishedIssue.model_validate_json((out / "issue.json").read_text())
    assert [(e.page, e.aspect_ratio, e.segment_count) for e in issue.pages] == [(1, 0.5, 1), (2, 0.5, 0)]
    page1 = PublishedPage.model_validate_json((out / "page1.json").read_text())
    assert (page1.image, page1.thumbnail) == ("04_published/page1.webp", "04_published/page1.thumb.webp")
    assert page1.segments[0].sentences == ["s0", "s1"]
    widths = (Image.open(rd / page1.image).width, Image.open(rd / page1.thumbnail).width)
    assert widths == (run.IMAGE_WIDTH_PX, run.THUMBNAIL_WIDTH_PX)
    assert (issue.paper, issue.paper_title, issue.edition, issue.date, issue.attribution) == (
        "paper",
        "Das Blatt",
        "morning",
        datetime.date(1926, 10, 8),
        "Das Blatt, 08.10.1926",
    )
    assert not stale.exists()
    assert json.loads((rd / "status.json").read_text())["status"] == "succeeded"


def test_failed_publish_keeps_the_previous_version(rd):
    run.run(RUN_ID)
    before = (rd / "04_published" / "issue.json").read_text()
    # Narration about an article the report doesn't have: the job fails.
    (rd / "03_rewritten" / "page1.narration.json").write_text(_narration([7]).model_dump_json())
    with pytest.raises(ValueError, match="article_idx \\[7\\]"):
        run.run(RUN_ID)
    assert (rd / "04_published" / "issue.json").read_text() == before
