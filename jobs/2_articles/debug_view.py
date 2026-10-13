"""The job's debug view: every page with its blocks, labels, columns and
articles drawn on top. The job writes the data (02_articles/debug.json);
this script, run by hand, renders the pages and builds the page from it
-> 02_articles_view.html in the run dir, pages in 02_articles_view/ (open
the HTML from there: it references them relatively).

    uv run --project jobs/2_articles python jobs/2_articles/debug_view.py <run_id>"""

import json
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from bbox import scale_bbox
from models import Article, PageImage, TextBlock
from pipeline_run import run_dir, run_id_from_args

DEBUG_RENDER_DPI = 96
DATA_FILE_NAME = "debug.json"
OUT_NAME = "02_articles_view.html"
IMAGES_DIR_NAME = "02_articles_view"


@dataclass
class _PageDebugInput:
    """Everything one page's overlay needs (see DebugViewBuilder.add_page)."""

    page_num: int  # 1-based
    page: pymupdf.Page
    text_blocks: list[TextBlock]
    boundaries: list[float]
    articles: list[Article]
    images: list[PageImage]
    scale: float


def _page_debug_data(p: _PageDebugInput) -> dict:
    return {
        "page_num": p.page_num,
        # The size of the page rendered at DEBUG_RENDER_DPI (build() renders it).
        "width_px": round(p.page.rect.width * p.scale),
        "height_px": round(p.page.rect.height * p.scale),
        "column_boundaries_px": [round(x * p.scale, 1) for x in p.boundaries],
        "blocks": [
            {
                "bbox": scale_bbox(b.bbox, p.scale),
                "text": b.text,
                "font_size": b.max_font_size,
                "is_bold": b.is_bold,
                "is_italic": b.is_italic,
                "word_count": b.word_count,
                "excluded_short": b.excluded_short,
                "columns": b.columns,
                "article_idx": b.article_idx,
                "looks_like_headline": b.looks_like_headline,
                "is_caption": b.is_caption,
                "median_body_size": b.median_body_size,
            }
            for b in p.text_blocks
        ],
        "articles": [
            {
                "article_idx": a.article_idx,
                "columns": a.columns,
                "headline_guess": a.headline_guess,
                "text": a.text,
                "bbox": scale_bbox(a.bbox_union, p.scale),
            }
            for a in p.articles
        ],
        "images": [
            {
                "bbox": scale_bbox(img.bbox, p.scale),
                "article_idx": img.article_idx,
            }
            for img in p.images
        ],
    }


class DebugViewBuilder:
    """Collects the pages as run.py processes them; write() saves the debug
    view's data once all are in."""

    def __init__(self, scale: float) -> None:
        self._scale = scale
        self._pages: list[_PageDebugInput] = []

    def add_page(
        self,
        page_num: int,
        page: pymupdf.Page,
        text_blocks: list[TextBlock],
        boundaries: list[float],
        articles: list[Article],
        images: list[PageImage],
    ) -> None:
        self._pages.append(
            _PageDebugInput(
                page_num=page_num,
                page=page,
                text_blocks=text_blocks,
                boundaries=boundaries,
                articles=articles,
                images=images,
                scale=self._scale,
            )
        )

    def write(self, out_dir: Path) -> None:
        data = {"pages": [_page_debug_data(p) for p in self._pages]}
        (out_dir / DATA_FILE_NAME).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def build(run_id: str) -> Path:
    """Renders the pages and writes the debug view for a run the job has
    processed."""
    rd = run_dir(run_id)
    data_path = rd / "02_articles" / DATA_FILE_NAME
    if not data_path.is_file():
        raise SystemExit(f"no {data_path} -- run the articles job first")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    doc = pymupdf.open(str(rd / "00_source.pdf"))
    images_dir = rd / IMAGES_DIR_NAME
    images_dir.mkdir(exist_ok=True)
    for page in data["pages"]:
        image_path = images_dir / f"page{page['page_num']}.jpg"
        doc[page["page_num"] - 1].get_pixmap(dpi=DEBUG_RENDER_DPI).save(str(image_path), jpg_quality=80)
        page["image"] = image_path.relative_to(rd).as_posix()

    template = (Path(__file__).parent / "viewer_template.html").read_text(encoding="utf-8")
    out = rd / OUT_NAME
    out.write_text(template.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(f"Wrote {build(run_id_from_args())}")
