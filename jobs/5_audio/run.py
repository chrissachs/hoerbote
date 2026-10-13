"""Audio job: every narration segment of a published issue -> one Ogg Opus each
in 05_audio/, listed in 05_audio/audio.json (shared/audio.py), which is
what the backend serves.

Not part of an import: it costs money per issue (~$0.29 for a 29-page
issue at the 2026 price), so it runs when someone asks for an
issue's audio (the backend writes a request file, the runner starts this
job) or by hand.

One Gemini Batch API job for every segment without a take yet: half the
price of a call per segment, and not subject to the per-minute TTS limit
(10 requests/min on Tier 1) -- in exchange for a turnaround of ~2-3 min
(measured 2026-10-13), up to 24h in the worst case. Requests and
responses go through files, not inline: a full issue's audio is ~200 MB.

A take is named after its fingerprint (speech.py), so a re-run renders
only what's missing or changed: a failed segment, new narration text, a
new voice. The batch job's name is kept in 05_audio/batch_job.json while
waiting, so an interrupted run resumes polling that job instead of paying
for a second one.

Needs GEMINI_API_KEY (this folder's .env, or `docker run --env-file`)."""

import hashlib
import json
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from audio import AUDIO_DIR_NAME, MANIFEST_FILE_NAME, STEP_NAME, AudioManifest, AudioSegment, text_hash
from pipeline_run import run_dir, run_id_from_args, step
from published import PublishedIssue, PublishedPage, PublishedSegment
from speech import MODEL_ID, audio_from_batch_response, batch_request, fingerprint, style_for, voice_for

# From this job's own folder, not the repo root or CWD. google-genai only
# reads GEMINI_API_KEY when a client is created.
load_dotenv(Path(__file__).parent / ".env")

POLL_SECONDS = 30
TAKE_SUFFIX = ".ogg"
JOB_FILE_NAME = "batch_job.json"
_DONE_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}
_FAILED_STATES = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


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


def take_path(rd: Path, page: int, segment: PublishedSegment, style: str) -> Path:
    text = " ".join(segment.sentences)
    name = f"segment{segment.index}-{fingerprint(text, voice_for(segment.index), style)}{TAKE_SUFFIX}"
    return rd / AUDIO_DIR_NAME / f"page{page}" / name


def _save(path: Path, audio: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename, so a crash mid-write never leaves a truncated file
    # that a re-run takes for a finished take.
    tmp = path.with_suffix(f"{TAKE_SUFFIX}.tmp")
    tmp.write_bytes(audio)
    tmp.replace(path)


def _submit_or_resume(client: genai.Client, rd: Path, lines: list[dict]) -> str:
    job_file = rd / AUDIO_DIR_NAME / JOB_FILE_NAME
    job_fingerprint = hashlib.sha256(json.dumps([MODEL_ID, lines], sort_keys=True).encode()).hexdigest()[:12]
    if job_file.is_file():
        saved = json.loads(job_file.read_text())
        if saved["fingerprint"] == job_fingerprint:
            state = client.batches.get(name=saved["job"]).state.name
            if state not in _FAILED_STATES:
                print(f"Resuming batch job {saved['job']} ({state})")
                return saved["job"]
    display_name = f"hoerbote audio {rd.name}"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "requests.jsonl"
        src.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
        uploaded = client.files.upload(file=src, config={"display_name": display_name, "mime_type": "jsonl"})
    job = client.batches.create(model=MODEL_ID, src=uploaded.name, config={"display_name": display_name})
    job_file.parent.mkdir(parents=True, exist_ok=True)
    job_file.write_text(json.dumps({"job": job.name, "fingerprint": job_fingerprint}))
    print(f"Submitted batch job {job.name} ({len(lines)} segments)")
    return job.name


def _render_batch(client: genai.Client, rd: Path, pending: dict[str, tuple[Path, PublishedSegment]], style: str) -> int:
    """Renders `pending` (batch key -> (take path, segment)) in one batch
    job. Returns how many failed."""
    lines = [
        {"key": key, "request": batch_request(" ".join(segment.sentences), voice_for(segment.index), style)}
        for key, (_, segment) in pending.items()
    ]
    job_name = _submit_or_resume(client, rd, lines)
    while True:
        job = client.batches.get(name=job_name)
        state = job.state.name
        if state in _DONE_STATES:
            break
        if state in _FAILED_STATES:
            (rd / AUDIO_DIR_NAME / JOB_FILE_NAME).unlink(missing_ok=True)
            raise RuntimeError(f"batch job {job_name} ended in {state}: {job.error}")
        print(f"Batch job {state}, waiting {POLL_SECONDS}s...", flush=True)
        time.sleep(POLL_SECONDS)

    left = dict(pending)
    failed = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "responses.jsonl"
        client.files.download(file=job.dest.file_name, destination=out)
        # Line by line: each holds a whole segment's audio.
        with out.open(encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                if item.get("key") not in left:
                    continue
                path, _ = left.pop(item["key"])
                try:
                    if "error" in item:
                        raise RuntimeError(item["error"])
                    _save(path, audio_from_batch_response(item["response"]))
                except Exception as e:  # one bad item mustn't lose the others' audio
                    failed.append((item["key"], e))
    failed += [(key, "no response") for key in left]
    (rd / AUDIO_DIR_NAME / JOB_FILE_NAME).unlink(missing_ok=True)
    for key, error in failed:
        print(f"  {key}: FAILED -- {error!r}")
    return len(failed)


def render(rd: Path, client: genai.Client | None = None) -> int:
    """Renders every segment without a take, then rewrites the manifest
    (rendered segments only) and deletes takes it no longer lists. Returns
    how many segments have no take."""
    style = style_for(rd)
    takes = [(page, segment, take_path(rd, page, segment, style)) for page, segment in published_segments(rd)]
    pending = {
        f"page{page}-segment{segment.index}": (path, segment) for page, segment, path in takes if not path.is_file()
    }
    print(f"{len(takes)} segments, {len(takes) - len(pending)} already rendered")
    failed = _render_batch(client or genai.Client(), rd, pending, style) if pending else 0

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
    # Any audio file, so takes in an earlier format go too.
    for old in out_dir.glob("page*/segment*.*"):
        if old not in listed:
            old.unlink()
    print(f"Done. {len(manifest.segments)} of {len(takes)} segments rendered to {out_dir}")
    return failed


def run(run_id: str, client: genai.Client | None = None) -> None:
    rd = run_dir(run_id)
    published = rd / "04_published"
    if not (published / "issue.json").is_file():
        raise FileNotFoundError(f"missing {published} -- the publish job must complete for this run first.")
    with step(run_id, STEP_NAME, input_path=str(published)) as s:
        # The segments that did render are in the manifest either way; a
        # re-run renders only the rest.
        if failed := render(rd, client):
            raise RuntimeError(f"{failed} segments failed to render -- re-run to render just those")
        s.finish(str(rd / AUDIO_DIR_NAME))


if __name__ == "__main__":
    run(run_id_from_args())
