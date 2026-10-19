"""The qwen3-tts engine, job side: plans the batches, sends them to the GPU
side (qwen3_tts_gpu.py) and stitches each segment's sentences into a take.
Needs Modal credentials and voices/voices.toml (make_voices.py)."""

import hashlib
import json
import logging
import time
import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import qwen3_tts_gpu
from speech_engine import Request, encode

log = logging.getLogger(__name__)

VOICES_DIR = Path(__file__).parent / "voices"
VOICES_FILE = VOICES_DIR / "voices.toml"
# Fits an L4 (24 GB) with room to spare.
BATCH_SIZE = 48
# Batches per GPU call: what a preemption costs at most.
CHUNK_BATCHES = 2
# Between a segment's sentences, which are rendered one by one.
PAUSE_S = 0.35

# The GPU side: chunks of batches of (voice, sentence) -> per sentence
# {"pcm", "sample_rate", "capped"}, or the chunk's exception. In order.
Speaker = Callable[[list[list[list[tuple[str, str]]]], dict[str, bytes]], Iterable[list[list[dict]] | BaseException]]


@dataclass(frozen=True)
class Voice:
    name: str
    clip: bytes  # reference clip, Ogg
    transcript: str  # what the clip says; x-vector cloning doesn't use it


@dataclass(frozen=True)
class Sentence:
    key: str  # the segment's request key
    position: int  # in the segment
    voice: str
    text: str


def load_voices(path: Path = VOICES_FILE) -> list[Voice]:
    """The voices in voices.toml, in pool order (alternating F/M)."""
    if not path.is_file():
        raise SystemExit(f"missing {path} -- render the reference clips first: make_voices.py")
    entries = tomllib.loads(path.read_text(encoding="utf-8"))["voice"]
    return [Voice(e["name"], (path.parent / e["clip"]).read_bytes(), e["transcript"]) for e in entries]


def plan_batches(sentences: list[Sentence], batch_size: int = BATCH_SIZE) -> list[list[Sentence]]:
    # By length, voices mixed: a batch takes as long as its longest sentence.
    by_length = sorted(sentences, key=lambda s: len(s.text))
    return [by_length[i : i + batch_size] for i in range(0, len(by_length), batch_size)]


def stitch(pieces: list[bytes], sample_rate: int) -> np.ndarray:
    """A segment's sentences (16-bit PCM each) as one float waveform, with
    PAUSE_S of silence between them."""
    gap = np.zeros(int(PAUSE_S * sample_rate), dtype=np.float32)
    parts = [np.frombuffer(p, dtype=np.int16).astype(np.float32) / 32767 for p in pieces]
    return np.concatenate([x for part in parts for x in (part, gap)][:-1])


def modal_speaker(chunks: list[list[list[tuple[str, str]]]], voices: dict[str, bytes]):
    """The real GPU side: a Modal app for this run, all chunks through one
    container."""
    import modal

    with modal.enable_output(), qwen3_tts_gpu.app.run():
        speaker = qwen3_tts_gpu.Speaker()
        yield from speaker.render.map(chunks, [voices] * len(chunks), return_exceptions=True)


class Qwen3Engine:
    def __init__(self, voices: list[Voice], speaker: Speaker = modal_speaker) -> None:
        self.voices = voices
        self._clips = {v.name: v.clip for v in voices}
        self._speaker = speaker

    @classmethod
    def from_voices_file(cls) -> Qwen3Engine:
        return cls(load_voices())

    def voice_for(self, segment_index: int) -> str:
        return self.voices[segment_index % len(self.voices)].name

    def fingerprint(self, sentences: list[str], voice: str) -> str:
        settings = {
            "model": qwen3_tts_gpu.MODEL,
            "revision": qwen3_tts_gpu.MODEL_REVISION,
            "language": qwen3_tts_gpu.LANGUAGE,
            "seed": qwen3_tts_gpu.SEED,
            "generation": qwen3_tts_gpu.GEN_KWARGS,
            "cap": [qwen3_tts_gpu.TOKENS_PER_CHAR_CAP, qwen3_tts_gpu.TOKENS_CAP_MARGIN],
            "pause_s": PAUSE_S,
            "voice": voice,
            "clip": hashlib.sha256(self._clips[voice]).hexdigest(),
            "sentences": sentences,
        }
        return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:12]

    def render(self, requests: dict[str, Request]) -> Iterator[tuple[str, bytes | Exception]]:
        sentences = [
            Sentence(key, i, r.voice, text) for key, r in requests.items() for i, text in enumerate(r.sentences)
        ]
        plan = plan_batches(sentences, BATCH_SIZE)
        chunks = [plan[i : i + CHUNK_BATCHES] for i in range(0, len(plan), CHUNK_BATCHES)]
        log.info(
            "%d sentences of %d segments: %d batches in %d GPU calls",
            len(sentences),
            len(requests),
            len(plan),
            len(chunks),
        )

        pieces: dict[str, dict[int, bytes]] = {key: {} for key in requests}
        failed: dict[str, Exception] = {}
        sample_rate = None
        # The ETA weighs each chunk by its batches' longest sentences.
        weights = [sum(max(len(s.text) for s in batch) for batch in chunk) for chunk in chunks]
        t0 = time.perf_counter()
        first_done = None
        payload = [[[(s.voice, s.text) for s in batch] for batch in chunk] for chunk in chunks]
        for n, (chunk, result) in enumerate(zip(chunks, self._speaker(payload, self._clips), strict=True)):
            self._log_progress(n, len(chunks), weights, t0, first_done)
            first_done = first_done or time.perf_counter()
            if isinstance(result, BaseException):
                for batch in chunk:
                    for s in batch:
                        failed.setdefault(s.key, RuntimeError(f"GPU call {n + 1} failed: {result!r}"))
            else:
                for batch, rendered in zip(chunk, result, strict=True):
                    for s, take in zip(batch, rendered, strict=True):
                        pieces[s.key][s.position] = take["pcm"]
                        sample_rate = take["sample_rate"]
                        if take["capped"]:
                            log.warning("%s: a sentence ran into the token cap, cut off: %r", s.key, s.text[:60])
            for key in [k for k, got in pieces.items() if k not in failed and len(got) == len(requests[k].sentences)]:
                got = pieces.pop(key)
                yield key, encode(stitch([got[i] for i in range(len(got))], sample_rate), sample_rate)
        for key, error in failed.items():
            yield key, error

    @staticmethod
    def _log_progress(n: int, total: int, weights: list[int], t0: float, first_done: float | None) -> None:
        """The first call includes starting the GPU, so the ETA's rate starts
        after it."""
        now = time.perf_counter()
        if first_done is None:
            log.info("GPU call 1/%d done after %.1f min, incl. starting the GPU", total, (now - t0) / 60)
            return
        left = sum(weights[n + 1 :]) * (now - first_done) / sum(weights[1 : n + 1])
        log.info("GPU call %d/%d done: %.1f min elapsed, ETA %.1f min", n + 1, total, (now - t0) / 60, left / 60)
