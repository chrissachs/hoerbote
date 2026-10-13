"""Segment audio as the audio job rendered it (05_audio/audio.json, see
shared/audio.py). The backend renders nothing itself: asking for an
issue's audio writes a request file, the runner picks it up within a
minute and starts the audio job (~3 min for a whole issue).

A take only counts while its text hash matches the published segment, so
after a narration or publish re-run the issue's audio is "none" again
instead of reading out the old text."""

import datetime
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from audio import AUDIO_DIR_NAME, MANIFEST_FILE_NAME, REQUEST_FILE_NAME, STEP_NAME, AudioManifest, text_hash
from published import PublishedIssue, PublishedPage, PublishedSegment

# none: no (current) audio and nobody asked; requested: waiting for the
# runner; rendering: the audio job runs; ready: every segment has a take;
# failed: the last audio job failed (some segments may still have takes).
AudioStatus = Literal["none", "requested", "rendering", "ready", "failed"]


class AudioState(BaseModel):
    status: AudioStatus
    # Segments with a current take, of all narrated segments.
    rendered: int
    total: int


def _manifest(run_dir: Path) -> dict[tuple[int, int], tuple[str, Path]]:
    """(page, segment index) -> (text hash, take path)."""
    path = run_dir / AUDIO_DIR_NAME / MANIFEST_FILE_NAME
    if not path.is_file():
        return {}
    manifest = AudioManifest.model_validate_json(path.read_text(encoding="utf-8"))
    return {(s.page, s.index): (s.text_hash, run_dir / s.file) for s in manifest.segments}


def take_for(run_dir: Path, page: int, segment: PublishedSegment) -> Path | None:
    """The segment's audio file, if the audio job rendered it from its current text."""
    hashed, path = _manifest(run_dir).get((page, segment.index), (None, None))
    return path if hashed == text_hash(segment.sentences) and path.is_file() else None


def _step_status(run_dir: Path) -> str | None:
    path = run_dir / "status.json"
    steps = json.loads(path.read_text()).get("steps", []) if path.is_file() else []
    return next((s["status"] for s in steps if s["name"] == STEP_NAME), None)


def state(run_dir: Path) -> AudioState:
    published_dir = run_dir / "04_published"
    issue = PublishedIssue.model_validate_json((published_dir / "issue.json").read_text(encoding="utf-8"))
    manifest = _manifest(run_dir)
    total = rendered = 0
    for entry in issue.pages:
        if not entry.segment_count:
            continue
        page = PublishedPage.model_validate_json((published_dir / f"page{entry.page}.json").read_text(encoding="utf-8"))
        for segment in page.segments:
            total += 1
            hashed, path = manifest.get((entry.page, segment.index), (None, None))
            rendered += hashed == text_hash(segment.sentences) and path.is_file()
    step = _step_status(run_dir)
    # The runner deletes the request file only once the job is over.
    if step == "running":
        status = "rendering"
    elif (run_dir / REQUEST_FILE_NAME).is_file():
        status = "requested"
    elif rendered == total:
        status = "ready"
    elif step == "failed":
        status = "failed"
    else:
        status = "none"
    return AudioState(status=status, rendered=rendered, total=total)


def request(run_dir: Path) -> AudioState:
    """Asks the runner for the issue's audio, unless it's ready or already
    on its way."""
    current = state(run_dir)
    if current.status in ("requested", "rendering", "ready"):
        return current
    (run_dir / REQUEST_FILE_NAME).write_text(datetime.datetime.now(datetime.UTC).isoformat() + "\n")
    return current.model_copy(update={"status": "requested"})
