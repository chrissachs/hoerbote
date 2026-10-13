"""Golden regression tests on a scanned historic issue (text from ALTO).
The inputs live in the repo: the Berliner Tageblatt issue carries a Public
Domain Mark (Staatsbibliothek zu Berlin), so its per-page ALTO and layout
cache sit in tests/fixtures/<run_id>/ next to the expected article
texts in expected/.

Pages and cases were picked from the ones a bold-detection fix changed
(see alto_io) and checked by hand: each article starts with its own
headline and ends with its own last paragraph.

To (re)generate the snapshots -- only after confirming the current output
BY HAND (e.g. in the run's debug view, see debug_view.py):
    uv run --project jobs/2_articles python jobs/2_articles/tests/test_golden_alto.py
"""

from functools import cache
from pathlib import Path

import pytest

from alto_io import extract_alto_rules, extract_alto_text_blocks
from articles import Article, extract_articles_from_labeled_blocks
from layout_boundaries import apply_layout_labels, load_regions_in_points

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "berliner-tageblatt-morning-1926-10-08"
EXPECTED_DIR = FIXTURE_DIR / "expected"
PAGE_WIDTH_PT = 576.0  # every page of this issue's PDF

# (page_num, marker, expected_file) -- marker is a substring unique to
# exactly one article's text on that page (OCR spelling as-is).
GOLDEN_CASES = [
    (1, "Masseuverhastungen rn Peking", "page1_peking.txt"),
    (1, "Ler griechische UEaEjüompf", "page1_griechischer_wahlkampf.txt"),
    (7, "Ein Tag -er Anfälle", "page7_unfaelle.txt"),
    (7, "Flugzeugabsturz in Staaken", "page7_flugzeugabsturz.txt"),
    (18, "Velzwarenembrnch", "page18_pelzwareneinbruch.txt"),
    (18, "Werden die Hauenummern beleuchtet", "page18_hausnummern.txt"),
]


@cache
def extract_page_articles(page_num: int) -> list[Article]:
    """The ALTO branch of run.process_pdf for one page, minus the PDF
    (only its page width is needed) and the debug output."""
    regions = load_regions_in_points(FIXTURE_DIR / f"page{page_num}.layout.json")
    alto_path = FIXTURE_DIR / f"page{page_num}.xml"
    text_blocks = extract_alto_text_blocks(alto_path, PAGE_WIDTH_PT, regions)
    apply_layout_labels(regions, text_blocks, [], PAGE_WIDTH_PT)
    _, articles = extract_articles_from_labeled_blocks(
        text_blocks, [], PAGE_WIDTH_PT, extract_alto_rules(alto_path, PAGE_WIDTH_PT)
    )
    return articles


def find_one(articles: list[Article], marker: str) -> Article:
    matches = [a for a in articles if marker in a.text]
    assert len(matches) == 1, (
        f"expected exactly one article containing {marker!r}, found {len(matches)}: "
        f"{[a.headline_guess for a in matches]}"
    )
    return matches[0]


@pytest.mark.parametrize("page_num,marker,expected_file", GOLDEN_CASES, ids=[Path(f).stem for _, _, f in GOLDEN_CASES])
def test_golden_alto_article(page_num: int, marker: str, expected_file: str) -> None:
    article = find_one(extract_page_articles(page_num), marker)
    assert article.text == (EXPECTED_DIR / expected_file).read_text(encoding="utf-8")


if __name__ == "__main__":
    EXPECTED_DIR.mkdir(exist_ok=True)
    for page_num, marker, expected_file in GOLDEN_CASES:
        article = find_one(extract_page_articles(page_num), marker)
        (EXPECTED_DIR / expected_file).write_text(article.text, encoding="utf-8")
        print(f"wrote {expected_file} ({len(article.text)} chars) -- {article.headline_guess!r}")
