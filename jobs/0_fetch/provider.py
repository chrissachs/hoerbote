"""What every provider implements. A provider knows one archive or site
(DDB's newspaper portal, later e.g. a publisher's e-paper behind a login);
the generic part in run.py does the run dir, status.json, 00_source.json
and the rights warning around it.

Split in two so a lookup is cheap: `find` resolves an issue and reads its
metadata (ids, pages, rights) without downloading content, `download`
then writes the files."""

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from papers import Paper
from source_info import Rights, SourceInfo


class IssueNotFound(Exception):
    pass


@dataclass
class IssueRef:
    paper: Paper
    edition: str
    date: datetime.date
    item_id: str
    paper_title: str
    landing_url: str | None
    rights: Rights
    attribution: str
    pdf_url: str
    # Per page, in order (page 1 first).
    text_urls: list[str | None] = field(default_factory=list)
    image_urls: list[str | None] = field(default_factory=list)


class Provider(Protocol):
    def find(self, paper: Paper, edition: str, date: datetime.date) -> IssueRef: ...

    def download(self, ref: IssueRef, run_dir: Path) -> SourceInfo:
        """Writes 00_source.pdf (+ per-page text, when the source has it
        separately) into run_dir and returns what 00_source.json should
        say. Overwrites whatever a previous fetch left there."""
        ...


def http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """`transport`: tests pass an httpx.MockTransport."""
    return httpx.Client(
        timeout=httpx.Timeout(30, read=120),
        follow_redirects=True,
        transport=transport or httpx.HTTPTransport(retries=3),
        headers={"User-Agent": "hoerbote-fetch/0.1 (non-commercial research)"},
    )


def download_file(client: httpx.Client, url: str, dest: Path) -> None:
    # Via a temp name, so an interrupted download never looks complete.
    part = dest.with_name(dest.name + ".part")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with part.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    part.replace(dest)
