"""Narration job: an issue's articles -> one page{N}.narration.json per page
in 03_rewritten/ (read it as one HTML page with render_narration.py).

Needs GEMINI_API_KEY (this folder's .env, or `docker run -e`). The tone is
the paper's (00_source.json), else "colloquial"; NARRATION_TONE overrides it.
Runs via the Gemini Batch API (batch.py, half price): one job for every
uncached article's article step, then one for every page's page step. A job usually takes
minutes but may take up to 24h; this blocks and polls, and a re-run after
an interruption resumes the same job instead of paying for a new one."""

import logging
from pathlib import Path

from dotenv import load_dotenv

from cache import ArticleCache
from narration import PageSummary
from pipeline import CACHE_DIR_NAME, NARRATION_DIR_NAME, Pipeline, load_all_pages, write_page_narration
from pipeline_run import run_dir, run_id_from_args, step
from source_info import SOURCE_INFO_FILE_NAME, NarrationContext, SourceInfo
from stages import article_system_prompt, resolve_tone

# From this job's own folder, not the repo root or CWD. google-genai only
# reads GEMINI_API_KEY when a client is created, i.e. at call time.
load_dotenv(Path(__file__).parent / ".env")

STEP_NAME = "narration"

log = logging.getLogger(__name__)


def run(run_id: str) -> None:
    rd = run_dir(run_id)
    articles_dir = rd / "02_articles"
    report_path = articles_dir / "report.json"
    out_dir = rd / NARRATION_DIR_NAME

    if not report_path.exists():
        raise FileNotFoundError(
            f"missing {report_path} -- the articles job must complete for this run before the narration job can run."
        )
    ocr, narration_context, paper_tone, tone_prompt = _paper_settings(rd)

    with step(run_id, STEP_NAME, input_path=str(articles_dir)) as s:
        cache = ArticleCache(rd / CACHE_DIR_NAME, article_system_prompt(ocr, narration_context))
        pipeline = Pipeline(cache, ocr, narration_context, paper_tone, tone_prompt)
        if ocr:
            log.info("Text is OCR of a scan: using the OCR cleanup prompt")
        if narration_context != "none":
            log.info("Narration context: %s", narration_context)
        # Also validates the tone now, before any (paid) batch job runs.
        log.info("Tone: %s%s", resolve_tone(paper_tone), " + the paper's tone prompt" if tone_prompt else "")
        pages = load_all_pages(run_id)
        log.info("Processing %d pages for run %s...", len(pages), run_id)
        _write_narrations(run_id, out_dir, pipeline.process_issue_batched(pages, rd / CACHE_DIR_NAME))
        s.finish(str(out_dir))


def _paper_settings(rd: Path) -> tuple[bool, NarrationContext, str | None, str | None]:
    """(ocr, narration_context, tone, tone_prompt) from the run's
    00_source.json. OCR text gets a more forgiving cleanup prompt."""
    info = SourceInfo.model_validate_json((rd / SOURCE_INFO_FILE_NAME).read_text())
    return info.text_source == "alto", info.narration_context, info.narration_tone, info.tone_prompt


def _write_narrations(run_id: str, out_dir: Path, narrations: dict[int, PageSummary | None]) -> None:
    # A page that had narration in an earlier run but has none now (e.g.
    # its only articles were ads) must not keep the old file.
    for old in out_dir.glob("page*.narration.json"):
        old.unlink()
    empty_pages = [page_num for page_num, summary in narrations.items() if summary is None]
    for page_summary in narrations.values():
        if page_summary is not None:
            log.info("Page %d: wrote %s", page_summary.page, write_page_narration(run_id, page_summary))
    log.info("Done. %d/%d pages have narration.", len(narrations) - len(empty_pages), len(narrations))
    if empty_pages:
        log.info("Pages with no real articles (e.g. full-page ads): %s", empty_pages)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # google-genai's client logs every request (the batch polling too) at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run(run_id_from_args())
