"""What run.py needs from a speech engine, and which one SPEECH_ENGINE picks.
Unlike the rest of the repo, the engines are named after their tool:
they're alternatives side by side."""

import io
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import soundfile as sf

# libsndfile's 0-1 scale, higher = smaller: ~19 kbps for 24 kHz speech.
OPUS_COMPRESSION_LEVEL = 0.95
ENGINES = ("gemini", "qwen3-tts")


@dataclass(frozen=True)
class Request:
    """One segment to render."""

    sentences: list[str]
    voice: str  # from the engine's voice_for()


class SpeechEngine(Protocol):
    def voice_for(self, segment_index: int) -> str:
        """Who reads a segment: a pure function of its position, so
        rendering order (or which segments ever get rendered) can't change
        it."""

    def fingerprint(self, sentences: list[str], voice: str) -> str:
        """A short hash of everything that shapes the take's sound: the
        text, the voice and the engine's settings. It names the take, so a
        change to any of it renders afresh."""

    def render(self, requests: dict[str, Request]) -> Iterator[tuple[str, bytes | Exception]]:
        """(key, Ogg Opus take) for every request, or (key, why it failed),
        yielded as each is ready so the caller can save it right away. A key
        never yielded counts as failed too."""


def configure_logging() -> None:
    """For the entrypoints. httpx (google-genai's client) logs every request
    at INFO."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def engine_name() -> str:
    name = os.environ.get("SPEECH_ENGINE", "gemini")
    if name not in ENGINES:
        raise SystemExit(f"SPEECH_ENGINE={name!r}: must be one of {', '.join(ENGINES)}")
    return name


def make_engine(rd: Path, name: str | None = None) -> SpeechEngine:
    """Imports only the chosen engine, so only its credentials are needed."""
    name = name or engine_name()
    if name == "qwen3-tts":
        from qwen3_tts import Qwen3Engine

        return Qwen3Engine.from_voices_file()
    from gemini_tts import GeminiEngine

    return GeminiEngine.for_run(rd)


def encode(samples: np.ndarray, sample_rate: int) -> bytes:
    """Ogg Opus: ~50x smaller than WAV, and plays in every major browser
    (Safari since 18.4)."""
    out = io.BytesIO()
    sf.write(out, samples, sample_rate, format="OGG", subtype="OPUS", compression_level=OPUS_COMPRESSION_LEVEL)
    return out.getvalue()
