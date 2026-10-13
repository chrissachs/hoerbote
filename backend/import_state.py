"""Issue imports asked for in the web app (shared/import_request.py). The
backend imports nothing itself: asking writes a request file, the runner
picks it up within a minute and runs fetch and every job up to publish
(~10 min), which costs money -- hence logged in only, and no daily cron.
Any paper in config/papers.toml (shared/papers.py) can be asked for."""

import datetime
import json
from pathlib import Path

from pydantic import BaseModel, ValidationError

from import_request import REQUESTS_DIR_NAME, ImportRequest, ImportStatus, file_stem
from papers import load_papers
from pipeline_run import data_root, run_dir


class ImportState(BaseModel):
    paper: str
    date: datetime.date
    status: ImportStatus
    run_id: str | None
    # While running: the job at work, once fetch has a run_id.
    step: str | None
    error: str | None


class PaperOption(BaseModel):
    """A paper in the import form."""

    slug: str
    title: str
    # The paper's default issue date, today (e.g. 100 years ago today).
    default_date: datetime.date


def papers() -> list[PaperOption]:
    return [PaperOption(slug=p.slug, title=p.title, default_date=p.default_date()) for p in load_papers().values()]


def _requests_dir() -> Path:
    return data_root() / REQUESTS_DIR_NAME


def _running_step(run_id: str) -> str | None:
    path = run_dir(run_id) / "status.json"
    try:
        steps = json.loads(path.read_text()).get("steps", []) if path.is_file() else []
    except json.JSONDecodeError:  # caught mid-write
        return None
    return next((s["name"] for s in steps if s["status"] == "running"), None)


def _load(path: Path) -> ImportState | None:
    try:
        request = ImportRequest.model_validate_json(path.read_text(encoding="utf-8"))
        status = ImportStatus(path.suffix.removeprefix("."))
    except FileNotFoundError, ValidationError, ValueError:  # gone, mid-write, or not ours
        return None
    step = _running_step(request.run_id) if status is ImportStatus.RUNNING and request.run_id else None
    return ImportState(**request.model_dump(include={"paper", "date", "run_id", "error"}), status=status, step=step)


def list_imports() -> list[ImportState]:
    """Every import asked for and not done yet (or failed), latest issue
    date first."""
    if not _requests_dir().is_dir():
        return []
    states = [s for path in _requests_dir().iterdir() if (s := _load(path)) is not None]
    return sorted(states, key=lambda s: (s.date, s.paper), reverse=True)


def request(paper: str, date: datetime.date) -> ImportState:
    """Asks the runner to import the issue, unless that's already on its
    way. Asking again after a failure replaces the failure. An issue that's
    already there is imported again only as far as it isn't (the runner
    continues the run), so asking for it costs nothing."""
    stem = file_stem(paper, date)
    for status in (ImportStatus.REQUESTED, ImportStatus.RUNNING):
        if (current := _load(_requests_dir() / f"{stem}.{status}")) is not None:
            return current
    _requests_dir().mkdir(parents=True, exist_ok=True)
    (_requests_dir() / f"{stem}.{ImportStatus.FAILED}").unlink(missing_ok=True)
    body = ImportRequest(paper=paper, date=date, requested_at=datetime.datetime.now(datetime.UTC))
    (_requests_dir() / f"{stem}.{ImportStatus.REQUESTED}").write_text(body.model_dump_json(), encoding="utf-8")
    return ImportState(paper=paper, date=date, status=ImportStatus.REQUESTED, run_id=None, step=None, error=None)


def dismiss(paper: str, date: datetime.date) -> None:
    """Forgets a failed import."""
    (_requests_dir() / f"{file_stem(paper, date)}.{ImportStatus.FAILED}").unlink(missing_ok=True)
