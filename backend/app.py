"""Serves the published issues (04_published/), page images, segment audio
and the frontend build.

Without a login (access.py), only issues whose 00_source.json says the
rights are open are visible -- the others are 404, so their existence
doesn't leak. Logged in, everything is, and only then can audio and new
issues be asked for: the backend renders and fetches nothing itself, the
runner starts the jobs (audio_state.py, import_state.py).

Published JSON is read from disk per request -- the files are small, and
a pipeline re-run shows up without a restart.

Run from the repo root (DATA_ROOT defaults to ./data):
    ACCESS_PASSWORD=... uv run --project backend uvicorn app:app --port 8001"""

import datetime
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import audio_state
import import_state
from access import PUBLIC_PATHS, Access
from audio_state import AudioState
from import_state import ImportState, PaperOption
from papers import load_papers
from pipeline_run import data_root, run_dir
from published import PublishedIssue, PublishedPage, PublishedSegment
from source_info import SOURCE_INFO_FILE_NAME, SourceInfo

# From the backend's own folder (ACCESS_PASSWORD for local runs), same
# convention as the jobs.
load_dotenv(Path(__file__).parent / ".env")

log = logging.getLogger(__name__)

PUBLISHED_DIR_NAME = "04_published"
# The React build (frontend: `npm run build`). Read once at
# startup -- restart the backend after a rebuild. In dev, Vite's own
# server serves the frontend instead and proxies /api here.
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR", Path(__file__).parent.parent / "frontend" / "dist"))
# Page images and segment audio only change when a pipeline stage is
# re-run, and a prefetch should fill the browser cache for the real
# request.
CONTENT_CACHE_HEADERS = {"Cache-Control": "private, max-age=86400"}
# run_ids are `<paper>-<edition>-<date>`;
# anything with a dot or slash never reaches the filesystem.
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class LoginRequest(BaseModel):
    password: str


class Session(BaseModel):
    logged_in: bool


class ImportForm(BaseModel):
    paper: str
    date: datetime.date


class Imports(BaseModel):
    # The papers that can be imported (config/papers.toml).
    papers: list[PaperOption]
    imports: list[ImportState]


class IssueSummary(BaseModel):
    """One line of the issue list: enough to group by paper and sort by date."""

    run_id: str
    paper: str
    paper_title: str
    edition: str
    date: datetime.date


def _visible(request: Request, rd: Path) -> bool:
    """Logged in: every run fetch made (it writes 00_source.json; anything
    else in issues/ isn't a run). Anonymous: only those whose source says
    they may be shown publicly."""
    path = rd / SOURCE_INFO_FILE_NAME
    if not path.is_file():
        return False
    return request.state.logged_in or SourceInfo.model_validate_json(path.read_text()).rights.open


def _check_issue(request: Request) -> None:
    """Every issue route's guard (a router dependency, so a new route gets
    it too): 404 for a run that isn't published, or that this visitor may
    not see."""
    run_id = request.path_params.get("run_id")
    if run_id is None:
        return
    if not RUN_ID_PATTERN.match(run_id):
        raise HTTPException(404, "no such issue")
    rd = run_dir(run_id)
    if not (rd / PUBLISHED_DIR_NAME / "issue.json").is_file() or not _visible(request, rd):
        raise HTTPException(404, "no such issue")


def _published_dir(run_id: str) -> Path:
    # Only called from routes behind _check_issue.
    return run_dir(run_id) / PUBLISHED_DIR_NAME


def _load_page(run_id: str, page: int) -> PublishedPage:
    path = _published_dir(run_id) / f"page{page}.json"
    if not path.is_file():
        raise HTTPException(404, "no such page")
    return PublishedPage.model_validate_json(path.read_text(encoding="utf-8"))


def _shell_paths(frontend_dir: Path) -> set[str]:
    """Every file of the frontend build as an exact public path, so the
    allowlist stays exact-match (no prefixes) -- see access.py."""
    if not frontend_dir.is_dir():
        return set()
    files = (p for p in frontend_dir.rglob("*") if p.is_file())
    return {"/"} | {"/" + p.relative_to(frontend_dir).as_posix() for p in files}


