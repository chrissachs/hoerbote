"""Fetch job: the one job that creates a run_id instead of taking one.

    run.py <paper> [--date YYYY-MM-DD] [--edition NAME] [--dry-run]

Writes data/issues/<paper>-<edition>-<date>/ (00_source.pdf, per-page text,
00_source.json) and prints the run_id as its last line. An issue whose rights statement
isn't open is still fetched, with a warning and rights.open = false."""

import argparse
import datetime
import logging

from ddb import DdbProvider
from papers import load_papers
from pipeline_run import run_dir, step
from provider import IssueNotFound, Provider
from source_info import SOURCE_INFO_FILE_NAME
from url import UrlProvider

STEP_NAME = "fetch"
PROVIDERS: dict[str, type[Provider]] = {"ddb": DdbProvider, "url": UrlProvider}

log = logging.getLogger(__name__)


def make_run_id(paper: str, edition: str, date: datetime.date) -> str:
    return f"{paper}-{edition}-{date.isoformat()}"


def run(
    paper_slug: str,
    date: datetime.date | None = None,
    edition: str | None = None,
    dry_run: bool = False,
    if_new: bool = False,
) -> str:
    """Fetches the issue and returns its run_id. `if_new`: do nothing (no
    network either) if the run dir already exists."""
    papers = load_papers()
    if paper_slug not in papers:
        raise SystemExit(f"unknown paper {paper_slug!r}; known: {', '.join(papers)}")
    paper = papers[paper_slug]
    edition = edition or next(iter(paper.editions))
    if edition not in paper.editions:
        raise SystemExit(f"unknown edition {edition!r} of {paper_slug}; known: {', '.join(paper.editions)}")
    date = date or paper.default_date()
    run_id = make_run_id(paper.slug, edition, date)
    if if_new and run_dir(run_id).exists():
        log.info("%s: already fetched, skipped", run_id)
        print(run_id)
        return run_id

    provider = PROVIDERS[paper.provider]()
    try:
        ref = provider.find(paper, edition, date)
    except IssueNotFound as e:
        raise SystemExit(str(e)) from e
    pages = f", {len(ref.text_urls)} pages" if ref.text_urls else ""
    log.info("%s: %s%s, item %s", run_id, ref.paper_title, pages, ref.item_id)
    log.info(
        "rights: %s (%s) -- %s", ref.rights.label, ref.rights.statement_url, "open" if ref.rights.open else "NOT open"
    )
    if dry_run:
        return run_id

    rd = run_dir(run_id)
    with step(run_id, STEP_NAME, input_path=ref.landing_url or ref.item_id) as s:
        if not ref.rights.open:
            s.warn(
                f"rights statement isn't open ({ref.rights.label}, {ref.rights.statement_url}) -- "
                "fine for a private run, must not be served publicly"
            )
        info = provider.download(ref, rd)
        (rd / SOURCE_INFO_FILE_NAME).write_text(info.model_dump_json(indent=2), encoding="utf-8")
        s.finish(str(rd))
    log.info("Done. Fetched into %s", rd)
    print(run_id)
    return run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch one newspaper issue into a new run dir.")
    parser.add_argument("paper", choices=sorted(load_papers()))
    parser.add_argument(
        "--date", type=datetime.date.fromisoformat, help="issue date (default: today minus the paper's years_back)"
    )
    parser.add_argument("--edition", help="default: the paper's first edition")
    parser.add_argument("--dry-run", action="store_true", help="look the issue up, download nothing")
    parser.add_argument("--if-new", action="store_true", help="skip an issue whose run dir already exists")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run(args.paper, args.date, args.edition, args.dry_run, args.if_new)
