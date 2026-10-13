"""run.py end to end, for both text sources: a synthetic born-digital PDF
(embedded text, hand-made layout cache) and the committed public-domain
ALTO fixture. Checks what lands in 02_articles/ and status.json."""

import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Literal

import pymupdf
import pytest
from test_golden_alto import EXPECTED_DIR, FIXTURE_DIR, GOLDEN_CASES

import run
from layout_cache import LayoutRegion, save_region_cache
from models import BBox, PageReport
from source_info import Rights, SourceInfo, SourcePage

RUN_ID = "paper-morning-1926-10-08"

# Synthetic page: the reference page width, three columns, a masthead line,
# and three articles. Body words carry a marker (<word><column><paragraph>w<n>)
# so the tests can check which article got which paragraphs, in which order.
PAGE_W, PAGE_H = 992.12, 1400
COL_W, COL_GAP, MARGIN = 290, 25, 40
ARTICLES = [
    # (headline, columns, top, marker word, paragraphs per column)
    ("Neue Brücke für die Stadt: Rat beschließt Bau im Frühjahr", [0, 1], 120, "bruecke", 3),
    ("Konzert im Park", [2], 120, "konzert", 4),
    ("Wetter bleibt mild bis weit in den späten Oktober hinein", [0, 1], 640, "wetter", 3),
]


def _col_x(col: int) -> float:
    return MARGIN + col * (COL_W + COL_GAP)


def _write_synthetic_issue(rd: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    regions: list[LayoutRegion] = []

    def put(label: str, rect: pymupdf.Rect, text: str, fontsize: float, font: str) -> None:
        # insert_textbox returns the unused height (negative: text didn't fit
        # and nothing was written); the region gets the text's real extent.
        unused = page.insert_textbox(rect, text, fontsize=fontsize, fontname=font)
        assert unused >= 0, f"text doesn't fit: {text[:30]!r}"
        rect.y1 -= unused
        regions.append(
            LayoutRegion(position=len(regions), label=label, bbox=BBox(x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1))
        )

    put(
        "PageHeader",
        pymupdf.Rect(MARGIN, 30, PAGE_W - MARGIN, 60),
        "Stadtanzeiger  ·  Montag, 8. Oktober 1926  ·  Seite 1",
        10,
        "helv",
    )
    for headline, cols, top, word, paras in ARTICLES:
        put(
            "SectionHeader",
            pymupdf.Rect(_col_x(cols[0]), top, _col_x(cols[-1]) + COL_W, top + 32),
            headline,
            18,
            "hebo",
        )
        for col in cols:
            y = top + 40
            for p in range(paras):
                text = " ".join(f"{word}{col}{p}w{i}" if i % 7 == 0 else "und die Stadt" for i in range(45))
                rect = pymupdf.Rect(_col_x(col), y, _col_x(col) + COL_W, y + 400)
                put("Text", rect, text, 9.5, "helv")
                y = rect.y1 + 6
    doc.save(rd / "00_source.pdf")
    _write_source_info(rd, "pdf", [SourcePage(page=1)])
    (rd / "01_layout").mkdir()
    # dpi=72: region pixels are PDF points.
    save_region_cache(rd / "01_layout" / "page1.layout.json", regions, source_pdf="00_source.pdf", dpi=72)


def _write_alto_issue(rd: Path, fixture_pages: list[int]) -> None:
    """The committed fixture pages as pages 1..n of a run. Only the PDF's
    page size matters on the ALTO path, so its pages are blank."""
    doc = pymupdf.open()
    (rd / "01_layout").mkdir()
    (rd / "00_page_text").mkdir()
    for n, fixture_page in enumerate(fixture_pages, start=1):
        doc.new_page(width=576, height=817)
        shutil.copy(FIXTURE_DIR / f"page{fixture_page}.layout.json", rd / "01_layout" / f"page{n}.layout.json")
        shutil.copy(FIXTURE_DIR / f"page{fixture_page}.xml", rd / "00_page_text" / f"page{n}.xml")
    doc.save(rd / "00_source.pdf")
    _write_source_info(
        rd,
        "alto",
        [SourcePage(page=n, text_file=f"00_page_text/page{n}.xml") for n in range(1, len(fixture_pages) + 1)],
    )


def _write_source_info(rd: Path, text_source: Literal["pdf", "alto"], pages: list[SourcePage]) -> None:
    info = SourceInfo(
        paper="paper",
        paper_title="Paper",
        edition="morning",
        date=datetime.date(1926, 10, 8),
        provider="ddb",
        provider_item_id="ITEM",
        landing_url=None,
        text_source=text_source,
        rights=Rights(statement_url=None, label=None, holder=None, open=False),
        attribution="",
        pages=pages,
    )
    (rd / "00_source.json").write_text(info.model_dump_json())


@pytest.fixture
def rd(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    rd = tmp_path / "issues" / RUN_ID
    rd.mkdir(parents=True)
    return rd


def _report(rd: Path) -> list[PageReport]:
    return [PageReport.model_validate(p) for p in json.loads((rd / "02_articles" / "report.json").read_text())]


def _status(rd: Path) -> dict:
    return json.loads((rd / "status.json").read_text())


def test_pdf_text_groups_articles(rd):
    _write_synthetic_issue(rd)
    run.run(RUN_ID)

    (page,) = _report(rd)
    by_headline = {a.headline_guess: a for a in page.articles}
    assert sorted(by_headline) == sorted(h for h, *_ in ARTICLES)
    for headline, cols, _, word, paras in ARTICLES:
        article = by_headline[headline]
        assert article.columns == cols
        # Every paragraph of the article, column by column, and nothing else.
        markers = re.findall(r"\b([a-z]+\d\d)w0\b", article.text)
        assert markers == [f"{word}{c}{p}" for c in cols for p in range(paras)]
    assert "Stadtanzeiger" not in " ".join(a.text for a in page.articles)
    assert (rd / "02_articles" / "debug.json").exists()
    assert _status(rd)["status"] == "succeeded"


def test_alto_text_matches_golden_articles(rd):
    fixture_pages = sorted({p for p, _, _ in GOLDEN_CASES})
    _write_alto_issue(rd, fixture_pages)
    run.run(RUN_ID)

    texts = {page.page: [a.text for a in page.articles] for page in _report(rd)}
    for fixture_page, _, expected_file in GOLDEN_CASES:
        expected = (EXPECTED_DIR / expected_file).read_text(encoding="utf-8")
        assert expected in texts[fixture_pages.index(fixture_page) + 1], expected_file
    assert _status(rd)["status"] == "succeeded"


def test_missing_layout_cache_fails_the_step(rd):
    _write_synthetic_issue(rd)
    (rd / "01_layout" / "page1.layout.json").unlink()
    with pytest.raises(FileNotFoundError, match=r"layout-detection cache for page\(s\) \[1\]"):
        run.run(RUN_ID)
    assert _status(rd)["status"] == "failed"
    assert not (rd / "02_articles" / "report.json").exists()
