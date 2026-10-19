"""The narration cascade's two LLM steps and their prompts: the article step cleans up
and summarizes each article (one call), the page step weaves a page's summaries into
its narration. Each is an LLMStage: a prompt, how to build the request from
its input, and how to turn the response into its output."""

import logging
import os
from dataclasses import dataclass

from google import genai
from pydantic import BaseModel
from tenacity import Retrying, stop_after_attempt, wait_exponential

from models import Article
from narration import ArticleCategory, NarratedArticle, PageSummary, PageSummarySentence
from source_info import NarrationContext
from summaries import ArticleSummary

log = logging.getLogger(__name__)

# Retries for synchronous calls: transient errors (rate limits, network) and
# responses that don't validate. A content-policy refusal exhausts them too
# (there's no second model to fall back to) and fails the run; the cache
# keeps everything that succeeded for the re-run.
_RETRY_POLICY = Retrying(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    reraise=True,
    before_sleep=lambda retry_state: log.warning(
        "transient error (attempt %d): %r -- retrying...", retry_state.attempt_number, retry_state.outcome.exception()
    ),
)


@dataclass
class ArticleResult:
    """One article's article-step result; summary is None when the article step judged it not
    a real article."""

    page_num: int
    article: Article
    summary: ArticleSummary | None


# Model names shift over time: if this 404s, check
# ai.google.dev/gemini-api/docs/models.
LLM_MODEL_ID = "gemini-3.5-flash-lite"
# The model produces no thinking tokens for these prompts anyway (measured
# 2026-10-05); pinned so a model change can't silently bill them. No
# sampling parameters (temperature etc.) on purpose: Google deprecated
# them for Gemini 3 and upcoming models reject requests that set them.
THINKING_LEVEL = "minimal"

# Only the page step gets a tone: the per-article summaries are an intermediate the
# listener never hears, so a different tone only needs new page-step calls.
#
# Picked per paper (`narration_tone` in config/papers.toml, via
# 00_source.json); the NARRATION_TONE env var overrides that for
# experiments (`NARRATION_TONE=radio_host uv run ...`). Add a new style by
# adding a key; a paper's free-text `tone_prompt` (e.g. regional wording)
# is appended after the chosen tone.
TONES: dict[str, str] = {
    "formal": ("Tone: formal, factual news-presenter style -- neutral and to the point, no colloquialisms."),
    "colloquial": (
        'Tone: colloquial, conversational "easy listen" style -- like a '
        "friend catching you up on the news, not a formal broadcast. Plain "
        "everyday words, contractions and casual connectors are fine (e.g. "
        '"Und dann...", "Übrigens...", "Kurz gesagt..."). Still fully '
        "faithful to the facts -- looser in phrasing, not in accuracy."
    ),
    "radio_host": (
        "Tone: upbeat local-radio-host energy -- warm, a little playful, "
        "genuinely engaged with the stories, like a morning-show host "
        "walking listeners through the day's news. Light enthusiasm and "
        "the occasional aside are welcome, but never at the expense of a "
        "fact or by trivializing a serious story -- read the room: stay "
        "warm on a light story, dial the energy down for a grave one."
    ),
    "storyteller": (
        "Tone: narrative, podcast-narrator style -- lean into "
        'scene-setting and cause-and-effect ("was passiert, wenn...", '
        '"das Ergebnis:..."), giving each story a clear shape (setup, '
        "development, payoff) rather than reading like a list of facts. "
        "Unhurried pacing, but still concise -- this is narrative framing, "
        "not padding, and every sentence must still be traceable to a "
        "real fact from the input."
    ),
    "brief": (
        "Tone: brief and dense -- the fastest possible catch-up, closer "
        "to spoken headlines than a narrated story. Short, punchy "
        "sentences, minimal connective tissue between stories, no "
        "scene-setting or color. Optimize for a listener who wants the "
        "facts in the fewest words, not for narrative flow."
    ),
}

DEFAULT_TONE = "colloquial"


def resolve_tone(paper_tone: str | None) -> str:
    """The tone NAME to use -- NARRATION_TONE from the environment if set,
    else the paper's own tone, else DEFAULT_TONE. Returning the name (not
    the instruction text) is what lets PageSummary.tone record which one
    actually produced a given result."""
    resolved = os.environ.get("NARRATION_TONE") or paper_tone or DEFAULT_TONE
    if resolved not in TONES:
        raise ValueError(f"Unknown tone {resolved!r} -- choose one of: {', '.join(sorted(TONES))}")
    return resolved


