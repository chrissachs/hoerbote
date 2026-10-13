"""Audio state, requests and serving, against a hand-written audio.json --
no audio job, no API calls."""

import json

import pytest
from conftest import OPEN_RUN_ID, RESTRICTED_RUN_ID
from fastapi.testclient import TestClient
from test_app import PASSWORD

from app import create_app
from audio import AUDIO_DIR_NAME, MANIFEST_FILE_NAME, REQUEST_FILE_NAME, AudioManifest, AudioSegment, text_hash

RUN_ID = RESTRICTED_RUN_ID
AUDIO = f"/api/issues/{RUN_ID}/audio"
SEGMENT_AUDIO = f"/api/issues/{RUN_ID}/pages/1/segments/0/audio"


@pytest.fixture
def client(data):
    client = TestClient(create_app(PASSWORD, frontend_dir=data / "no-frontend"), base_url="https://testserver")
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 204
    return client


@pytest.fixture
def rd(data):
    return data / "issues" / RUN_ID


def _render(rd, text: str = "s") -> None:
    """What the audio job leaves behind for the fixture's one segment."""
    take = rd / AUDIO_DIR_NAME / "page1" / "segment0-abc.ogg"
    take.parent.mkdir(parents=True)
    take.write_bytes(b"ogg")
    manifest = AudioManifest(
        segments=[AudioSegment(page=1, index=0, text_hash=text_hash([text]), file=str(take.relative_to(rd)))]
    )
    (rd / AUDIO_DIR_NAME / MANIFEST_FILE_NAME).write_text(manifest.model_dump_json())


def _audio_step(rd, status: str) -> None:
    (rd / "status.json").write_text(json.dumps({"steps": [{"name": "audio", "status": status}]}))


def test_nothing_rendered(client):
    assert client.get(AUDIO).json() == {"status": "none", "rendered": 0, "total": 1}
    assert client.get(SEGMENT_AUDIO).status_code == 404


def test_rendered_audio_is_served(client, rd):
    _render(rd)
    assert client.get(AUDIO).json() == {"status": "ready", "rendered": 1, "total": 1}
    r = client.get(SEGMENT_AUDIO)
    assert (r.status_code, r.content, r.headers["content-type"]) == (200, b"ogg", "audio/ogg")


def test_a_take_of_older_text_isnt(client, rd):
    _render(rd, text="the text before a narration re-run")
    assert client.get(AUDIO).json()["status"] == "none"
    assert client.get(SEGMENT_AUDIO).status_code == 404


def test_request_writes_the_request_file_once(client, rd):
    r = client.post(AUDIO)
    assert (r.status_code, r.json()["status"]) == (202, "requested")
    first = (rd / REQUEST_FILE_NAME).read_text()
    assert client.post(AUDIO).json()["status"] == "requested"
    assert (rd / REQUEST_FILE_NAME).read_text() == first


def test_request_while_rendering_or_ready_is_a_no_op(client, rd):
    _audio_step(rd, "running")
    assert client.post(AUDIO).json()["status"] == "rendering"
    _audio_step(rd, "succeeded")
    _render(rd)
    assert client.post(AUDIO).json()["status"] == "ready"
    assert not (rd / REQUEST_FILE_NAME).exists()


def test_failed_job_can_be_asked_again(client, rd):
    _audio_step(rd, "failed")
    assert client.get(AUDIO).json()["status"] == "failed"
    assert client.post(AUDIO).json()["status"] == "requested"


def test_anonymous_visitors_cant_ask_for_audio(data):
    anonymous = TestClient(create_app(PASSWORD, frontend_dir=data / "no-frontend"), base_url="https://testserver")
    assert anonymous.get(f"/api/issues/{OPEN_RUN_ID}/audio").json()["status"] == "ready"  # no segments
    assert anonymous.post(f"/api/issues/{OPEN_RUN_ID}/audio").status_code == 401
    assert not (data / "issues" / OPEN_RUN_ID / REQUEST_FILE_NAME).exists()
