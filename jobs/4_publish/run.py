"""Publish job: articles + narration -> frontend-ready JSON in 04_published/
(issue.json and one page{N}.json per page), rewritten from scratch on every
run. Audio isn't made here: the audio job renders it on request."""

import json
import logging
import shutil
from pathlib import Path

import pymupdf
from PIL import Image

from models import PageReport
from narration import PageSummary
from pipeline_run import run_dir, run_id_from_args, step
from publish import build_page
from published import PublishedIssue, PublishedPageEntry
from source_info import SOURCE_INFO_FILE_NAME, SourceInfo

STEP_NAME = "publish"
OUT_DIR_NAME = "04_published"
# Page images rendered from the PDF: sharp enough to read old print when
# zoomed in (a 576 pt Tageblatt page -> ~300 DPI), ~0.8 MB as WebP.
IMAGE_WIDTH_PX = 2400
# Sharp in the frontend's page sidebar on high-density screens.
THUMBNAIL_WIDTH_PX = 360
# WebP at 70 looks the same as JPEG at 80 even zoomed in, at ~60% of the
# size (compared on an e-paper and a scanned page, 2026-10-13).
WEBP_QUALITY = 70

log = logging.getLogger(__name__)


def run(run_id: str) -> None:
    rd = run_dir(run_id)
    source_pdf = rd / "00_source.pdf"
    report_path = rd / "02_articles" / "report.json"
    narration_dir = rd / "03_rewritten"
    out_dir = rd / OUT_DIR_NAME

    for path, stage in [
        (source_pdf, "the run's source PDF"),
        (report_path, "the articles job"),
        (narration_dir, "the narration job"),
    ]:
        if not path.exists():
            raise FileNotFoundError(f"missing {path} -- {stage} must exist/complete for this run before publishing.")

    with step(run_id, STEP_NAME, input_path=str(narration_dir)) as s:
        pages = [PageReport.model_validate(p) for p in json.loads(report_path.read_text())]
        doc = pymupdf.open(str(source_pdf))

        # Built next to the old output and swapped in only when complete, so
        # a failed run leaves the previous version published.
        build_dir = rd / f"{OUT_DIR_NAME}.new"
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir()
        entries = [_publish_page(rd, page, doc, build_dir) for page in pages]
        info = SourceInfo.model_validate_json((rd / SOURCE_INFO_FILE_NAME).read_text())
        issue = PublishedIssue(
            run_id=run_id,
            paper=info.paper,
            paper_title=info.paper_title,
            edition=info.edition,
            date=info.date,
            attribution=info.attribution,
            pages=entries,
        )
        (build_dir / "issue.json").write_text(issue.model_dump_json(indent=2), encoding="utf-8")
        if out_dir.exists():
            shutil.rmtree(out_dir)
        build_dir.rename(out_dir)
        narrated = sum(1 for e in entries if e.segment_count)
        log.info(
            "Done. %d pages published (%d with narration, %d segments) to %s",
            len(entries),
            narrated,
            sum(e.segment_count for e in entries),
            out_dir,
        )

        s.finish(str(out_dir))


def _publish_page(rd: Path, page: PageReport, doc: pymupdf.Document, build_dir: Path) -> PublishedPageEntry:
    """Writes the page's JSON and images into `build_dir`; the paths in the
    JSON are where they'll be once it's swapped in as OUT_DIR_NAME."""
    narration_path = rd / "03_rewritten" / f"page{page.page}.narration.json"
    narration = (
        PageSummary.model_validate_json(narration_path.read_text(encoding="utf-8")) if narration_path.exists() else None
    )
    pdf_page = doc[page.page - 1]
    image, thumbnail = f"page{page.page}.webp", f"page{page.page}.thumb.webp"
    _render(pdf_page, IMAGE_WIDTH_PX, build_dir / image)
    _render(pdf_page, THUMBNAIL_WIDTH_PX, build_dir / thumbnail)

    rect = pdf_page.rect
    published = build_page(page.page, page.articles, narration, rect.width, rect.height, f"{OUT_DIR_NAME}/{image}")
    published.thumbnail = f"{OUT_DIR_NAME}/{thumbnail}"
    (build_dir / f"page{page.page}.json").write_text(published.model_dump_json(indent=2), encoding="utf-8")
    return PublishedPageEntry(
        page=page.page, aspect_ratio=published.aspect_ratio, segment_count=len(published.segments)
    )


def _render(page: pymupdf.Page, width_px: int, path: Path) -> None:
    zoom = width_px / page.rect.width
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    Image.frombytes("RGB", (pix.width, pix.height), pix.samples).save(path, "WEBP", quality=WEBP_QUALITY)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(run_id_from_args())