def create_app(password: str, frontend_dir: Path = FRONTEND_DIR) -> FastAPI:
    access = Access(password, public_paths=PUBLIC_PATHS | _shell_paths(frontend_dir))
    # Interactive API docs at /api/docs (public, see access.PUBLIC_PATHS).
    app = FastAPI(title="hoerbote", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.middleware("http")(access.middleware)

    # Added last, so it runs outermost: 401s get the header too.
    @app.middleware("http")
    async def no_index(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
    def robots() -> str:
        return "User-agent: *\nDisallow: /\n"

    @app.post("/api/login", status_code=204)
    def login(body: LoginRequest, response: Response) -> None:
        """Checks the shared password and sets the session cookie that every
        other route needs."""
        if not access.password_matches(body.password):
            raise HTTPException(401, "wrong password")
        access.issue(response)

    @app.post("/api/logout", status_code=204)
    def logout(response: Response) -> None:
        access.forget(response)

    @app.get("/api/session")
    def session(request: Request) -> Session:
        """Whether this browser is logged in -- anonymous visitors see the
        openly licensed issues only."""
        return Session(logged_in=request.state.logged_in)

    app.include_router(_imports_router(), prefix="/api/imports")
    app.include_router(_issues_router(), prefix="/api/issues", dependencies=[Depends(_check_issue)])

    # Mounted last: the routes above take precedence over the catch-all.
    if frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        log.warning("no frontend build at %s -- serving the API only", frontend_dir)
    return app


def _imports_router() -> APIRouter:
    """Logged in only, reads too (access.py): not under /api/issues."""
    router = APIRouter()

    def check_paper(paper: str) -> None:
        if paper not in load_papers():
            raise HTTPException(422, f"unknown paper {paper!r}")

    @router.get("")
    def list_imports() -> Imports:
        """Which papers can be imported, and the imports asked for that
        aren't done yet or failed. A done one is gone: its issue is listed."""
        return Imports(papers=import_state.papers(), imports=import_state.list_imports())

    @router.post("", status_code=202)
    def request_import(body: ImportForm) -> ImportState:
        """Asks for an issue: the runner starts fetch and every job up to
        publish within a minute (~10 min). A no-op while it's on its way."""
        check_paper(body.paper)
        return import_state.request(body.paper, body.date)

    @router.delete("/{paper}/{date}", status_code=204)
    def dismiss_import(paper: str, date: datetime.date) -> None:
        """Forgets a failed import."""
        check_paper(paper)
        import_state.dismiss(paper, date)

    return router


def _issues_router() -> APIRouter:
    router = APIRouter()

    @router.get("")
    def list_issues(request: Request) -> list[IssueSummary]:
        """Every published issue this visitor may see, latest first."""
        issues_dir = data_root() / "issues"
        if not issues_dir.is_dir():
            return []
        summaries = []
        for d in issues_dir.iterdir():
            path = d / PUBLISHED_DIR_NAME / "issue.json"
            if RUN_ID_PATTERN.match(d.name) and path.is_file() and _visible(request, d):
                issue = PublishedIssue.model_validate_json(path.read_text(encoding="utf-8"))
                summaries.append(IssueSummary(**issue.model_dump(exclude={"pages", "attribution"})))
        return sorted(summaries, key=lambda s: (s.date, s.run_id), reverse=True)

    @router.get("/{run_id}")
    def get_issue(run_id: str) -> PublishedIssue:
        """The issue's index: paper, date, attribution, and per page its
        aspect ratio and segment count."""
        return PublishedIssue.model_validate_json((_published_dir(run_id) / "issue.json").read_text(encoding="utf-8"))

    @router.get("/{run_id}/pages/{page}")
    def get_page(run_id: str, page: int) -> dict:
        """One page: its articles (bounding boxes as page fractions) and
        narration segments, in play order."""
        # The image paths are backend-only; the frontend uses the image routes.
        return _load_page(run_id, page).model_dump(mode="json", exclude={"image", "thumbnail"})

    @router.get("/{run_id}/pages/{page}/image")
    def get_page_image(run_id: str, page: int) -> FileResponse:
        """The page as an image (WebP), 2400 px wide."""
        path = run_dir(run_id) / _load_page(run_id, page).image
        if not path.is_file():
            raise HTTPException(404, "page image missing")
        return FileResponse(path, headers=CONTENT_CACHE_HEADERS)

    @router.get("/{run_id}/pages/{page}/thumbnail")
    def get_page_thumbnail(run_id: str, page: int) -> FileResponse:
        """The page as a small image (WebP), 360 px wide."""
        thumbnail = _load_page(run_id, page).thumbnail
        path = run_dir(run_id) / thumbnail if thumbnail else None
        if path is None or not path.is_file():
            raise HTTPException(404, "page thumbnail missing")
        return FileResponse(path, headers=CONTENT_CACHE_HEADERS)

    def find_segment(run_id: str, page: int, segment: int) -> PublishedSegment:
        match = next((s for s in _load_page(run_id, page).segments if s.index == segment), None)
        if match is None:
            raise HTTPException(404, "no such segment")
        return match

    @router.get("/{run_id}/pages/{page}/segments/{segment}/audio")
    def get_segment_audio(run_id: str, page: int, segment: int) -> FileResponse:
        """One narration segment as Ogg Opus, once the issue's audio is rendered
        (see the audio route)."""
        path = audio_state.take_for(run_dir(run_id), page, find_segment(run_id, page, segment))
        if path is None:
            raise HTTPException(404, "audio not rendered")
        # Content type from the extension (.ogg: audio/ogg).
        return FileResponse(path, headers=CONTENT_CACHE_HEADERS)

    @router.get("/{run_id}/audio")
    def get_audio_state(run_id: str) -> AudioState:
        """Whether the issue's audio is rendered, asked for, or on its way."""
        return audio_state.state(run_dir(run_id))

    @router.post("/{run_id}/audio", status_code=202)
    def request_audio(run_id: str) -> AudioState:
        """Asks for the issue's audio (logged in only): the runner starts the
        audio job within a minute, which takes ~3 min. A no-op if it's
        ready or already on its way."""
        return audio_state.request(run_dir(run_id))

    return router


def __getattr__(name: str):
    # `uvicorn app:app` builds the app lazily, so importing this module
    # (e.g. in tests) doesn't require ACCESS_PASSWORD.
    if name == "app":
        return create_app(os.environ.get("ACCESS_PASSWORD", ""))
    raise AttributeError(name)
