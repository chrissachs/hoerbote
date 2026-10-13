"""Layout job: renders every page of a run's PDF and runs the layout model
on it -> 01_layout/pageN.layout.json. The renders themselves aren't kept:
nothing after this job needs them (debug_view.py renders its own).

Keeps as many pages on the model as the inference server has parallel
slots, starting the next as soon as one finishes. A page whose model output
is unusable is retried once at a lower DPI, then saved without regions (a
warning; the articles job falls back to its own geometry there) -- unless
more than MAX_UNUSABLE_SHARE of the pages fail, which fails the step."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pymupdf

from layout_cache import LAYOUT_RENDER_DPI, LayoutRegion, save_region_cache
from layout_model import CPU_SAFE_ENV, detect_layouts, max_pages_in_flight, render_page_image
from pipeline_run import run_dir, run_id_from_args, step

STEP_NAME = "layout"
RETRY_DPI_STEP = 8
# A few pages the model can't handle are saved without regions (a warning);
# more than this share of the issue means something systemic (e.g. the
# server returning garbage) and fails the step instead.
MAX_UNUSABLE_SHARE = 0.1


def run(run_id: str, dpi: int = LAYOUT_RENDER_DPI) -> None:
    rd = run_dir(run_id)
    source_pdf = rd / "00_source.pdf"
    out_dir = rd / "01_layout"

    if not source_pdf.exists():
        raise FileNotFoundError(f"missing {source_pdf}")

    for k, v in CPU_SAFE_ENV.items():
        os.environ.setdefault(k, v)

    with step(run_id, STEP_NAME, input_path=str(source_pdf)) as s:
        out_dir.mkdir(parents=True, exist_ok=True)
        doc = pymupdf.open(str(source_pdf))
        page_count = len(doc)
        writer = _PageWriter(out_dir, source_pdf.name)
        failed = _detect_pages(doc, list(range(1, page_count + 1)), dpi, writer)

        # At temperature 0 the same image gives the same unusable output,
        # so retry each failed page once from a slightly different render
        # (each cache records its own DPI).
        if failed:
            print(f"retrying page(s) {failed} at {dpi - RETRY_DPI_STEP} DPI")
            failed = _detect_pages(doc, failed, dpi - RETRY_DPI_STEP, writer)

        if len(failed) > MAX_UNUSABLE_SHARE * page_count:
            raise RuntimeError(
                f"layout detection failed for {len(failed)}/{page_count} pages {failed} (model output unusable)"
            )

        # Still unusable (e.g. a long list of dates the model loops on):
        # save the page without regions rather than fail the issue over it.
        for i in failed:
            writer.save(i, [], dpi)
            s.warn(f"page {i}: model output unusable after retry, saved without regions")
            print(f"page {i}: saved without regions (model output unusable after retry)")
        s.finish(str(out_dir))


def _detect_pages(doc: pymupdf.Document, pages: list[int], dpi: int, writer: _PageWriter) -> list[int]:
    """Detect layouts for `pages`, keeping max_pages_in_flight() of them on
    the model at once, and hand each page to `writer` as it finishes.
    Returns the pages whose model output was unusable (nothing saved)."""
    render_lock = threading.Lock()  # a pymupdf Document isn't safe to render from several threads

    def detect(i: int):
        with render_lock:
            image = render_page_image(doc[i - 1], dpi=dpi)
        return i, detect_layouts([image])[0]

    failed = []
    t_start = time.time()
    with ThreadPoolExecutor(max_pages_in_flight()) as pool:
        try:
            for done, future in enumerate(as_completed([pool.submit(detect, i) for i in pages]), start=1):
                i, regions = future.result()
                if regions is None:
                    writer.discard(i)
                    failed.append(i)
                    outcome = "unusable model output"
                else:
                    writer.save(i, regions, dpi)
                    outcome = f"{len(regions)} regions"
                avg = (time.time() - t_start) / done
                print(
                    f"[{done}/{len(pages)}] page {i}: {outcome} "
                    f"(avg {avg:.1f}s/page, ~{avg * (len(pages) - done) / 60:.1f}min remaining)"
                )
        except BaseException:
            # Don't start the remaining pages after an error (e.g. server gone).
            pool.shutdown(wait=False, cancel_futures=True)
            raise
    return failed


class _PageWriter:
    """Writes each page's layout cache as it finishes."""

    def __init__(self, out_dir: Path, source_pdf_name: str) -> None:
        self._out_dir = out_dir
        self._source_pdf_name = source_pdf_name

    def save(self, page: int, regions: list[LayoutRegion], dpi: int) -> None:
        save_region_cache(self._cache_path(page), regions, source_pdf=self._source_pdf_name, dpi=dpi)

    def discard(self, page: int) -> None:
        """Drops a cache an earlier run left for `page`."""
        self._cache_path(page).unlink(missing_ok=True)

    def _cache_path(self, page: int) -> Path:
        return self._out_dir / f"page{page}.layout.json"


if __name__ == "__main__":
    run(run_id_from_args(), dpi=int(os.environ.get("LAYOUT_RENDER_DPI", LAYOUT_RENDER_DPI)))