_CLEANUP_PROMPT_PART = (
    "You clean up and summarize German newspaper article text that was "
    "mechanically extracted from a scanned page, for a listen-only audio "
    "digest. Three jobs:\n\n"
    "1. Produce a cleaned headline. The user message includes a "
    "'Likely headline' line, identified upstream using font-size "
    "analysis you don't have access to from the flat text alone -- use "
    "it as your anchor and only lightly normalize it (fix stray "
    "spacing/OCR artifacts), rather than picking a different line "
    "yourself. The real headline sometimes isn't the first line of the "
    'text (e.g. a kicker/eyebrow/topic-tag line like "Verkehr - ..." '
    "often comes first, with the real headline appearing later, "
    "sometimes mid-paragraph, due to how a print column visually "
    "breaks) -- that's exactly why the font-size-based hint is more "
    "reliable here than picking the first headline-shaped line. Only "
    "deviate from the hint if it's clearly wrong for this article (e.g. "
    "it's actually an unrelated caption).\n"
    "IMPORTANT: a 'Likely headline' being present does NOT mean this is "
    "a real article -- that upstream extraction step fires on every "
    "input, including bare headlines with no story behind them. Judge "
    "whether it's a real article from the body content alone, per the "
    "empty-response rule below, same as if no headline hint were given.\n"
    "2. Work out which parts of the text actually belong to this "
    "article, and ignore any text that clearly doesn't (e.g. an "
    "unrelated teaser for a different story, a stray caption, a "
    "masthead line, a contact footer) that got glued on by the "
    "extraction process. Don't write this cleaned text out -- it's only "
    "what job 3 works from.\n\n"
    "Only respond with an empty headline and empty summary (category: "
    "miscellaneous) if there is no "
    "substantive information anywhere in the input at all -- no "
    "indication of what actually happened, who was involved, or what the "
    "news is (e.g. it's purely a caption fragment, a masthead/issue "
    "header, a leftover teaser-box stub, or a bare headline with nothing "
    "else). A short item is still a real article if it already states "
    "what happened, even if it has no separate headline/body split, or "
    "is just one or two sentences -- brevity alone is not a reason to "
    'skip it. Likewise, a news-in-brief box (e.g. headed "In Kürze" or '
    '"Kurz notiert") that collects several short, complete news items '
    "is real content, not glued-on text: summarize every item in it. "
    "Never invent or infer content that isn't in the input."
)

# What each ArticleCategory means, as shown to the article step's model.
CATEGORY_DESCRIPTIONS: dict[ArticleCategory, str] = {
    ArticleCategory.LOCAL_NEWS: (
        "news from the paper's own city or region (municipal politics, clubs, "
        "local people, construction, traffic) that no more specific category "
        "below fits"
    ),
    ArticleCategory.NON_LOCAL_NEWS: (
        "news from anywhere else -- state, national or international politics and "
        "society -- that no more specific category below fits"
    ),
    ArticleCategory.ECONOMY: "business, markets, companies, jobs, prices, finance",
    ArticleCategory.SPORTS: "sports at any level, from local clubs to international competitions",
    ArticleCategory.CULTURE: "arts, music, theater, film, literature, reviews of past performances",
    ArticleCategory.EVENT_RECOMMENDATION: (
        "tips for upcoming events the reader can still attend (concerts, festivals, "
        "markets, exhibitions, talks) -- forward-looking, with dates/places"
    ),
    ArticleCategory.TRAVEL: "travel destinations, holidays, excursions, travel tips",
    ArticleCategory.SCIENCE_TECH: "science, research, technology, digital topics",
    ArticleCategory.HEALTH: "health, medicine, care, nutrition",
    ArticleCategory.CRIME_ACCIDENTS: "police reports, crime, court cases, accidents, fires",
    ArticleCategory.CONSUMER_ADVICE: "practical guidance: money, law, housing, cars, household",
    ArticleCategory.OPINION: "commentary, editorials, columns, letters to the editor",
    ArticleCategory.MISCELLANEOUS: "anything else (human interest, curiosities, celebrities, weather)",
}
assert set(CATEGORY_DESCRIPTIONS) == set(ArticleCategory), "every ArticleCategory needs a description"

