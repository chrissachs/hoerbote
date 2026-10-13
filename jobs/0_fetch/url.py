"""Provider for papers whose issue PDF sits at a predictable URL: the
paper's `params["pdf_url"]` is a template filled with the issue's `date`
and `edition` (the edition's value in the paper's `editions`), e.g.
"https://example.org/epaper/{date:%Y%m%d}.pdf". The paper's `title`
names it in the attribution.

Only the PDF: the text comes from its text layer ("pdf"). Nothing states
rights, so they count as not open."""

import datetime
from pathlib import Path

import httpx

from papers import Paper
from provider import IssueNotFound, IssueRef, download_file, http_client
from source_info import Rights, SourceInfo


class UrlProvider:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._http = http_client(transport)

    def find(self, paper: Paper, edition: str, date: datetime.date) -> IssueRef:
        url = paper.params["pdf_url"].format(date=date, edition=paper.editions[edition])
        r = self._http.head(url)
        if r.status_code == 404:
            raise IssueNotFound(f"no issue of {paper.slug} on {date}: {url} not found")
        r.raise_for_status()
        return IssueRef(
            paper=paper,
            edition=edition,
            date=date,
            item_id=url,
            paper_title=paper.title,
            landing_url=None,
            rights=Rights(statement_url=None, label="not stated", holder=None, open=False),
            attribution=f"{paper.title}, {date:%d.%m.%Y}",
            pdf_url=url,
        )

    def download(self, ref: IssueRef, run_dir: Path) -> SourceInfo:
        run_dir.mkdir(parents=True, exist_ok=True)
        download_file(self._http, ref.pdf_url, run_dir / "00_source.pdf")
        return SourceInfo(
            paper=ref.paper.slug,
            paper_title=ref.paper_title,
            edition=ref.edition,
            date=ref.date,
            provider="url",
            provider_item_id=ref.item_id,
            landing_url=None,
            text_source="pdf",
            rights=ref.rights,
            attribution=ref.attribution,
            pages=[],
            narration_context=ref.paper.narration_context,
            narration_tone=ref.paper.narration_tone,
            tone_prompt=ref.paper.tone_prompt,
            speech_style=ref.paper.speech_style,
        )
