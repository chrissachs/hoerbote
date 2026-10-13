"""Debug view of the layout job's output: every page with its regions
drawn on top (label colour, reading-order number) and, when the run has
ALTO, the ALTO TextBlocks too -> 01_layout_view.html in the run dir, with
the pages rendered into 01_layout_view/ at the DPI the model saw (open the
HTML from there: it references them relatively).

    uv run --project jobs/1_layout python jobs/1_layout/debug_view.py <run_id>"""

import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf

from layout_cache import load_region_cache
from layout_model import render_page_image
from pipeline_run import run_dir, run_id_from_args
from source_info import PAGE_TEXT_DIR_NAME

OUT_NAME = "01_layout_view.html"
IMAGES_DIR_NAME = "01_layout_view"
LABEL_COLOURS = {
    "Text": "#2563eb",
    "SectionHeader": "#dc2626",
    "PageHeader": "#9333ea",
    "Picture": "#16a34a",
    "Figure": "#16a34a",
    "Caption": "#ea580c",
    "Table": "#0891b2",
    "ListGroup": "#ca8a04",
    "Form": "#64748b",
    "PageFooter": "#9333ea",
    "Footnote": "#64748b",
}
OTHER_COLOUR = "#db2777"


def _alto_blocks(path: Path, image_width: int) -> list[dict]:
    root = ET.parse(path).getroot()

    def local(el: ET.Element) -> str:
        return el.tag.rsplit("}", 1)[-1]

    page = next(el for el in root.iter() if local(el) == "Page")
    scale = image_width / float(page.get("WIDTH"))
    blocks = []
    for el in root.iter():
        if local(el) != "TextBlock":
            continue
        words = [s.get("CONTENT", "") for s in el.iter() if local(s) == "String"]
        x, y, w, h = (float(el.get(k)) * scale for k in ("HPOS", "VPOS", "WIDTH", "HEIGHT"))
        blocks.append({"bbox": [x, y, x + w, y + h], "text": " ".join(words)[:200]})
    return blocks


