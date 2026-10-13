"""ALTO reader against a tiny synthetic page -- the shape of the SBB
files (styles by STYLEREFS, STYLE="bold", hyphenation via SUBS_CONTENT),
no real newspaper text."""

from alto_io import extract_alto_text_blocks
from layout_cache import LayoutRegion
from models import BBox

# 1000 px wide scan, so a 500 pt PDF page scales everything by 0.5. One
# ALTO block holding a headline line and two body lines -- the fused case.
ALTO = """<?xml version="1.0" encoding="UTF-8"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v3#">
<Styles><TextStyle ID="body" FONTSIZE="10"/><TextStyle ID="head" FONTSIZE="30"/></Styles>
<Layout><Page WIDTH="1000" HEIGHT="1400"><PrintSpace>
  <TextBlock HPOS="100" VPOS="100" WIDTH="800" HEIGHT="300" STYLEREFS="body">
    <TextLine HPOS="100" VPOS="100" WIDTH="800" HEIGHT="80" STYLEREFS="head">
      <String CONTENT="Big" STYLE="bold" HPOS="100" VPOS="100" WIDTH="200" HEIGHT="80"/>
      <String CONTENT="News" STYLE="bold" HPOS="320" VPOS="100" WIDTH="300" HEIGHT="80"/>
    </TextLine>
    <TextLine HPOS="100" VPOS="250" WIDTH="800" HEIGHT="30">
      <String CONTENT="Die" HPOS="100" VPOS="250" WIDTH="60" HEIGHT="30"/>
      <String CONTENT="Ent" SUBS_TYPE="HypPart1" SUBS_CONTENT="Entscheidung" HPOS="180" VPOS="250" WIDTH="60" HEIGHT="30"/>
      <HYP CONTENT="-"/>
    </TextLine>
    <TextLine HPOS="100" VPOS="300" WIDTH="800" HEIGHT="30">
      <String CONTENT="scheidung" SUBS_TYPE="HypPart2" SUBS_CONTENT="Entscheidung" HPOS="100" VPOS="300" WIDTH="150" HEIGHT="30"/>
      <String CONTENT="fiel." HPOS="270" VPOS="300" WIDTH="80" HEIGHT="30"/>
    </TextLine>
  </TextBlock>
</PrintSpace></Page></Layout></alto>"""

# In PDF points (half the scan pixels): the headline line's centre is at
# y=70, the body lines' at y=132/157.
#
# Font sizes come out in PDF points: line height (pt) / FONTSIZE is 40/30,
# 15/10 and 15/10 here, median 1.5, so FONTSIZE 30 -> 45 pt, 10 -> 15 pt.
REGIONS = [
    LayoutRegion(position=0, label="SectionHeader", bbox=BBox(x0=40, y0=40, x1=460, y1=100)),
    LayoutRegion(position=1, label="Text", bbox=BBox(x0=40, y0=110, x1=460, y1=200)),
]


def _blocks(tmp_path, regions):
    path = tmp_path / "page1.xml"
    path.write_text(ALTO, encoding="utf-8")
    return extract_alto_text_blocks(path, page_width_pt=500, regions=regions)


def test_fused_alto_block_is_split_at_region_boundaries(tmp_path):
    head, body = _blocks(tmp_path, REGIONS)
    assert head.text == "Big News"
    assert head.is_bold and head.max_font_size == 45
    assert body.text == "Die Entscheidung fiel."
    assert not body.is_bold and body.max_font_size == 15
    assert body.word_count == 3


def test_coordinates_scaled_to_pdf_points(tmp_path):
    head, body = _blocks(tmp_path, REGIONS)
    assert (head.bbox.x0, head.bbox.y0, head.bbox.x1, head.bbox.y1) == (50, 50, 450, 90)
    assert (body.bbox.y0, body.bbox.y1) == (125, 165)


def test_lines_outside_every_region_stay_one_block(tmp_path):
    (only,) = _blocks(tmp_path, [])
    assert only.text == "Big News Die Entscheidung fiel."
    assert only.max_font_size == 45 and only.min_font_size == 15
    assert only.max_font_char_count == len("Big") + len("News")


def test_bold_first_word_doesnt_make_a_paragraph_bold(tmp_path):
    # A bold dateline ("Peking, 7. Oktober.") opening a body paragraph.
    path = tmp_path / "page1.xml"
    path.write_text(ALTO.replace('CONTENT="Die"', 'CONTENT="Die" STYLE="bold"'), encoding="utf-8")
    head, body = extract_alto_text_blocks(path, page_width_pt=500, regions=REGIONS)
    assert head.is_bold
    assert not body.is_bold