# Job 3 of the article step's prompt.
_SUMMARY_PROMPT_PART = (
    "3. Summarize only the article's own text from job 2 (none of the "
    "glued-on content) in German. Compress and smooth the "
    "prose, but do not introduce any fact, name, or number that isn't "
    "in the article -- faithfulness to the source matters more than "
    "polish. Aim for roughly a quarter of the original length.\n\n"
    "Write the summary as the content itself, the way the digest would "
    "narrate it directly -- never as commentary describing the article "
    'from outside (no "Der Artikel behandelt...", "Der Text berichtet '
    'über...", "Es geht um..." or similar framing). State the facts '
    "themselves, the way a news presenter would.\n\n"
    "Write this factually and neutrally, regardless of what final tone "
    "the digest ends up using -- this is an internal intermediate "
    "summary the listener never hears as-is; style/tone shaping happens "
    "later, in the page-level synthesis step, not here.\n\n"
    "Also classify the article into exactly one category, by its main "
    "topic rather than where it happened (a local football match is "
    "sports, a local company's results are economy; local_news and "
    "non_local_news are only for news no more specific category fits):\n"
    + "\n".join(f"- {c.value}: {d}" for c, d in CATEGORY_DESCRIPTIONS.items())
)

ARTICLE_SYSTEM_PROMPT = _CLEANUP_PROMPT_PART + "\n\n" + _SUMMARY_PROMPT_PART

# Appended for issues whose text is OCR of a scan (the run's 00_source.json
# says text_source "alto") -- not for born-digital PDFs, whose text is
# exact. Loosens job 1's "only lightly normalize the headline": large
# Fraktur headlines are where the OCR is worst (e.g. "Enlscheidlmg im Aull
# Seeül" for "Entscheidung im Fall Seeckt").
_OCR_PROMPT_PART = (
    "This article's text is OCR output from a scanned historic newspaper "
    "(1920s, mostly set in Fraktur type), so expect recognition errors: "
    'misread letters ("Rcgicrnng" for "Regierung", "ii" for '
    '"ü", "f" for the long s), garbled or split words, and stray '
    "characters. Headlines are hit hardest, since large Fraktur letters "
    "confuse the OCR most.\n"
    "So, overriding job 1's \"only lightly normalize\": the 'Likely "
    "headline' still tells you which line is the headline, but reconstruct "
    "what it actually says from its garbled letters together with the "
    "article's content. Read through OCR errors in the body the same way, "
    "taking the word the context makes clear. Write headline and summary "
    'in today\'s German spelling ("dass", not "daß").\n'
    "Check the reconstructed headline against the body before settling on "
    "it: its names and key words usually reappear there (a garbled "
    '"Gcncral Wiuz" over a story about General Wirz is "General '
    'Wirz"), and a headline that contradicts the body is wrong -- e.g. a '
    'dropped or misread letter turning "nicht" into "ich", or '
    '"gegen" into "wegen", where the body says otherwise. When the letters allow '
    "several readings, pick the one the body supports. If no reading is "
    "clearly supported by the body, don't guess from the letters: write a "
    "short, factual headline from the body instead (for a story about "
    'dockworkers going on strike, "Hafenarbeiter streiken" beats an '
    "invented word that merely resembles the garbled letters). A misread "
    'letter can also produce a real but wrong word ("Anfälle" over a '
    'story about accidents is "Unfälle"), so check those too.\n'
    "Advertisements in these papers are set as text, not pictures, so "
    "they reach you looking like articles. Treat one as having no "
    "substantive information and give the empty response: a text whose "
    "point is to sell or order something (a product or book with its "
    "price, a shop's address, a publisher's order details, a price list "
    "of goods) or the paper's own notices to advertisers and "
    "subscribers. Reporting about companies or prices (a market report, "
    "a firm's results) is still news.\n"
    "The no-invention rule still holds: a reconstruction must be clearly "
    "supported by the letters and the context. If a name, place or number "
    "can't be read with confidence, leave it out rather than guess."
)


