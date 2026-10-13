"""The narration job's intermediate: one article's article-step result. Its output,
PageSummary, is in shared's narration.py (the publish job reads it).

Named summaries.py, not models.py: that would collide with shared's
models.py, since both install their modules at the top level."""

from pydantic import BaseModel

from narration import ArticleCategory


class ArticleSummary(BaseModel):
    article_idx: int
    # The cleaned headline (anchored on the articles job's headline_guess)
    # -- what the page step and the frontend show for this story.
    headline: str
    summary: str
    category: ArticleCategory
