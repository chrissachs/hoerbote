"""The audio job -> backend contract: 05_audio/audio.json lists every
rendered segment and its audio file, plus the request file through which the
backend asks for a render.

Each entry carries a hash of the segment's text, so the backend can tell
a take that no longer matches the published text (narration or publish
re-run since) without knowing anything about voices or models."""

import hashlib

from pydantic import BaseModel

AUDIO_DIR_NAME = "05_audio"
MANIFEST_FILE_NAME = "audio.json"
# At the run root, not in 05_audio (the audio job's own output): the
# backend writes it when someone asks for the issue's audio, the runner
# deletes it when it starts the audio job.
REQUEST_FILE_NAME = "05_audio.requested"
# The audio job's step name in status.json.
STEP_NAME = "audio"


def text_hash(sentences: list[str]) -> str:
    return hashlib.sha256(" ".join(sentences).encode()).hexdigest()[:12]


class AudioSegment(BaseModel):
    page: int
    # PublishedSegment.index.
    index: int
    # text_hash() of the sentences the take was rendered from.
    text_hash: str
    # The audio file (Ogg Opus), relative to the run directory.
    file: str


class AudioManifest(BaseModel):
    segments: list[AudioSegment]