# Appended for papers whose narration_context is "from_article" (historic
# papers, whose articles assume what their readers knew): only context the
# article itself gives, made explicit -- none from the model's own
# knowledge, too high a hallucination risk.
_CONTEXT_PROMPT_PART = (
    "This is a historic newspaper, written for readers of its own time. "
    "Its articles take for granted what those readers knew and today's "
    "listener doesn't: who a person was, what an institution, party or "
    "abbreviation stood for, what an earlier event or ongoing affair was "
    "about. Where the article itself gives such context -- a person's "
    "office, an event it recalls, what an organization does -- keep it "
    "in the summary and make it explicit, even if the article mentions "
    "it only in passing or far from where the person or thing first "
    'comes up ("Seeckt, der Chef der Heeresleitung", not just '
    '"Seeckt", when the article says he heads the army command). '
    "Give such context room within the summary's length rather than "
    "cutting it as a detail.\n"
    "Never add context from your own knowledge, however sure you are of "
    "it: if the article doesn't say who or what something is, leave it as "
    "the article has it."
)


def article_system_prompt(ocr: bool, narration_context: NarrationContext = "none") -> str:
    parts = [ARTICLE_SYSTEM_PROMPT]
    if ocr:
        parts.append(_OCR_PROMPT_PART)
    if narration_context == "from_article":
        parts.append(_CONTEXT_PROMPT_PART)
    return "\n\n".join(parts)


# The fixed part of the page step's prompt; PageSynthesisStage adds the tone.
_PAGE_SYSTEM_PROMPT_BODY = (
    "You are producing one coherent spoken overview of everything on a "
    "single newspaper page, for a listen-only audio digest, from a set "
    "of already-written per-article summaries.\n\n"
    "Each input article is labeled with its article_idx and its "
    "original source length in characters -- treat that length as a "
    "proxy for editorial prominence (a newspaper gives more space to "
    "more important stories) and allocate your narration accordingly: "
    "articles with a longer original length should get more sentences "
    "and more detail; short items should be covered briefly, in one "
    "sentence if that's enough.\n\n"
    "Write the overview in German, as a sequence of sentences that flow "
    "naturally from one story to the next (short transitions between "
    "topics, not a flat concatenation). Do not open with a fixed framing "
    'phrase like "Wir beginnen mit...", "Zum Auftakt...", "Zum '
    'Einstieg..." or similar meta-announcements introducing the digest '
    "itself -- across many pages read back to back these become "
    "repetitive filler. Start directly with the first story's content, "
    "and keep transitions between stories varied too, not a repeated "
    "formula.\n\n"
    "Every sentence -- including short transitions -- must be tagged "
    "with the article_idx of the story it is primarily about (a "
    "transition into a new story counts as belonging to that new "
    "story). Do not introduce any fact that isn't present in the input "
    "summaries."
)

# Appended to the page step's prompt alongside _CONTEXT_PROMPT_PART in the article step: the
# summaries carry the context, this keeps the page step from dropping it again.
_PAGE_CONTEXT_PROMPT_PART = (
    "The summaries keep context today's listener needs to follow these "
    "historic stories (who a person is, what an institution or earlier "
    "event was). Carry it into the narration instead of dropping it for "
    "brevity, but add none of your own."
)


class LLMStage[TIn, TResponse: BaseModel, TOut]:
    """One stage of the cascade: a single LLM call plus the code needed to
    build its request and interpret its response. Subclasses set
    `name`/`system_prompt`/`response_model` and implement
    `build_user_content`/`to_output`; `run` is the only thing callers
    need."""

    name: str
    system_prompt: str
    response_model: type[TResponse]

    def get_system_prompt(self) -> str:
        """Override when the prompt depends on more than the class (e.g. the
        tone)."""
        return self.system_prompt

    def build_user_content(self, input: TIn) -> str:
        raise NotImplementedError

    def to_output(self, input: TIn, response: TResponse) -> TOut:
        raise NotImplementedError

    def request_config(self) -> dict:
        """The Gemini request config, shared by run() and the Batch API
        (batch.py) so both paths send exactly the same settings."""
        return {
            "system_instruction": self.get_system_prompt(),
            "response_mime_type": "application/json",
            # response_schema (the SDK converts the Pydantic class), not
            # response_json_schema: the Batch API silently ignored the
            # latter -- 2026-10-05 test run, every page-step response came back
            # as a bare list in whatever shape the model liked, while the
            # same schema is enforced on synchronous calls.
            "response_schema": self.response_model,
            "thinking_config": {"thinking_level": THINKING_LEVEL},
        }

    def parse(self, input: TIn, response_text: str) -> TOut:
        return self.to_output(input, self.response_model.model_validate_json(response_text))

    def run(self, input: TIn) -> TOut:
        """One synchronous call: batch.py's fallback for a request the batch
        didn't answer usably. Retries transient errors and responses that
        don't validate."""
        client = genai.Client()  # GEMINI_API_KEY from the environment
        for attempt in _RETRY_POLICY:
            with attempt:
                response = client.models.generate_content(
                    model=LLM_MODEL_ID,
                    contents=self.build_user_content(input),
                    # AFC (client-side tool calling) is unused, and the SDK
                    # warns on every call when it's left on.
                    config={**self.request_config(), "automatic_function_calling": {"disable": True}},
                )
                return self.parse(input, response.text)


