"""Import requests: the files the backend writes, and how it reads the
runner's progress from them -- no runner, no jobs."""

import json

import pytest
from fastapi.testclient import TestClient
from test_app import PASSWORD

from app import create_app
from import_request import REQUESTS_DIR_NAME
from papers import load_papers

IMPORTS = "/api/imports"
FORM = {"paper": "berliner-tageblatt", "date": "1926-10-08"}
STEM = "berliner-tageblatt_1926-10-08"


@pytest.fixture
def client(data):
    client = TestClient(create_app(PASSWORD, frontend_dir=data / "no-frontend"), base_url="https://testserver")
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 204
    return client


@pytest.fixture
def requests_dir(data):
    return data / REQUESTS_DIR_NAME


def _imports(client) -> list[dict]:
    return client.get(IMPORTS).json()["imports"]


def _runner_renames(requests_dir, state: str, **fields) -> None:
    """What the runner does with the request file."""
    (current,) = requests_dir.glob(f"{STEM}.*")
    body = json.loads(current.read_text()) | fields
    current.write_text(json.dumps(body))
    current.rename(requests_dir / f"{STEM}.{state}")


def test_nothing_asked_for(client):
    imports = client.get(IMPORTS).json()
    assert imports["imports"] == []
    # The repo's config/papers.toml (the tests run from the repo root).
    tageblatt = next(p for p in imports["papers"] if p["slug"] == "berliner-tageblatt")
    assert tageblatt["title"] == "Berliner Tageblatt und Handels-Zeitung"
    assert tageblatt["default_date"] == load_papers()["berliner-tageblatt"].default_date().isoformat()


def test_request_writes_the_request_file_once(client, requests_dir):
    r = client.post(IMPORTS, json=FORM)
    assert (r.status_code, r.json()["status"]) == (202, "requested")
    first = (requests_dir / f"{STEM}.requested").read_text()
    assert client.post(IMPORTS, json=FORM).json()["status"] == "requested"
    assert (requests_dir / f"{STEM}.requested").read_text() == first
    assert [(i["paper"], i["date"], i["status"]) for i in _imports(client)] == [
        ("berliner-tageblatt", "1926-10-08", "requested")
    ]


def test_running_shows_the_job_at_work(client, data, requests_dir):
    client.post(IMPORTS, json=FORM)
    _runner_renames(requests_dir, "running")
    assert (_imports(client)[0]["status"], _imports(client)[0]["step"]) == ("running", None)
    run_id = "berliner-tageblatt-morning-1926-10-08"
    _runner_renames(requests_dir, "running", run_id=run_id)
    steps = [{"name": "fetch", "status": "succeeded"}, {"name": "layout", "status": "running"}]
    (data / "issues" / run_id / "status.json").write_text(json.dumps({"steps": steps}))
    assert (_imports(client)[0]["run_id"], _imports(client)[0]["step"]) == (run_id, "layout")
    # Asking again meanwhile changes nothing.
    assert client.post(IMPORTS, json=FORM).json()["status"] == "running"
    assert [p.name for p in requests_dir.iterdir()] == [f"{STEM}.running"]


def test_failed_can_be_asked_again_or_dismissed(client, requests_dir):
    client.post(IMPORTS, json=FORM)
    _runner_renames(requests_dir, "failed", error="fetch: no issue that day")
    assert (_imports(client)[0]["status"], _imports(client)[0]["error"]) == ("failed", "fetch: no issue that day")
    assert client.post(IMPORTS, json=FORM).json()["status"] == "requested"
    assert [p.name for p in requests_dir.iterdir()] == [f"{STEM}.requested"]
    _runner_renames(requests_dir, "failed", error="x")
    assert client.delete(f"{IMPORTS}/berliner-tageblatt/1926-10-08").status_code == 204
    assert _imports(client) == []


def test_unknown_papers_and_bad_dates_are_refused(client, requests_dir):
    assert client.post(IMPORTS, json=FORM | {"paper": "../issues"}).status_code == 422
    assert client.post(IMPORTS, json=FORM | {"date": "1926-13-01"}).status_code == 422
    assert client.delete(f"{IMPORTS}/nope/1926-10-08").status_code == 422
    assert not requests_dir.exists()


def test_anonymous_visitors_cant_see_or_ask(data):
    anonymous = TestClient(create_app(PASSWORD, frontend_dir=data / "no-frontend"), base_url="https://testserver")
    assert anonymous.get(IMPORTS).status_code == 401
    assert anonymous.post(IMPORTS, json=FORM).status_code == 401
    assert not (data / REQUESTS_DIR_NAME).exists()
