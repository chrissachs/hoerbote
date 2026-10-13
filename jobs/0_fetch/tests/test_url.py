"""The URL-template provider against a mocked server."""

import datetime

import httpx
import pytest

from papers import Paper
from provider import IssueNotFound
from url import UrlProvider

DATE = datetime.date(2026, 10, 12)
PAPER = Paper(
    slug="daily",
    provider="url",
    title="Daily",
    years_back=0,
    editions={"morning": "m", "evening": "e"},
    params={"pdf_url": "https://example.org/{edition}/{date:%Y%m%d}.pdf"},
    speech_style="leise",
)


def _provider(existing: set[str]) -> UrlProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) not in existing:
            return httpx.Response(404)
        return httpx.Response(200, content=b"" if request.method == "HEAD" else b"%PDF-fake")

    return UrlProvider(transport=httpx.MockTransport(handler))


def test_template_filled_with_date_and_edition(tmp_path):
    url = "https://example.org/e/20261012.pdf"
    provider = _provider({url})
    ref = provider.find(PAPER, "evening", DATE)
    assert (ref.pdf_url, ref.attribution, ref.rights.open) == (url, "Daily, 12.10.2026", False)

    info = provider.download(ref, tmp_path)
    assert (tmp_path / "00_source.pdf").read_bytes() == b"%PDF-fake"
    assert (info.text_source, info.provider, info.speech_style) == ("pdf", "url", "leise")


def test_missing_issue_is_not_found():
    with pytest.raises(IssueNotFound, match="no issue of daily on 2026-10-12"):
        _provider(set()).find(PAPER, "morning", DATE)