class _ArticleText(BaseModel):
    """The article step's response. No article_idx: it's known, and asking the model
    to echo it only risks a wrong one. An empty summary means "not a real
    article" (category is ignored then)."""

    headline: str
    summary: str
    category: ArticleCategory


class ArticleStage(LLMStage[Article, _ArticleText, ArticleSummary | None]):
    """The article step: cleanup (headline, not-a-real-article detection, ignoring
    glued-on content) plus summary and topic category, in one call. The
    cleaned text itself isn't asked for: it was ~75% of the output tokens,
    and nothing used it."""

    name = "article step: cleanup + summary"
    response_model = _ArticleText

    def __init__(self, ocr: bool = False, narration_context: NarrationContext = "none") -> None:
        # ocr: the text is OCR of a scan -- adds _OCR_PROMPT_PART;
        # narration_context: see article_system_prompt.
        self.system_prompt = article_system_prompt(ocr, narration_context)

    def build_user_content(self, article: Article) -> str:
        return f"Likely headline: {article.headline_guess}\n\n---\n\n{article.text}"

    def to_output(self, article: Article, response: _ArticleText) -> ArticleSummary | None:
        if not response.summary.strip():
            return None
        return ArticleSummary(
            article_idx=article.article_idx,
            headline=response.headline,
            summary=response.summary,
            category=response.category,
        )


@dataclass
class PageSynthesisInput:
    page_num: int
    summaries: list[ArticleSummary]
    # Article.text length, keyed by article_idx -- the prominence proxy
    # The page step's prompt uses to weight how much narration each story gets.
    original_lengths: dict[int, int]


class _PageSentences(BaseModel):
    sentences: list[PageSummarySentence]


class PageSynthesisStage(LLMStage[PageSynthesisInput, _PageSentences, PageSummary]):
    """The page step: weaves a page's per-article summaries into one coherent,
    sentence-attributed narrative. Caller is responsible for not invoking
    this with an empty summaries list (see pipeline.py's Pipeline) --
    there's nothing meaningful to synthesize from zero articles."""

    name = "page step: page synthesis"
    response_model = _PageSentences

    def __init__(
        self, narration_context: NarrationContext = "none", tone: str | None = None, tone_prompt: str | None = None
    ) -> None:
        # tone/tone_prompt: the paper's (see source_info); resolve_tone
        # still lets NARRATION_TONE override the tone.
        self._narration_context = narration_context
        self._tone = tone
        self._tone_prompt = tone_prompt

    def get_system_prompt(self) -> str:
        parts = [_PAGE_SYSTEM_PROMPT_BODY]
        if self._narration_context == "from_article":
            parts.append(_PAGE_CONTEXT_PROMPT_PART)
        parts.append(TONES[resolve_tone(self._tone)])
        if self._tone_prompt:
            parts.append(self._tone_prompt)
        return "\n\n".join(parts)

    def build_user_content(self, input: PageSynthesisInput) -> str:
        return "\n\n".join(
            f"[article_idx={s.article_idx}, original_length={input.original_lengths[s.article_idx]} chars]\n"
            f"{s.headline}\n{s.summary}"
            for s in input.summaries
        )

    def to_output(self, input: PageSynthesisInput, response: _PageSentences) -> PageSummary:
        known_idxs = {s.article_idx for s in input.summaries}
        for sentence in response.sentences:
            if sentence.article_idx not in known_idxs:
                log.warning("page summary referenced unknown article_idx %d", sentence.article_idx)
        articles = [
            NarratedArticle(article_idx=s.article_idx, headline=s.headline, category=s.category)
            for s in input.summaries
        ]
        return PageSummary(
            page=input.page_num,
            tone=resolve_tone(self._tone),
            articles=articles,
            sentences=response.sentences,
        )
