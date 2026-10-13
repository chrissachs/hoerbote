"""Renders every page{N}.narration.json already written for a run as one
continuous HTML reading view, in page order -- for reading through the
actual production output. Run run.py first so there's something to read.

    uv run --project jobs/3_narration python jobs/3_narration/render_narration.py <run_id>
"""

import html
from pathlib import Path

from narration import PageSummary
from pipeline import load_all_narrations
from pipeline_run import run_dir, run_id_from_args


class NarrationReadthrough:
    """Consecutive sentences on the same article_idx are grouped into one
    paragraph (real narration flows across sentence boundaries; showing a
    ref on every single sentence would break that up for no reason) -- the
    ref marks where each group starts, not each sentence."""

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._pages: list[PageSummary] = []

    def add_page(self, page_summary: PageSummary) -> None:
        self._pages.append(page_summary)

    def _render_page(self, page_summary: PageSummary) -> str:
        groups: list[tuple[int, list[str]]] = []
        for s in page_summary.sentences:
            if groups and groups[-1][0] == s.article_idx:
                groups[-1][1].append(s.sentence)
            else:
                groups.append((s.article_idx, [s.sentence]))
        paragraphs = "\n".join(
            f'<p><span class="ref">[{idx}]</span> {html.escape(" ".join(sentences))}</p>' for idx, sentences in groups
        )
        return f"""<section id="page{page_summary.page}">
<h1>Page {page_summary.page}</h1>
{paragraphs}
</section>
"""

    def render(self) -> str:
        nav = " · ".join(f'<a href="#page{p.page}">{p.page}</a>' for p in self._pages)
        body = "\n<hr>\n".join(self._render_page(p) for p in self._pages)
        tones = {p.tone for p in self._pages}
        tone_label = tones.pop() if len(tones) == 1 else "mixed"
        return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>{html.escape(self._run_id)} -- full narration</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; margin: 2rem auto; max-width: 700px;
    line-height: 1.6; padding: 0 1rem; }}
  h1 {{ font-family: sans-serif; font-size: 1.1rem; color: #555; border-bottom: 1px solid #ddd;
    padding-bottom: 0.3rem; }}
  .meta {{ font-family: sans-serif; color: #888; font-size: 0.85rem; }}
  .nav {{ font-family: sans-serif; font-size: 0.85rem; color: #888; margin: 0.5rem 0 2rem 0;
    position: sticky; top: 0; background: white; padding: 0.5rem 0; line-height: 1.8; }}
  .nav a {{ color: #557; text-decoration: none; margin-right: 0.3rem; }}
  .ref {{ font-family: sans-serif; font-size: 0.7rem; color: #aaa; vertical-align: super; }}
  hr {{ border: none; border-top: 1px solid #eee; margin: 2.5rem 0; }}
</style>
</head>
<body>
<p class="meta">Run {html.escape(self._run_id)} -- tone: {html.escape(tone_label)} -- {len(self._pages)} pages</p>
<div class="nav">{nav}</div>
{body}
</body>
</html>
"""

    def write(self, path: Path) -> None:
        path.write_text(self.render(), encoding="utf-8")
        print(f"Done. See {path}")


def main(run_id: str) -> None:
    pages = load_all_narrations(run_id)
    if not pages:
        raise SystemExit(f"No page*.narration.json found for run {run_id} -- run run.py first.")

    report = NarrationReadthrough(run_id)
    for page_summary in pages:
        report.add_page(page_summary)
    report.write(run_dir(run_id) / "03_rewritten_readthrough.html")


if __name__ == "__main__":
    main(run_id_from_args())
