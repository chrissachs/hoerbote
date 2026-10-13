"""On-disk cache of the article step's results (03_rewritten/cache/), keyed by
(page, article_idx) plus a fingerprint of the prompt and the article. The
article step doesn't depend on the tone, so trying another tone only calls
the LLM for the page step.

The fingerprint makes an edited prompt, or an articles-job re-run that
regrouped a page (same article_idx, different article), a cache miss
instead of serving stale output."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from models import Article
from stages import ARTICLE_SYSTEM_PROMPT
from summaries import ArticleSummary


def _fingerprint(system_prompt: str, article: Article) -> str:
    # The article's part: what ArticleStage sends besides the prompt.
    data = "\0".join([system_prompt, article.headline_guess, article.text])
    return hashlib.sha256(data.encode()).hexdigest()[:12]


@dataclass
class CacheEntry:
    """A cache hit. summary is None when the article step judged the article not a
    real one -- a cached result too, distinct from a miss (get() -> None)."""

    summary: ArticleSummary | None


class ArticleCache:
    def __init__(self, cache_dir: Path, system_prompt: str = ARTICLE_SYSTEM_PROMPT) -> None:
        """`system_prompt`: the article-step prompt this run actually uses (it
        differs for OCR text, see stages.article_system_prompt)."""
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._system_prompt = system_prompt

    def _path(self, page_num: int, article_idx: int) -> Path:
        return self._dir / f"page{page_num}_article{article_idx}.json"

    def get(self, page_num: int, article: Article) -> CacheEntry | None:
        """None means a cache miss (never cached, or cached under a
        different article-step prompt or for a different article) -- caller
        should run the article step for real."""
        path = self._path(page_num, article.article_idx)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("fingerprint") != _fingerprint(self._system_prompt, article):
            return None
        summary = ArticleSummary.model_validate(data["summary"]) if data["summary"] is not None else None
        return CacheEntry(summary)

    def set(self, page_num: int, article: Article, summary: ArticleSummary | None) -> None:
        data = {
            "fingerprint": _fingerprint(self._system_prompt, article),
            "summary": summary.model_dump(mode="json") if summary is not None else None,
        }
        self._path(page_num, article.article_idx).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
