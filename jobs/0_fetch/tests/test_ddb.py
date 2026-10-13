"""METS parsing against a small synthetic record -- shaped like the real
SBB/WLB ones (OAI wrapper, page divs pointing at file ids), no network."""

import datetime
import xml.etree.ElementTree as ET

import pytest

from ddb import _parse_mets
from papers import load_papers
from run import make_run_id

PAPER = load_papers()["berliner-tageblatt"]
DATE = datetime.date(1926, 10, 8)


def _mets(license_url: str, label: str) -> ET.Element:
    def file(fid, url):
        return f'<mets:file ID="{fid}"><mets:FLocat LOCTYPE="URL" xlink:href="{url}"/></mets:file>'

    # Pages deliberately out of document order; page 2 has only the
    # library's own ALTO, page 1 both copies.
    return ET.fromstring(f"""
<record xmlns:mets="http://www.loc.gov/METS/" xmlns:mods="http://www.loc.gov/mods/v3"
        xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:dv="http://dfg-viewer.de/"><metadata><mets:mets>
  <mets:dmdSec><mets:mdWrap><mets:xmlData><mods:mods>
    <mods:relatedItem type="host"><mods:titleInfo><mods:title>Berliner Tageblatt</mods:title></mods:titleInfo></mods:relatedItem>
    <mods:accessCondition type="use and reproduction" xlink:href="{license_url}">{label}</mods:accessCondition>
    <mods:location><mods:url access="object in context">https://example.org/issue</mods:url></mods:location>
  </mods:mods></mets:xmlData></mets:mdWrap></mets:dmdSec>
  <mets:amdSec><mets:rightsMD><mets:mdWrap><mets:xmlData><dv:rights><dv:owner>Staatsbibliothek zu Berlin</dv:owner></dv:rights></mets:xmlData></mets:mdWrap></mets:rightsMD></mets:amdSec>
  <mets:fileSec>
    <mets:fileGrp USE="MAX">{file("max_1", "img1")}{file("max_2", "img2")}</mets:fileGrp>
    <mets:fileGrp USE="DOWNLOAD">{file("download_0", "issue.pdf")}{file("download_1", "p1.pdf")}{file("download_2", "p2.pdf")}</mets:fileGrp>
    <mets:fileGrp USE="FULLTEXT">{file("fulltext_1", "lib1.xml")}{file("fulltext_2", "lib2.xml")}</mets:fileGrp>
    <mets:fileGrp USE="DDB_FULLTEXT">{file("fulltext_1_DDB_FULLTEXT", "ddb1.xml")}</mets:fileGrp>
  </mets:fileSec>
  <mets:structMap TYPE="PHYSICAL"><mets:div TYPE="physSequence">
    <mets:div ORDER="2" TYPE="page"><mets:fptr FILEID="max_2"/><mets:fptr FILEID="download_2"/><mets:fptr FILEID="fulltext_2"/></mets:div>
    <mets:div ORDER="1" TYPE="page"><mets:fptr FILEID="max_1"/><mets:fptr FILEID="download_1"/><mets:fptr FILEID="fulltext_1"/><mets:fptr FILEID="fulltext_1_DDB_FULLTEXT"/></mets:div>
  </mets:div></mets:structMap>
  <mets:structMap TYPE="LOGICAL"><mets:div TYPE="issue"><mets:fptr FILEID="download_0"/></mets:div></mets:structMap>
</mets:mets></metadata></record>""")


def test_pages_in_order_with_preferred_text_and_issue_pdf():
    ref = _parse_mets(
        _mets("https://creativecommons.org/publicdomain/mark/1.0/", "Public Domain Mark 1.0"),
        PAPER,
        "morning",
        DATE,
        "ITEM",
        "search title",
    )
    assert ref.text_urls == ["ddb1.xml", "lib2.xml"]
    assert ref.image_urls == ["img1", "img2"]
    assert ref.pdf_url == "issue.pdf"
    assert ref.paper_title == "Berliner Tageblatt"
    assert ref.landing_url == "https://example.org/issue"
    assert ref.attribution == (
        "Berliner Tageblatt, Morgen-Ausgabe, 08.10.1926. "
        "Digitalisat: Staatsbibliothek zu Berlin, Public Domain Mark 1.0"
    )


@pytest.mark.parametrize(
    ("url", "is_open"),
    [
        ("https://creativecommons.org/publicdomain/mark/1.0/", True),
        ("http://creativecommons.org/publicdomain/zero/1.0/", True),
        ("https://creativecommons.org/licenses/by-sa/4.0", True),
        ("https://creativecommons.org/licenses/by-nc/4.0/", False),
        ("http://rightsstatements.org/vocab/InC/1.0/", False),
    ],
)
def test_only_open_statements_count_as_open(url, is_open):
    ref = _parse_mets(_mets(url, "x"), PAPER, "morning", DATE, "ITEM", "t")
    assert ref.rights.open is is_open


def test_run_id():
    assert make_run_id("berliner-tageblatt", "morning", DATE) == "berliner-tageblatt-morning-1926-10-08"
