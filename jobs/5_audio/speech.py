"""Narration text -> Ogg Opus, via Gemini Flash-Lite TTS.

Everything that shapes a segment's sound -- model, voice, style -- is
here, and all of it goes into `fingerprint()`, so changing any of it (or
the narration text) renders fresh instead of reusing a take."""

import base64
import hashlib
import io
from pathlib import Path

import soundfile as sf

from source_info import SOURCE_INFO_FILE_NAME, SourceInfo

# Flash-Lite TTS rather than Flash TTS: about a third cheaper per audio
# minute, same storyteller voices.
MODEL_ID = "gemini-3.8-flash-lite-tts"
# libsndfile's 0-1 scale (higher = smaller). 0.95 is ~19 kbps for the TTS's
# 24 kHz mono: ~30% of the MP3 at 64 kbps used before, and no difference
# heard (2026-10-13).
OPUS_COMPRESSION_LEVEL = 0.95
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


def voice_for(segment_index: int) -> str:
    """A pure function of the segment's position, so rendering order (or
    which segments ever get rendered) can't change who reads what."""
    return VOICE_POOL[segment_index % len(VOICE_POOL)]


def style_for(run_dir: Path) -> str:
    """The run's paper's speech style, else DEFAULT_STYLE."""
    return SourceInfo.model_validate_json((run_dir / SOURCE_INFO_FILE_NAME).read_text()).speech_style or DEFAULT_STYLE


def fingerprint(text: str, voice: str, style: str) -> str:
    return hashlib.sha256("\n".join([MODEL_ID, voice, style, text]).encode()).hexdigest()[:12]


def batch_request(text: str, voice: str, style: str) -> dict:
    """One segment's render, as one line of a Batch API input file (REST
    format: the batch runs generateContent). The style goes into the part's
    speechMetadata: the 3.8 TTS models take the text as a verbatim
    transcript, so a style put in front of it gets read out (it did on
    2026-10-13, every time), and a systemInstruction is rejected."""
    return {
        "contents": [{"role": "user", "parts": [{"text": text, "speechMetadata": {"style": style}}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }


def audio_from_batch_response(response: dict) -> bytes:
    """The audio of one Batch API output line's `response`, encoded."""
    return encode(base64.b64decode(response["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]))


def encode(wav: bytes) -> bytes:
    """Ogg Opus rather than the API's WAV: ~50x smaller (25 s: ~60 KB),
    which matters on mobile. Plays in every major browser (Safari since
    18.4, 2025)."""
    samples, sample_rate = sf.read(io.BytesIO(wav))
    out = io.BytesIO()
    sf.write(out, samples, sample_rate, format="OGG", subtype="OPUS", compression_level=OPUS_COMPRESSION_LEVEL)
    return out.getvalue()
