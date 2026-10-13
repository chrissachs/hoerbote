"""The fetch -> everything-after contract: 00_source.json at the run root.
Where the issue came from, which text source to read, under what rights it
may be shown, and the paper's narration settings."""

import datetime
from typing import Literal

from pydantic import BaseModel

SOURCE_INFO_FILE_NAME = "00_source.json"

NarrationContext = Literal["none", "from_article"]
PAGE_TEXT_DIR_NAME = "00_page_text"


class Rights(BaseModel):
    # The machine-readable statement, e.g.
    # https://creativecommons.org/publicdomain/mark/1.0/ -- None when the
    # source states nothing (treat as not open).
    statement_url: str | None
    label: str | None
    # Who holds/provides the digitised copy (named in the attribution).
    holder: str | None
    # True only for statements that allow showing the content publicly
    # (public domain marks, CC0, CC BY/BY-SA). A demo deployment must only
    # serve issues where this is true.
    open: bool


class SourcePage(BaseModel):
    page: int
    # Relative to the run dir; None when the text comes from the PDF.
    text_file: str | None = None
    # The source's own full-resolution page image, kept as a URL only --
    # fetched later if the PDF render turns out not to line up with it.
    image_url: str | None = None


class SourceInfo(BaseModel):
    paper: str
    paper_title: str
    edition: str
    date: datetime.date
    provider: str
    provider_item_id: str
    # Where a human can look at the original issue.
    landing_url: str | None
    # For the articles job: "pdf" = the PDF's embedded text (a born-digital
    # e-paper), "alto" = one ALTO XML per page (OCR of a scan, see
    # SourcePage.text_file).
    text_source: Literal["pdf", "alto"]
    rights: Rights
    attribution: str
    pages: list[SourcePage]
    # Copied from the paper's entry in config/papers.toml. How much
    # context the narration gives a listener who lacks what the paper's
    # readers knew: "from_article" spells out context the article itself
    # gives (who a person is, what an earlier event was), never any from
    # the model's own knowledge.
    narration_context: NarrationContext = "none"
    # A key of the narration job's TONES (None: its default), and free text
    # added after the tone, e.g. regional wording.
    narration_tone: str | None = None
    tone_prompt: str | None = None
    # How the audio job's TTS voices should speak (free text, e.g. an accent);
    # None: its neutral default.
    speech_style: str | None = None
