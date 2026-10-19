"""Articles job: groups each page's text into articles, guided by the
layout job's regions -> 02_articles/report.json, plus debug.json for the
debug view (debug_view.py).

The text comes from the run's 00_source.json `text_source`: "alto" reads
per-page OCR (alto_io), "pdf" the PDF's embedded text (pdf_io). Never runs the
layout model: a missing layout cache fails the step."""

import json
import logging
from pathlib import Path

import pymupdf

from alto_io import extract_alto_rules, extract_alto_text_blocks
from articles import assign_image_to_article
from debug_view import DEBUG_RENDER_DPI, DebugViewBuilder
from layout_boundaries import extract_articles_via_layout_model, load_regions_in_points
from models import PageImage, PageReport
from pdf_io import extract_page_elements
from pipeline_run import run_dir, run_id_from_args, step
from source_info import PAGE_TEXT_DIR_NAME, SOURCE_INFO_FILE_NAME, SourceInfo

STEP_NAME = "articles"

log = logging.getLogger(__name__)


def _check_layout_cache_complete(source_pdf: Path, layout_dir: Path) -> None:
    doc = pymupdf.open(str(source_pdf))
    missing = [n for n in range(1, len(doc) + 1) if not (layout_dir / f"page{n}.layout.json").exists()]
    if missing:
        raise FileNotFoundError(
            f"{layout_dir} is missing the layout-detection cache for page(s) {missing} -- "
            f"the layout job must complete for this run before "
            f"the articles job can run."
        )


def process_pdf(path: Path, out_dir: Path, layout_dir: Path, alto_dir: Path | None) -> None:
    """Groups every page of `path` into articles: report.json and the debug
    view's data in `out_dir`. `layout_dir` holds stage
    A's pageN.layout.json cache. `alto_dir` switches the text source to
    `<alto_dir>/pageN.xml` (OCR of a scanned issue, see alto_io) instead of
    the PDF's embedded text; scans have no embedded images."""
    doc = pymupdf.open(str(path))
    out_dir.mkdir(exist_ok=True)
    debug_builder = DebugViewBuilder(scale=DEBUG_RENDER_DPI / 72)

    report: list[PageReport] = []
    for page_num, page in enumerate(doc, start=1):
        if alto_dir:
            regions = load_regions_in_points(layout_dir / f"page{page_num}.layout.json")
            alto_path = alto_dir / f"page{page_num}.xml"
            text_blocks = extract_alto_text_blocks(alto_path, page.rect.width, regions)
            rules = extract_alto_rules(alto_path, page.rect.width)
            image_blocks = []
        else:
            text_blocks, image_blocks = extract_page_elements(page)
            rules = []
        boundaries, page_articles = extract_articles_via_layout_model(
            text_blocks, image_blocks, page, page_num, page.rect.width, cache_dir=layout_dir, rules=rules
        )

        images = [
            PageImage(bbox=b.bbox, article_idx=assign_image_to_article(b.bbox, page_articles)) for b in image_blocks
        ]
        report.append(PageReport(page=page_num, articles=page_articles, images=images))
        debug_builder.add_page(page_num, page, text_blocks, boundaries, page_articles, images)

    with open(out_dir / "report.json", "w", encoding="utf-8") as f:
        json.dump([r.model_dump(mode="json") for r in report], f, ensure_ascii=False, indent=2)

    log.info("Done. %d page(s) processed. See %s/report.json", len(report), out_dir)

    debug_builder.write(out_dir)


def run(run_id: str) -> None:
    rd = run_dir(run_id)
    source_pdf = rd / "00_source.pdf"
    layout_dir = rd / "01_layout"
    out_dir = rd / "02_articles"

    if not source_pdf.exists():
        raise FileNotFoundError(f"missing {source_pdf}")

    info = SourceInfo.model_validate_json((rd / SOURCE_INFO_FILE_NAME).read_text())
    alto_dir = rd / PAGE_TEXT_DIR_NAME if info.text_source == "alto" else None

    with step(run_id, STEP_NAME, input_path=str(layout_dir)) as s:
        _check_layout_cache_complete(source_pdf, layout_dir)
        log.info("Text source: %s", f"ALTO in {alto_dir}" if alto_dir else "PDF text")
        process_pdf(source_pdf, out_dir, layout_dir, alto_dir)
        s.finish(str(out_dir))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(run_id_from_args())