def build(run_id: str) -> Path:
    rd = run_dir(run_id)
    layout_dir = rd / "01_layout"
    caches = sorted(layout_dir.glob("page*.layout.json"), key=lambda p: int(re.search(r"\d+", p.name).group()))
    if not caches:
        raise SystemExit(f"no layout output in {layout_dir} -- run the layout job first")

    doc = pymupdf.open(str(rd / "00_source.pdf"))
    images_dir = rd / IMAGES_DIR_NAME
    images_dir.mkdir(exist_ok=True)
    pages = []
    for cache_path in caches:
        n = int(re.search(r"\d+", cache_path.name).group())
        cache = load_region_cache(cache_path)
        # Region bboxes are pixels of the render the model saw.
        image = render_page_image(doc[n - 1], dpi=round(cache.dpi))
        image_path = images_dir / f"page{n}.jpg"
        image.save(image_path, quality=80)
        width, height = image.size
        alto = rd / PAGE_TEXT_DIR_NAME / f"page{n}.xml"
        pages.append(
            {
                "page": n,
                "image": image_path.relative_to(rd).as_posix(),
                "width": width,
                "height": height,
                "regions": [
                    {"position": r.position, "label": r.label, "bbox": [r.bbox.x0, r.bbox.y0, r.bbox.x1, r.bbox.y1]}
                    for r in cache.regions
                ],
                "alto": _alto_blocks(alto, width) if alto.exists() else None,
            }
        )

    out = rd / OUT_NAME
    out.write_text(
        TEMPLATE.replace("__TITLE__", html.escape(run_id))
        .replace("__DATA__", json.dumps(pages).replace("</", "<\\/"))
        .replace("__COLOURS__", json.dumps(LABEL_COLOURS))
        .replace("__OTHER__", OTHER_COLOUR),
        encoding="utf-8",
    )
    return out


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ -- layout</title>
<style>
  body { font: 14px system-ui, sans-serif; margin: 0; background: #f4f4f5; color: #18181b; }
  header { position: sticky; top: 0; z-index: 2; background: #fff; border-bottom: 1px solid #ddd;
           padding: 8px 16px; display: flex; flex-wrap: wrap; gap: 16px; align-items: center; }
  header h1 { font-size: 15px; margin: 0; }
  .legend span { display: inline-block; margin-right: 10px; }
  .legend i { display: inline-block; width: 10px; height: 10px; margin-right: 4px; vertical-align: -1px; }
  section { margin: 16px auto; max-width: 1100px; padding: 0 16px; }
  section h2 { font-size: 14px; margin: 0 0 6px; }
  .page { position: relative; }
  .page img { width: 100%; height: auto; display: block; }
  .page svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  rect { fill-opacity: .08; stroke-width: 3; }
  rect:hover { fill-opacity: .25; }
  text { font: bold 28px system-ui, sans-serif; paint-order: stroke; stroke: #fff; stroke-width: 6px; }
  .alto rect { stroke: #111; stroke-dasharray: 10 6; fill: #111; fill-opacity: .04; }
  body:not(.show-regions) .regions, body:not(.show-alto) .alto, body:not(.show-numbers) .regions text { display: none; }
</style></head>
<body class="show-regions show-numbers">
<header>
  <h1>__TITLE__</h1>
  <label><input type="checkbox" data-layer="regions" checked> layout regions</label>
  <label><input type="checkbox" data-layer="numbers" checked> reading order</label>
  <label><input type="checkbox" data-layer="alto"> ALTO blocks (dashed)</label>
  <select id="jump" aria-label="Jump to page"></select>
  <div class="legend" id="legend"></div>
</header>
<main id="pages"></main>
<script>
const PAGES = __DATA__, COLOURS = __COLOURS__, OTHER = "__OTHER__";
const esc = s => s.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const rect = ([x0, y0, x1, y1], attrs, title) =>
  `<rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" ${attrs}><title>${esc(title)}</title></rect>`;
const labels = new Set();
document.getElementById("pages").innerHTML = PAGES.map(p => {
  const regions = p.regions.map(r => {
    labels.add(r.label);
    const c = COLOURS[r.label] || OTHER;
    return rect(r.bbox, `stroke="${c}" fill="${c}"`, `#${r.position} ${r.label}`) +
      `<text x="${r.bbox[0] + 6}" y="${r.bbox[1] + 30}" fill="${c}">${r.position}</text>`;
  }).join("");
  const alto = (p.alto || []).map(b => rect(b.bbox, "", b.text)).join("");
  const counts = `${p.regions.length} regions` + (p.alto ? `, ${p.alto.length} ALTO blocks` : "");
  return `<section id="p${p.page}"><h2>Page ${p.page} <small>(${counts})</small></h2><div class="page">
    <img src="${p.image}" width="${p.width}" height="${p.height}" loading="lazy" alt="Page ${p.page}">
    <svg viewBox="0 0 ${p.width} ${p.height}">
      <g class="alto">${alto}</g><g class="regions">${regions}</g>
    </svg></div></section>`;
}).join("");
document.getElementById("legend").innerHTML = [...labels].sort()
  .map(l => `<span><i style="background:${COLOURS[l] || OTHER}"></i>${esc(l)}</span>`).join("");
const jump = document.getElementById("jump");
jump.innerHTML = PAGES.map(p => `<option value="p${p.page}">Page ${p.page}</option>`).join("");
jump.onchange = () => document.getElementById(jump.value).scrollIntoView();
document.querySelectorAll("[data-layer]").forEach(cb =>
  cb.onchange = () => document.body.classList.toggle("show-" + cb.dataset.layer, cb.checked));
if (!PAGES.some(p => p.alto)) document.querySelector('[data-layer="alto"]').parentElement.remove();
</script>
</body></html>
"""


if __name__ == "__main__":
    print(f"Wrote {build(run_id_from_args())}")
