"""Which papers can be fetched: config/papers.toml, plus the gitignored
config/papers_local.toml if there is one. The fetch job reads it to find
an issue, the backend to offer papers in the import form.

CONFIG_DIR defaults to ./config relative to the CWD (local runs from the
repo root, like DATA_ROOT); the Dockerfiles copy config/ and set it."""

import datetime
import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from source_info import NarrationContext

PAPERS_FILE_NAMES = ["papers.toml", "papers_local.toml"]


class Paper(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Part of the run_id; the key of the paper's table in the file.
    slug: str
    # How the import form names it. The ddb provider names the issue after
    # the archive's own title; the url provider uses this one.
    title: str
    provider: str
    # Default issue date is today minus this many years (100 for the
    # "100 years ago today" historic papers, 0 for a current paper).
    years_back: int
    # Our edition slug (part of the run_id) -> how the provider tells
    # editions apart; the first one is the default.
    editions: dict[str, str]
    # Provider-specific lookup keys.
    params: dict[str, str]
    # How the narration job narrates this paper (see source_info): how much
    # context it adds, its tone (a key of its TONES), and free-text tone
    # wording, e.g. "an occasional regional word is welcome".
    narration_context: NarrationContext = "none"
    narration_tone: str | None = None
    tone_prompt: str | None = None
    # How the TTS voices speak (see source_info), e.g. "a faint regional
    # accent"; None: neutral.
    speech_style: str | None = None

    def default_date(self, today: datetime.date | None = None) -> datetime.date:
        today = today or datetime.date.today()
        try:
            return today.replace(year=today.year - self.years_back)
        except ValueError:  # 29 February in a non-leap target year
            return today.replace(year=today.year - self.years_back, day=28)


def config_dir() -> Path:
    return Path(os.environ.get("CONFIG_DIR", "./config"))


def load_papers(directory: Path | None = None) -> dict[str, Paper]:
    """Every paper by slug, the local file's added (and winning on a
    clash). Read per call: a few lines of TOML."""
    papers: dict[str, Paper] = {}
    for name in PAPERS_FILE_NAMES:
        path = (directory or config_dir()) / name
        if path.is_file():
            tables = tomllib.loads(path.read_text(encoding="utf-8"))
            papers |= {slug: Paper(slug=slug, **fields) for slug, fields in tables.items()}
    return papers
