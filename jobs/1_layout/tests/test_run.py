"""run.py with a fake model and fake page renders: pages -> 01_layout/
caches + PNGs, retry at a lower DPI, unusable pages saved without regions
(a warning), too many of them failing the step."""

import json

import pymupdf
import pytest
from PIL import Image

import run
from layout_cache import LayoutRegion, load_region_cache
from models import BBox

RUN_ID = "paper-morning-1926-10-08"
DPI = 152
PAGES = 10


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    rd = tmp_path / "issues" / RUN_ID
    rd.mkdir(parents=True)
    doc = pymupdf.open()
    for _ in range(PAGES):
        doc.new_page()
    doc.save(rd / "00_source.pdf")

    def fake_render(page, dpi):
        image = Image.new("RGB", (4, 4))
        image.info.update(page=page.number + 1, dpi=dpi)
        return image

    monkeypatch.setattr(run, "render_page_image", fake_render)
    return rd


def _fake_model(monkeypatch, unusable: dict[int, set[int]]):
    """`unusable`: page -> the DPIs at which the model's output for it is
    unusable. Every other page gets one region tagged with its page."""
    calls = []

    def detect(images):
        (image,) = images
        page, dpi = image.info["page"], image.info["dpi"]
        calls.append((page, dpi))
        if dpi in unusable.get(page, set()):
            return [None]
        return [[LayoutRegion(position=0, label="Text", bbox=BBox(x0=page, y0=0, x1=page + 1, y1=1))]]

    monkeypatch.setattr(run, "detect_layouts", detect)
    return calls


def _status(rd) -> dict:
    return json.loads((rd / "status.json").read_text())


def test_every_page_cached(run_dir, monkeypatch):
    _fake_model(monkeypatch, {})
    run.run(RUN_ID, dpi=DPI)
    out = run_dir / "01_layout"
    for page in range(1, PAGES + 1):
        cache = load_region_cache(out / f"page{page}.layout.json")
        assert (cache.source_pdf, cache.dpi, cache.regions[0].bbox.x0) == ("00_source.pdf", DPI, page)
        assert not (out / f"page{page}.png").exists()
    assert _status(run_dir)["status"] == "succeeded"


def test_unusable_page_retried_at_lower_dpi(run_dir, monkeypatch):
    calls = _fake_model(monkeypatch, {3: {DPI}})
    run.run(RUN_ID, dpi=DPI)
    retry_dpi = DPI - run.RETRY_DPI_STEP
    assert (3, retry_dpi) in calls
    assert load_region_cache(run_dir / "01_layout" / "page3.layout.json").dpi == retry_dpi
    assert "warnings" not in _status(run_dir)["steps"][0]


def test_page_unusable_after_retry_saved_without_regions(run_dir, monkeypatch):
    _fake_model(monkeypatch, {3: {DPI, DPI - run.RETRY_DPI_STEP}})
    run.run(RUN_ID, dpi=DPI)
    assert load_region_cache(run_dir / "01_layout" / "page3.layout.json").regions == []
    status = _status(run_dir)
    assert status["status"] == "succeeded"
    assert status["steps"][0]["warnings"] == ["page 3: model output unusable after retry, saved without regions"]


def test_too_many_unusable_pages_fail_the_step(run_dir, monkeypatch):
    both = {DPI, DPI - run.RETRY_DPI_STEP}
    _fake_model(monkeypatch, {3: both, 7: both})  # 2 of 10 > MAX_UNUSABLE_SHARE
    with pytest.raises(RuntimeError, match="failed for 2/10 pages"):
        run.run(RUN_ID, dpi=DPI)
    assert _status(run_dir)["status"] == "failed"
    assert not (run_dir / "01_layout" / "page3.layout.json").exists()
