"""Provider for the Deutsche Digitale Bibliothek's newspaper portal
(Deutsches Zeitungsportal). Works for any title there, keyed by its ZDB
id; no API key needed.

1. The portal's search index (one hit per page) finds the issue's item
   id for a ZDB id + date; editions are told apart by the hit's title.
2. The item's METS record lists everything else. Page order and per-page
   files come from the PHYSICAL structMap's fptr pointers -- file ids
   and URLs differ per library (WLB: FILE_0008_DDB_FULLTEXT, SBB:
   fulltext_8_DDB_FULLTEXT; ALTO URLs are opaque UUIDs), so nothing is
   derived from naming patterns.
3. The whole-issue PDF is the DOWNLOAD file no page points to (the others
   are single-page PDFs)."""

import datetime
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import httpx

from papers import Paper
from provider import IssueNotFound, IssueRef, download_file, http_client
from source_info import PAGE_TEXT_DIR_NAME, Rights, SourceInfo, SourcePage

API = "https://api.deutsche-digitale-bibliothek.de"
SEARCH_URL = f"{API}/search/index/newspaper-issues/select"
NS = {
    "mets": "http://www.loc.gov/METS/",
    "mods": "http://www.loc.gov/mods/v3",
    "xlink": "http://www.w3.org/1999/xlink",
    "dv": "http://dfg-viewer.de/",
}
HREF = f"{{{NS['xlink']}}}href"
# Preferred first: DDB's copy of the ALTO, then the library's own (same
# bytes where checked); the largest page image.
TEXT_GROUPS = ("DDB_FULLTEXT", "FULLTEXT")
IMAGE_GROUPS = ("MAX", "DEFAULT")
# Rights statements that allow showing the content publicly. Compared
# without scheme and trailing slash (records mix http/https).
OPEN_STATEMENTS = (
    "creativecommons.org/publicdomain/mark/",
    "creativecommons.org/publicdomain/zero/",
    "creativecommons.org/licenses/by/",
    "creativecommons.org/licenses/by-sa/",
)


class DdbProvider:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._http = http_client(transport)

    def find(self, paper: Paper, edition: str, date: datetime.date) -> IssueRef:
        item_id, title = self._find_item(paper, edition, date)
        mets = self._get(f"{API}/2/items/{item_id}/source/record").content
        return _parse_mets(ET.fromstring(mets), paper, edition, date, item_id, title)

    def download(self, ref: IssueRef, run_dir: Path) -> SourceInfo:
        run_dir.mkdir(parents=True, exist_ok=True)
        self._download_file(ref.pdf_url, run_dir / "00_source.pdf")

        text_dir = run_dir / PAGE_TEXT_DIR_NAME
        if text_dir.exists():
            shutil.rmtree(text_dir)
        text_dir.mkdir()
        pages = []
        for n, (text_url, image_url) in enumerate(zip(ref.text_urls, ref.image_urls, strict=True), start=1):
            text_file = None
            if text_url:
                text_file = f"{PAGE_TEXT_DIR_NAME}/page{n}.xml"
                self._download_file(text_url, run_dir / text_file)
            pages.append(SourcePage(page=n, text_file=text_file, image_url=image_url))

        return SourceInfo(
            paper=ref.paper.slug,
            paper_title=ref.paper_title,
            edition=ref.edition,
            date=ref.date,
            provider="ddb",
            provider_item_id=ref.item_id,
            landing_url=ref.landing_url,
            text_source="alto",
            rights=ref.rights,
            attribution=ref.attribution,
            pages=pages,
            narration_context=ref.paper.narration_context,
            narration_tone=ref.paper.narration_tone,
            tone_prompt=ref.paper.tone_prompt,
            speech_style=ref.paper.speech_style,
        )

    def _find_item(self, paper: Paper, edition: str, date: datetime.date) -> tuple[str, str]:
        day = date.isoformat()
        query = f'zdb_id:"{paper.params["zdb_id"]}" AND publication_date:[{day}T00:00:00Z TO {day}T23:59:59Z]'
        docs = self._get(SEARCH_URL, params={"q": query, "fl": "id,paper_title", "rows": 1000, "wt": "json"}).json()
        titles: dict[str, str] = {}
        for doc in docs["response"]["docs"]:
            # Hit ids are "<item id>-<file id>"; item ids have no dash.
            titles[doc["id"].split("-", 1)[0]] = doc["paper_title"]

        label = paper.editions[edition]
        matches = {item: title for item, title in titles.items() if label in title}
        if len(matches) != 1:
            found = "; ".join(sorted(titles.values())) or "nothing"
            what = "no issue" if not matches else f"{len(matches)} issues"
            raise IssueNotFound(f"{what} of {paper.slug} ({label}) on {day} -- that day has: {found}")
        return next(iter(matches.items()))

    def _get(self, url: str, **kwargs) -> httpx.Response:
        r = self._http.get(url, **kwargs)
        r.raise_for_status()
        return r

    def _download_file(self, url: str, dest: Path) -> None:
        download_file(self._http, url, dest)


