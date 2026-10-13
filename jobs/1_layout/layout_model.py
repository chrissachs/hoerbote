"""The layout model (currently Surya 2's LayoutPredictor): page image ->
labeled regions. Purely visual; the articles job matches the regions onto
the page's text, and doesn't trust their reading order.

Without a GPU, Surya runs the model via llama.cpp on the CPU (slow)."""

import os

import pymupdf
from PIL import Image

from layout_cache import LAYOUT_RENDER_DPI, LayoutRegion
from models import BBox

# CPU defaults (run.py applies them unless set): keeps llama.cpp off the GPU
# -- on a machine with only an integrated GPU, its Vulkan backend crashed
# (ErrorDeviceLost) -- and one page on the model at a time.
CPU_SAFE_ENV = {
    "LLAMA_CPP_NGL": "0",
    "LLAMA_CPP_EXTRA_ARGS": "--device none --mmproj-device none",
    "SURYA_INFERENCE_PARALLEL": "1",
}


def render_page_image(page: pymupdf.Page, dpi: int = LAYOUT_RENDER_DPI) -> Image.Image:
    # Straight from the pixel buffer (RGB, no alpha by default); a PNG round
    # trip here cost ~0.3 s per page for identical pixels.
    pix = page.get_pixmap(dpi=dpi)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


_predictor = None


def _get_predictor():
    """Lazily construct one LayoutPredictor for the process. Surya's manager
    is itself a lazy module-level singleton, so repeated calls (even fresh
    LayoutPredictor() instances) reuse the same running inference server --
    this just avoids re-importing surya.layout until it's actually needed."""
    global _predictor
    if _predictor is None:
        from surya.layout import LayoutPredictor

        _predictor = LayoutPredictor()
    return _predictor


def max_pages_in_flight() -> int:
    """How many pages to have on the model at once: the inference server's
    parallel slots (SURYA_INFERENCE_PARALLEL). 1 on CPU (CPU_SAFE_ENV)."""
    return max(1, int(os.environ.get("SURYA_INFERENCE_PARALLEL", "1")))


def detect_layouts(images: list[Image.Image]) -> list[list[LayoutRegion] | None]:
    """Run the layout model on a batch of page images. Per image: regions
    sorted by reading-order position, or None if the model's output was
    unusable (e.g. cut off at the token limit, so not parseable). No PDF text
    or OCR involved -- purely visual region detection."""
    predictor = _get_predictor()
    return [
        None
        if result.error
        else sorted(
            (
                LayoutRegion(position=b.position, label=b.label, bbox=BBox.from_tuple(tuple(b.bbox)))
                for b in result.bboxes
            ),
            key=lambda r: r.position,
        )
        for result in predictor(images)
    ]
