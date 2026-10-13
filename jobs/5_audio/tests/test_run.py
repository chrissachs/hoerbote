"""The audio job with a fake Batch API client -- no API calls."""

import base64
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from conftest import RUN_ID

from audio import AUDIO_DIR_NAME, MANIFEST_FILE_NAME, AudioManifest, text_hash
from published import PublishedPage, PublishedSegment
from run import JOB_FILE_NAME, run
from speech import DEFAULT_STYLE


def _wav() -> str:
    out = io.BytesIO()
    sf.write(out, np.zeros(2400), 24000, format="WAV")
    return base64.b64encode(out.getvalue()).decode()


class FakeClient:
    """Answers every request with a short silent WAV, except `fail_keys`."""

    def __init__(self, fail_keys: set[str] = frozenset()) -> None:
        self.fail_keys = fail_keys
        self.submitted: list[dict] = []
        self.files = SimpleNamespace(upload=self._upload, download=self._download)
        self.batches = SimpleNamespace(create=self._create, get=self._get)

    def _upload(self, file, config):
        self.submitted = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
        return SimpleNamespace(name="files/in")

    def _create(self, model, src, config):
        return SimpleNamespace(name="batches/1")

    def _get(self, name):
        state = SimpleNamespace(name="JOB_STATE_SUCCEEDED")
        return SimpleNamespace(state=state, error=None, dest=SimpleNamespace(file_name="files/out"))

    def _download(self, file, destination):
        lines = []
        for line in self.submitted:
            if line["key"] in self.fail_keys:
                lines.append({"key": line["key"], "error": {"code": 500}})
            else:
                part = {"inlineData": {"mimeType": "audio/wav", "data": _wav()}}
                lines.append({"key": line["key"], "response": {"candidates": [{"content": {"parts": [part]}}]}})
        destination.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def _manifest(rd) -> AudioManifest:
    return AudioManifest.model_validate_json((rd / AUDIO_DIR_NAME / MANIFEST_FILE_NAME).read_text())


def _status(rd) -> dict:
    return {s["name"]: s["status"] for s in json.loads((rd / "status.json").read_text())["steps"]}


def test_renders_every_segment_and_lists_it(run_dir):
    client = FakeClient()
    run(RUN_ID, client=client)
    assert [line["key"] for line in client.submitted] == ["page1-segment0", "page1-segment1"]
    manifest = _manifest(run_dir)
    assert [(s.page, s.index, s.text_hash) for s in manifest.segments] == [
        (1, 0, text_hash(["s0"])),
        (1, 1, text_hash(["s1"])),
    ]
    assert all((run_dir / s.file).is_file() for s in manifest.segments)
    assert not (run_dir / AUDIO_DIR_NAME / JOB_FILE_NAME).exists()
    assert _status(run_dir) == {"audio": "succeeded"}


def test_the_style_is_metadata_not_text(run_dir):
    # In the text, the TTS reads it out.
    client = FakeClient()
    run(RUN_ID, client=client)
    part = client.submitted[0]["request"]["contents"][0]["parts"][0]
    assert part["text"] == "s0"
    assert part["speechMetadata"]["style"] == DEFAULT_STYLE


def test_a_re_run_renders_only_what_changed_and_drops_the_old_take(run_dir):
    run(RUN_ID, client=FakeClient())
    old = {s.index: s.file for s in _manifest(run_dir).segments}
    path = run_dir / "04_published" / "page1.json"
    page = PublishedPage.model_validate_json(path.read_text())
    page.segments[1] = PublishedSegment(index=1, article_idx=0, sentences=["new text"])
    path.write_text(page.model_dump_json())

    client = FakeClient()
    run(RUN_ID, client=client)
    assert [line["key"] for line in client.submitted] == ["page1-segment1"]
    new = {s.index: s.file for s in _manifest(run_dir).segments}
    assert new[0] == old[0] and new[1] != old[1]
    assert not (run_dir / old[1]).exists()


def test_nothing_to_render_makes_no_api_call(run_dir):
    run(RUN_ID, client=FakeClient())
    client = FakeClient()
    run(RUN_ID, client=client)
    assert client.submitted == []


def test_a_failed_segment_fails_the_step_but_keeps_the_others(run_dir):
    with pytest.raises(RuntimeError, match="1 segments failed"):
        run(RUN_ID, client=FakeClient(fail_keys={"page1-segment0"}))
    assert [s.index for s in _manifest(run_dir).segments] == [1]
    assert _status(run_dir) == {"audio": "failed"}

    client = FakeClient()
    run(RUN_ID, client=client)
    assert [line["key"] for line in client.submitted] == ["page1-segment0"]
    assert _status(run_dir) == {"audio": "succeeded"}


def test_needs_a_published_issue(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="publish job"):
        run(RUN_ID, client=FakeClient())