def _parse_mets(
    root: ET.Element, paper: Paper, edition: str, date: datetime.date, item_id: str, search_title: str
) -> IssueRef:
    page_files, pdf_url = _issue_files(root, item_id)
    mods = root.find(".//mods:mods", NS)
    paper_title = _text(mods, "mods:relatedItem[@type='host']/mods:titleInfo/mods:title") or search_title
    rights = _rights(root, mods)
    attribution = (
        f"{paper_title}, {paper.editions[edition]}, {date:%d.%m.%Y}. "
        f"Digitalisat: {rights.holder or 'unbekannt'}, {rights.label or 'Rechte unbekannt'}"
    )
    return IssueRef(
        paper=paper,
        edition=edition,
        date=date,
        item_id=item_id,
        paper_title=paper_title,
        landing_url=_text(mods, "mods:location/mods:url[@access='object in context']"),
        rights=rights,
        attribution=attribution,
        pdf_url=pdf_url,
        text_urls=[_first(p, TEXT_GROUPS) for p in page_files],
        image_urls=[_first(p, IMAGE_GROUPS) for p in page_files],
    )


def _issue_files(root: ET.Element, item_id: str) -> tuple[list[dict[str, str]], str]:
    """Per page (in order): fileGrp USE -> URL; and the whole-issue PDF."""
    files: dict[str, tuple[str, str]] = {}  # file id -> (fileGrp USE, URL)
    for group in root.iterfind(".//mets:fileGrp", NS):
        for f in group.iterfind("mets:file", NS):
            loc = f.find("mets:FLocat", NS)
            if loc is not None:
                files[f.get("ID")] = (group.get("USE"), loc.get(HREF))

    page_divs = sorted(
        (
            div
            for sm in root.iterfind(".//mets:structMap[@TYPE='PHYSICAL']", NS)
            for div in sm.iterfind(".//mets:div[@TYPE='page']", NS)
        ),
        key=lambda div: int(div.get("ORDER")),
    )
    if not page_divs:
        raise IssueNotFound(f"METS of item {item_id} lists no pages")
    page_files: list[dict[str, str]] = []
    for div in page_divs:
        by_group = defaultdict(list)
        for ptr in div.iterfind("mets:fptr", NS):
            if (fid := ptr.get("FILEID")) in files:
                group, url = files[fid]
                by_group[group].append(url)
        page_files.append({g: urls[0] for g, urls in by_group.items()})

    page_file_ids = {ptr.get("FILEID") for div in page_divs for ptr in div.iterfind("mets:fptr", NS)}
    issue_pdfs = [url for fid, (group, url) in files.items() if group == "DOWNLOAD" and fid not in page_file_ids]
    if len(issue_pdfs) != 1:
        raise IssueNotFound(f"METS of item {item_id} has {len(issue_pdfs)} whole-issue PDFs, expected 1")
    return page_files, issue_pdfs[0]


def _rights(root: ET.Element, mods: ET.Element | None) -> Rights:
    cond = mods.find("mods:accessCondition[@type='use and reproduction']", NS) if mods is not None else None
    url = cond.get(HREF) if cond is not None else _text(root, ".//dv:license")
    label = cond.text.strip() if cond is not None and cond.text else None
    holder = _text(root, ".//dv:owner") or _text(mods, "mods:location/mods:physicalLocation")
    normalised = (url or "").split("://", 1)[-1].rstrip("/") + "/"
    return Rights(
        statement_url=url, label=label, holder=holder, open=any(normalised.startswith(s) for s in OPEN_STATEMENTS)
    )


def _text(el: ET.Element | None, path: str) -> str | None:
    found = el.find(path, NS) if el is not None else None
    return found.text.strip() if found is not None and found.text else None


def _first(page: dict[str, str], groups: tuple[str, ...]) -> str | None:
    return next((page[g] for g in groups if g in page), None)
