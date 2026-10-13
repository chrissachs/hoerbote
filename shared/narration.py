"""The narration -> publish contract: one 03_rewritten/page{N}.narration.json
per page. A page's narration is a list of sentences, each traced back to
the article it's about."""

from enum import StrEnum

from pydantic import BaseModel


class ArticleCategory(StrEnum):
    """Topic of one article, picked by the narration job (what each one
    means to the model: CATEGORY_DESCRIPTIONS in its stages.py, where a new
    member needs a description too). Topic, not geography: a local football
    match is `sports`; the two news categories are only for news no more
    specific category fits. Deliberately coarse: meant for picking a voice
    per topic."""

    LOCAL_NEWS = "local_news"
    NON_LOCAL_NEWS = "non_local_news"
    ECONOMY = "economy"
    SPORTS = "sports"
    CULTURE = "culture"
    EVENT_RECOMMENDATION = "event_recommendation"
    TRAVEL = "travel"
    SCIENCE_TECH = "science_tech"
    HEALTH = "health"
    CRIME_ACCIDENTS = "crime_accidents"
    CONSUMER_ADVICE = "consumer_advice"
    OPINION = "opinion"
    MISCELLANEOUS = "miscellaneous"


class PageSummarySentence(BaseModel):
    sentence: str
    # Asked of the model (which story a sentence is about), unlike every
    # other article_idx, which is set in code.
    article_idx: int


class NarratedArticle(BaseModel):
    """One story a PageSummary's sentences can point at (via article_idx);
    set in code, not asked of the model."""

    article_idx: int
    headline: str
    category: ArticleCategory


class PageSummary(BaseModel):
    page: int
    # The TONES key (narration job's stages.py) that produced the sentences.
    tone: str
    # Every article that went into the page's narration, in input order, so
    # a sentence's headline/category can be looked up from this file alone.
    articles: list[NarratedArticle]
    sentences: list[PageSummarySentence]
