"""Runs the cascade (stages.py) over a whole issue via the Batch API, and
reads/writes the per-page narration files."""

import json
from pathlib import Path

from batch import run_batch
from cache import ArticleCache
from models import Article, PageReport
from narration import PageSummary
from pipeline_run import run_dir
from source_info import NarrationContext
from stages import ArticleResult, ArticleStage, PageSynthesisInput, PageSynthesisStage

# One page{N}.narration.json per page, not one file per issue, so a page
# can be rewritten on its own.
NARRATION_DIR_NAME = "03_rewritten"

# Inside the job's own output folder; run.py only ever deletes the
# page{N}.narration.json files there, never the folder.
CACHE_DIR_NAME = f"{NARRATION_DIR_NAME}/cache"


def load_all_pages(run_id: str) -> list[PageReport]:
    report_path = run_dir(run_id) / "02_articles" / "report.json"
    return [PageReport.model_validate(p) for p in json.loads(report_path.read_text())]


class Pipeline:
    """Runs the article step (cleanup + summary, one call) for each
    article, then the page step over whatever the article step produced.
    Article-step results go through `cache` (see cache.py), so a second run (e.g.
    trying a different NARRATION_TONE, which only affects the page step) skips straight
    to cached results instead of re-calling the LLM for the article step."""

    def __init__(
        self,
        cache: ArticleCache,
        ocr: bool = False,
        narration_context: NarrationContext = "none",
        tone: str | None = None,
        tone_prompt: str | None = None,
    ) -> None:
        # ocr: the articles' text is OCR of a scan; the rest: the paper's
        # (see source_info). ocr and narration_context shape the article-step
        # prompt (see ArticleStage), and the cache must have been made
        # with the same; the tone only reaches the page step.
        self.article = ArticleStage(ocr, narration_context)
        self.page_synthesis = PageSynthesisStage(narration_context, tone, tone_prompt)
        self.cache = cache

    def process_issue_batched(self, pages: list[PageReport], job_dir: Path) -> dict[int, PageSummary | None]:
        """Every page's narration (None for a page with no real articles
        after cleanup), keyed by page number. Two batch jobs: all
        uncached articles' article step first, then every page's page step -- the page step needs
        a page's summaries, so the two can't share one job. `job_dir`
        holds batch.py's resume files while a job is in flight."""
        cache = self.cache
        uncached = [(p.page, a) for p in pages for a in p.articles if cache.get(p.page, a) is None]
        print(f"Article step: {len(uncached)} uncached article(s) of {sum(len(p.articles) for p in pages)}")
        outputs = run_batch(self.article, [a for _, a in uncached], job_dir / "batch_articles.json")
        for (page_num, article), summary in zip(uncached, outputs, strict=True):
            cache.set(page_num, article, summary)

        synthesis_inputs: list[PageSynthesisInput] = []
        for page in pages:
            results = []
            for article in page.articles:
                summary = cache.get(page.page, article).summary
                results.append(ArticleResult(page.page, article, summary))
            synthesis_input = _page_synthesis_input(page.page, page.articles, results)
            if synthesis_input is not None:
                synthesis_inputs.append(synthesis_input)
        page_summaries = run_batch(self.page_synthesis, synthesis_inputs, job_dir / "batch_pages.json")

        narrations: dict[int, PageSummary | None] = {p.page: None for p in pages}
        for synthesis_input, page_summary in zip(synthesis_inputs, page_summaries, strict=True):
            narrations[synthesis_input.page_num] = page_summary
        return narrations


def _page_synthesis_input(
    page_num: int, articles: list[Article], results: list[ArticleResult]
) -> PageSynthesisInput | None:
    """None when the article step left no real article on the page -- there's
    nothing meaningful for the page step to synthesize from zero articles."""
    summaries = [r.summary for r in results if r.summary is not None]
    if not summaries:
        return None
    original_lengths = {a.article_idx: len(a.text) for a in articles}
    return PageSynthesisInput(page_num, summaries, original_lengths)


def write_page_narration(run_id: str, page_summary: PageSummary) -> Path:
    """Writes (or overwrites) one page's page{N}.narration.json."""
    out_dir = run_dir(run_id) / NARRATION_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"page{page_summary.page}.narration.json"
    path.write_text(page_summary.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_all_narrations(run_id: str) -> list[PageSummary]:
    """Every page{N}.narration.json already written for this run (see
    write_page_narration), in page order -- for reading back the actual
    production output (render_narration.py)."""
    narration_dir = run_dir(run_id) / NARRATION_DIR_NAME
    pages = [
        PageSummary.model_validate_json(f.read_text(encoding="utf-8")) for f in narration_dir.glob("*.narration.json")
    ]
    return sorted(pages, key=lambda p: p.page)
