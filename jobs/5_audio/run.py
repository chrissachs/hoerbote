"""Audio job: every narration segment of a published issue -> one Ogg Opus
take in 05_audio/, listed in audio.json. The speech engine renders
(speech_engine.py); this file decides what to render and keeps the takes."""

import logging
from pathlib import Path

from dotenv import load_dotenv

from audio import AUDIO_DIR_NAME, MANIFEST_FILE_NAME, STEP_NAME, AudioManifest, AudioSegment, text_hash
from pipeline_run import run_dir, run_id_from_args, step
from published import PublishedIssue, PublishedPage, PublishedSegment
from speech_engine import Request, SpeechEngine, configure_logging, make_engine

# From this job's own folder, not the repo root or CWD, and before an
# engine exists: the clients read their keys only when created.
load_dotenv(Path(__file__).parent / ".env")

TAKE_SUFFIX = ".ogg"

log = logging.getLogger(__name__)


def published_segments(rd: Path) -> list[tuple[int, PublishedSegment]]:
    """(page, segment) of every segment of the issue, in play order."""
    published_dir = rd / "04_published"
    issue = PublishedIssue.model_validate_json((published_dir / "issue.json").read_text(encoding="utf-8"))
    segments = []
    for entry in issue.pages:
        if entry.segment_count:
            page = PublishedPage.model_validate_json(
                (published_dir / f"page{entry.page}.json").read_text(encoding="utf-8")
            )
            segments += [(entry.page, segment) for segment in page.segments]
    return segments


def take_path(rd: Path, page: int, segment: PublishedSegment, engine: SpeechEngine) -> Path:
    # Named after the fingerprint, so a re-run renders only what changed.
    name = f"segment{segment.index}-{engine.fingerprint(segment.sentences, engine.voice_for(segment.index))}"
    return rd / AUDIO_DIR_NAME / f"page{page}" / f"{name}{TAKE_SUFFIX}"


def _save(path: Path, audio: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename, so a crash mid-write never leaves a truncated file
    # that a re-run takes for a finished take.
    tmp = path.with_suffix(f"{TAKE_SUFFIX}.tmp")
    tmp.write_bytes(audio)
    tmp.replace(path)


def _render_pending(engine: SpeechEngine, pending: dict[str, tuple[Path, Request]]) -> int:
    """Renders `pending` (key -> (take path, request)), saving each take as
    it comes. Returns how many failed."""
    left = dict(pending)
    failed = []
    for key, result in engine.render({key: request for key, (_, request) in pending.items()}):
        if key not in left:
            continue
        path, _ = left.pop(key)
        if isinstance(result, Exception):
            failed.append((key, result))
        else:
            _save(path, result)
    failed += [(key, "no response") for key in left]
    for key, error in failed:
        log.error("%s: failed -- %r", key, error)
    return len(failed)


def render(rd: Path, engine: SpeechEngine) -> int:
    """Renders every segment without a take, then rewrites the manifest
    (rendered segments only) and deletes takes it no longer lists. Returns
    how many segments have no take."""
    takes = [(page, segment, take_path(rd, page, segment, engine)) for page, segment in published_segments(rd)]
    pending = {
        f"page{page}-segment{segment.index}": (path, Request(segment.sentences, engine.voice_for(segment.index)))
        for page, segment, path in takes
        if not path.is_file()
    }
    log.info("%d segments, %d already rendered", len(takes), len(takes) - len(pending))
    failed = _render_pending(engine, pending) if pending else 0

    manifest = AudioManifest(
        segments=[
            AudioSegment(
                page=page, index=segment.index, text_hash=text_hash(segment.sentences), file=str(path.relative_to(rd))
            )
            for page, segment, path in takes
            if path.is_file()
        ]
    )
    out_dir = rd / AUDIO_DIR_NAME
    out_dir.mkdir(exist_ok=True)
    tmp = out_dir / f"{MANIFEST_FILE_NAME}.tmp"
    tmp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(out_dir / MANIFEST_FILE_NAME)
    listed = {rd / s.file for s in manifest.segments}
    # Any audio file, so takes in an earlier format (or another engine's) go too.
    for old in out_dir.glob("page*/segment*.*"):
        if old not in listed:
            old.unlink()
    log.info("Done. %d of %d segments rendered to %s", len(manifest.segments), len(takes), out_dir)
    return failed


def run(run_id: str, engine: SpeechEngine | None = None) -> None:
    rd = run_dir(run_id)
    published = rd / "04_published"
    if not (published / "issue.json").is_file():
        raise FileNotFoundError(f"missing {published} -- the publish job must complete for this run first.")
    with step(run_id, STEP_NAME, input_path=str(published)) as s:
        # The segments that did render are in the manifest either way; a
        # re-run renders only the rest.
        if failed := render(rd, engine or make_engine(rd)):
            raise RuntimeError(f"{failed} segments failed to render -- re-run to render just those")
        s.finish(str(rd / AUDIO_DIR_NAME))


if __name__ == "__main__":
    configure_logging()
    run(run_id_from_args())
