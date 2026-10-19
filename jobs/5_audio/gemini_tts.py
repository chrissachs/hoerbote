"""The gemini engine: Gemini Flash-Lite TTS, a whole issue in one Batch API
job. batch_job.json lets an interrupted run resume that job instead of
paying for a second one."""

import base64
import hashlib
import io
import json
import logging
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import soundfile as sf
from google import genai

from audio import AUDIO_DIR_NAME
from source_info import SOURCE_INFO_FILE_NAME, SourceInfo
from speech_engine import Request, encode

# Flash-Lite TTS rather than Flash TTS: about a third cheaper per audio
# minute, same storyteller voices.
MODEL_ID = "gemini-3.8-flash-lite-tts"
# A paper can set its own (speech_style in config/papers.toml, via
# 00_source.json).
DEFAULT_STYLE = "Sprich klares, natürliches Hochdeutsch in ruhigem Erzähltempo."
# F, M, F, M -- a voice switch is how a listener hears the story change.
VOICE_POOL = [
    "de-de-storyteller-1",  # female
    "de-de-storyteller-8",  # male
    "de-de-storyteller-6",  # female
    "de-de-storyteller-2",  # male
]
JOB_FILE_NAME = "batch_job.json"
POLL_SECONDS = 30
_DONE_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}
_FAILED_STATES = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}

log = logging.getLogger(__name__)


def style_for(rd: Path) -> str:
    """The run's paper's speech style, else DEFAULT_STYLE."""
    return SourceInfo.model_validate_json((rd / SOURCE_INFO_FILE_NAME).read_text()).speech_style or DEFAULT_STYLE


def batch_request(text: str, voice: str, style: str) -> dict:
    """One segment's render, as one line of a Batch API input file (REST
    format). The style goes into speechMetadata: the TTS models read a
    style put in front of the text out loud, and reject a
    systemInstruction."""
    return {
        "contents": [{"role": "user", "parts": [{"text": text, "speechMetadata": {"style": style}}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }


def audio_from_batch_response(response: dict) -> bytes:
    """The audio of one Batch API output line's `response`, encoded."""
    wav = base64.b64decode(response["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
    samples, sample_rate = sf.read(io.BytesIO(wav))
    return encode(samples, sample_rate)


class GeminiEngine:
    def __init__(self, state_dir: Path, style: str = DEFAULT_STYLE, client: genai.Client | None = None) -> None:
        self.state_dir = state_dir  # where batch_job.json lives while waiting
        self.style = style
        self._client = client

    @classmethod
    def for_run(cls, rd: Path, client: genai.Client | None = None) -> GeminiEngine:
        return cls(rd / AUDIO_DIR_NAME, style_for(rd), client)

    @property
    def client(self) -> genai.Client:
        # Created on first use: google-genai reads GEMINI_API_KEY only then,
        # and a run with nothing to render needs no key.
        if self._client is None:
            self._client = genai.Client()
        return self._client

    def voice_for(self, segment_index: int) -> str:
        return VOICE_POOL[segment_index % len(VOICE_POOL)]

    def fingerprint(self, sentences: list[str], voice: str) -> str:
        # Keep as is: it names the takes already rendered.
        return hashlib.sha256("\n".join([MODEL_ID, voice, self.style, " ".join(sentences)]).encode()).hexdigest()[:12]

    def render(self, requests: dict[str, Request]) -> Iterator[tuple[str, bytes | Exception]]:
        lines = [
            {"key": key, "request": batch_request(" ".join(r.sentences), r.voice, self.style)}
            for key, r in requests.items()
        ]
        # Through files, not inline: a whole issue's audio is ~200 MB.
        job = self._wait(self._submit_or_resume(lines))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "responses.jsonl"
            self.client.files.download(file=job.dest.file_name, destination=out)
            # Line by line: each holds a whole segment's audio.
            with out.open(encoding="utf-8") as f:
                for line in f:
                    item = json.loads(line)
                    if item.get("key") not in requests:
                        continue
                    try:
                        if "error" in item:
                            raise RuntimeError(item["error"])
                        yield item["key"], audio_from_batch_response(item["response"])
                    except Exception as e:  # one bad item mustn't lose the others' audio
                        yield item["key"], e
        (self.state_dir / JOB_FILE_NAME).unlink(missing_ok=True)

    def _submit_or_resume(self, lines: list[dict]) -> str:
        job_file = self.state_dir / JOB_FILE_NAME
        job_fingerprint = hashlib.sha256(json.dumps([MODEL_ID, lines], sort_keys=True).encode()).hexdigest()[:12]
        if job_file.is_file():
            saved = json.loads(job_file.read_text())
            if saved["fingerprint"] == job_fingerprint:
                state = self.client.batches.get(name=saved["job"]).state.name
                if state not in _FAILED_STATES:
                    log.info("Resuming batch job %s (%s)", saved["job"], state)
                    return saved["job"]
        display_name = f"hoerbote audio {self.state_dir.parent.name}"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "requests.jsonl"
            src.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8")
            uploaded = self.client.files.upload(file=src, config={"display_name": display_name, "mime_type": "jsonl"})
        job = self.client.batches.create(model=MODEL_ID, src=uploaded.name, config={"display_name": display_name})
        job_file.parent.mkdir(parents=True, exist_ok=True)
        job_file.write_text(json.dumps({"job": job.name, "fingerprint": job_fingerprint}))
        log.info("Submitted batch job %s (%d segments)", job.name, len(lines))
        return job.name

    def _wait(self, job_name: str):
        while True:
            job = self.client.batches.get(name=job_name)
            state = job.state.name
            if state in _DONE_STATES:
                return job
            if state in _FAILED_STATES:
                (self.state_dir / JOB_FILE_NAME).unlink(missing_ok=True)
                raise RuntimeError(f"batch job {job_name} ended in {state}: {job.error}")
            log.info("Batch job %s, waiting %ds...", state, POLL_SECONDS)
            time.sleep(POLL_SECONDS)
