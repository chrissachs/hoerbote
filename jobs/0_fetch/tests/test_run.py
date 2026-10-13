"""run.py end to end against a mocked DDB: paper slug -> run dir with the
PDF, per-page ALTO, 00_source.json and status.json."""

import datetime
import json
import re
import xml.etree.ElementTree as ET

import httpx
import pytest
from test_ddb import _mets

import run
from ddb import API, SEARCH_URL, DdbProvider
from source_info import SourceInfo

DATE = datetime.date(1926, 10, 8)
RUN_ID = "berliner-tageblatt-morning-1926-10-08"
PD_MARK = "https://creativecommons.org/publicdomain/mark/1.0/"


def _fake_ddb(license_url: str, editions: tuple[str, ...] = ("Morgen-Ausgabe", "Abend-Ausgabe")):
    # The METS fixture's file URLs are bare names; make them absolute.
    mets = re.sub(rb':href="(?!http)', b':href="https://files.example/', ET.tostring(_mets(license_url, "some label")))
    files = {"issue.pdf": b"%PDF-fake", "ddb1.xml": b"<alto>1</alto>", "lib2.xml": b"<alto>2</alto>"}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(SEARCH_URL):
            # One hit per page; the morning edition is item ITEM.
            items = {"Morgen-Ausgabe": "ITEM", "Abend-Ausgabe": "OTHER"}
            docs = [
                {"id": f"{items[e]}-p{n}", "paper_title": f"Berliner Tageblatt, {e}"} for e in editions for n in (1, 2)
            ]
            return httpx.Response(200, json={"response": {"docs": docs}})
        if url == f"{API}/2/items/ITEM/source/record":
            return httpx.Response(200, content=mets)
        name = url.rsplit("/", 1)[-1]
        if name in files:
            return httpx.Response(200, content=files[name])
        return httpx.Response(404)

    return lambda: DdbProvider(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    return tmp_path


def test_fetch_writes_run_dir(data_root, monkeypatch):
    monkeypatch.setitem(run.PROVIDERS, "ddb", _fake_ddb(PD_MARK))
    assert run.run("berliner-tageblatt", DATE) == RUN_ID

    rd = data_root / "issues" / RUN_ID
    assert (rd / "00_source.pdf").read_bytes() == b"%PDF-fake"
    assert (rd / "00_page_text" / "page1.xml").read_bytes() == b"<alto>1</alto>"
    assert (rd / "00_page_text" / "page2.xml").read_bytes() == b"<alto>2</alto>"
    info = SourceInfo.model_validate_json((rd / "00_source.json").read_text())
    assert (info.paper, info.edition, info.date, info.text_source) == ("berliner-tageblatt", "morning", DATE, "alto")
    assert [p.text_file for p in info.pages] == ["00_page_text/page1.xml", "00_page_text/page2.xml"]
    assert info.rights.open
    assert info.narration_context == "from_article"
    status = json.loads((rd / "status.json").read_text())
    assert status["status"] == "succeeded"
    assert "warnings" not in status["steps"][0]


def test_closed_rights_still_fetch_with_a_warning(data_root, monkeypatch):
    monkeypatch.setitem(run.PROVIDERS, "ddb", _fake_ddb("http://rightsstatements.org/vocab/InC/1.0/"))
    run.run("berliner-tageblatt", DATE)
    status = json.loads((data_root / "issues" / RUN_ID / "status.json").read_text())
    assert status["status"] == "succeeded"
    assert "must not be served publicly" in status["steps"][0]["warnings"][0]


def test_if_new_skips_an_existing_run_without_network(data_root, monkeypatch):
    (data_root / "issues" / RUN_ID).mkdir(parents=True)
    monkeypatch.setitem(run.PROVIDERS, "ddb", lambda: pytest.fail("no lookup expected"))
    assert run.run("berliner-tageblatt", DATE, if_new=True) == RUN_ID
    assert not (data_root / "issues" / RUN_ID / "status.json").exists()


def test_dry_run_downloads_nothing(data_root, monkeypatch):
    monkeypatch.setitem(run.PROVIDERS, "ddb", _fake_ddb(PD_MARK))
    assert run.run("berliner-tageblatt", DATE, dry_run=True) == RUN_ID
    assert not (data_root / "issues").exists()


def test_missing_edition_is_reported(monkeypatch):
    monkeypatch.setitem(run.PROVIDERS, "ddb", _fake_ddb(PD_MARK, editions=["Morgen-Ausgabe"]))
    with pytest.raises(SystemExit, match="no issue of berliner-tageblatt \\(Abend-Ausgabe\\)"):
        run.run("berliner-tageblatt", DATE, edition="evening")
