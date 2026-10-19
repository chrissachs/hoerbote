"""The Qwen3-TTS engine with a fake GPU side -- no Modal, no model."""

import io

import numpy as np
import pytest
import soundfile as sf
from conftest import RUN_ID

import qwen3_tts
from audio import AUDIO_DIR_NAME, MANIFEST_FILE_NAME, AudioManifest
from qwen3_tts import Qwen3Engine, Sentence, Voice, load_voices, plan_batches, stitch
from run import run
from speech_engine import Request, make_engine

RATE = 24000
VOICES = [Voice("female", b"clip-f", "Text."), Voice("male", b"clip-m", "Text.")]


class FakeSpeaker:
    """Every sentence as 0.1 s of a tone; `fail_chunks` raise instead."""

    def __init__(self, fail_chunks: set[int] = frozenset()) -> None:
        self.fail_chunks = fail_chunks
        self.chunks: list = []
        self.voices: dict | None = None

    def __call__(self, chunks, voices):
        self.chunks, self.voices = chunks, voices
        pcm = (np.sin(np.arange(RATE // 10) / 10) * 10000).astype(np.int16).tobytes()
        for n, chunk in enumerate(chunks):
            if n in self.fail_chunks:
                yield RuntimeError("preempted twice")
            else:
                yield [[{"pcm": pcm, "sample_rate": RATE, "capped": False} for _ in batch] for batch in chunk]


def _manifest(rd) -> AudioManifest:
    return AudioManifest.model_validate_json((rd / AUDIO_DIR_NAME / MANIFEST_FILE_NAME).read_text())


def test_renders_every_segment_with_alternating_voices(run_dir):
    speaker = FakeSpeaker()
    run(RUN_ID, Qwen3Engine(VOICES, speaker))
    sent = [item for chunk in speaker.chunks for batch in chunk for item in batch]
    assert sorted(sent) == [("female", "s0"), ("male", "s1")]
    assert speaker.voices == {"female": b"clip-f", "male": b"clip-m"}
    manifest = _manifest(run_dir)
    assert [s.index for s in manifest.segments] == [0, 1]
    samples, rate = sf.read(run_dir / manifest.segments[0].file)
    assert rate == RATE and len(samples) > 0


def test_a_segments_sentences_are_stitched_in_order_with_a_pause(monkeypatch):
    speaker = FakeSpeaker()
    engine = Qwen3Engine(VOICES, speaker)
    out = dict(engine.render({"k": Request(["Kurz.", "Ein deutlich längerer zweiter Satz."], "female")}))
    samples, rate = sf.read(io.BytesIO(out["k"]))
    expected = 2 * RATE // 10 + int(qwen3_tts.PAUSE_S * RATE)
    # Opus pads and trims a little.
    assert abs(len(samples) - expected) < RATE // 50


def test_plan_sorts_all_sentences_by_length_across_voices():
    sentences = [
        Sentence("a", 0, "female", "x" * 30),
        Sentence("b", 0, "male", "x" * 10),
        Sentence("a", 1, "female", "x" * 20),
    ]
    plan = plan_batches(sentences, batch_size=2)
    assert [[len(s.text) for s in batch] for batch in plan] == [[10, 20], [30]]
    assert {s.voice for s in plan[0]} == {"female", "male"}


def test_a_failed_gpu_call_fails_only_its_segments(monkeypatch):
    monkeypatch.setattr(qwen3_tts, "BATCH_SIZE", 1)
    monkeypatch.setattr(qwen3_tts, "CHUNK_BATCHES", 1)
    engine = Qwen3Engine(VOICES, FakeSpeaker(fail_chunks={0}))
    results = dict(engine.render({"short": Request(["a"], "female"), "long": Request(["a longer one"], "male")}))
    assert isinstance(results["short"], Exception)
    assert isinstance(results["long"], bytes)


def test_stitch_puts_the_pause_between_sentences_only():
    one = np.full(100, 16000, dtype=np.int16).tobytes()
    out = stitch([one, one], RATE)
    assert len(out) == 200 + int(qwen3_tts.PAUSE_S * RATE)
    assert out[0] == pytest.approx(16000 / 32767) and out[150] == 0


def test_fingerprint_changes_with_text_voice_and_clip():
    engine = Qwen3Engine(VOICES, FakeSpeaker())
    base = engine.fingerprint(["s"], "female")
    assert engine.fingerprint(["s"], "female") == base
    assert engine.fingerprint(["t"], "female") != base
    assert engine.fingerprint(["s"], "male") != base
    other_clip = Qwen3Engine([Voice("female", b"another clip", "Text.")], FakeSpeaker())
    assert other_clip.fingerprint(["s"], "female") != base


def test_engines_take_different_names(run_dir):
    # Switching engines renders afresh instead of keeping the other's takes.
    gemini, qwen3 = make_engine(run_dir, "gemini"), Qwen3Engine(VOICES, FakeSpeaker())
    assert gemini.fingerprint(["s"], gemini.voice_for(0)) != qwen3.fingerprint(["s"], qwen3.voice_for(0))


def test_voices_file(tmp_path):
    (tmp_path / "f.ogg").write_bytes(b"clip")
    (tmp_path / "voices.toml").write_text('[[voice]]\nname = "female"\nclip = "f.ogg"\ntranscript = "Hallo."\n')
    assert load_voices(tmp_path / "voices.toml") == [Voice("female", b"clip", "Hallo.")]
    with pytest.raises(SystemExit, match="make_voices.py"):
        load_voices(tmp_path / "missing.toml")


def test_unknown_engine_is_refused(run_dir, monkeypatch):
    monkeypatch.setenv("SPEECH_ENGINE", "other")
    with pytest.raises(SystemExit, match="SPEECH_ENGINE"):
        make_engine(run_dir)
