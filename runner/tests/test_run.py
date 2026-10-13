"""The runner's order and skip logic with a fake `docker run` that writes
status.json the way the real jobs do."""

import datetime
import json
from pathlib import Path

import pytest

import run

RUN_ID = "paper-morning-1926-10-08"


class FakeDocker:
    """Records (image, args); each job writes its status.json step. `fail`:
    jobs that exit non-zero (and record a failed step)."""

    def __init__(self, data_dir: Path, fail: set[str] = frozenset()) -> None:
        self.data_dir, self.fail = data_dir, fail
        self.calls: list[tuple[str, list[str]]] = []

    def __call__(self, job: run.Job, args: list[str]) -> tuple[int, str]:
        self.calls.append((job.name, args))
        if job is run.FETCH and "already" in self.fail:
            return 0, RUN_ID  # an existing run dir: nothing written
        status = "failed" if job.name in self.fail else "succeeded"
        write_step(self.data_dir, job.name, status)
        return (1 if status == "failed" else 0), RUN_ID

    @property
    def jobs(self) -> list[str]:
        return [name for name, _ in self.calls]


def write_step(data_dir: Path, name: str, status: str, started_at: str | None = None) -> None:
    path = data_dir / "issues" / RUN_ID / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    st = json.loads(path.read_text()) if path.exists() else {"steps": []}
    st["steps"] = [s for s in st["steps"] if s["name"] != name]
    started_at = started_at or datetime.datetime.now(datetime.UTC).isoformat()
    st["steps"].append({"name": name, "status": status, "started_at": started_at})
    path.write_text(json.dumps(st))


@pytest.fixture
def config(tmp_path) -> run.Config:
    return run.Config(data_dir=tmp_path, host_data_dir="/host/data", user="1000:1000", repo_dir=tmp_path)


ALL = ["fetch", "layout", "articles", "narration", "publish"]


def test_daily_runs_a_new_issue_through_every_job(config):
    docker = FakeDocker(config.data_dir)
    assert run.daily(config, docker, ["paper"]) == 0
    assert docker.jobs == ALL
    assert docker.calls[0] == ("fetch", ["paper", "--if-new"])
    assert docker.calls[1] == ("layout", [RUN_ID])
    assert docker.calls[-1] == ("publish", [RUN_ID])


def test_daily_leaves_an_existing_run_alone(config):
    write_step(config.data_dir, "fetch", "succeeded", started_at="2026-10-11T06:00:00+00:00")
    write_step(config.data_dir, "layout", "failed", started_at="2026-10-11T06:01:00+00:00")
    docker = FakeDocker(config.data_dir, fail={"already"})
    assert run.daily(config, docker, ["paper"]) == 0
    assert docker.jobs == ["fetch"]


def test_daily_reports_a_failed_fetch_and_goes_on(config):
    docker = FakeDocker(config.data_dir, fail={"fetch"})
    assert run.daily(config, docker, ["a", "b"]) == 1
    assert docker.jobs == ["fetch", "fetch"]


def test_a_failed_job_stops_the_chain(config):
    docker = FakeDocker(config.data_dir, fail={"articles"})
    assert run.daily(config, docker, ["paper"]) == 1
    assert docker.jobs == ["fetch", "layout", "articles"]


def test_restart_continues_at_the_first_unfinished_job(config):
    for name in ("fetch", "layout"):
        write_step(config.data_dir, name, "succeeded")
    write_step(config.data_dir, "articles", "failed")
    docker = FakeDocker(config.data_dir)
    assert run.restart(config, docker, RUN_ID) == 0
    assert docker.jobs == ["articles", "narration", "publish"]


def test_restart_from_a_given_job(config):
    for name in ("fetch", "layout", "articles", "narration", "publish"):
        write_step(config.data_dir, name, "succeeded")
    docker = FakeDocker(config.data_dir)
    assert run.restart(config, docker, RUN_ID, from_job="narration") == 0
    assert docker.jobs == ["narration", "publish"]


def test_restart_of_a_finished_run_does_nothing(config):
    for name in ("fetch", "layout", "articles", "narration", "publish"):
        write_step(config.data_dir, name, "succeeded")
    docker = FakeDocker(config.data_dir)
    assert run.restart(config, docker, RUN_ID) == 0
    assert docker.jobs == []


def _request_audio(data_dir: Path, run_id: str = RUN_ID) -> Path:
    request = data_dir / "issues" / run_id / run.AUDIO_REQUEST_FILE_NAME
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text("2026-10-13T10:00:00+00:00\n")
    return request


def test_audio_requests_run_the_audio_job_once(config):
    request = _request_audio(config.data_dir)
    (config.data_dir / "issues" / "unrequested").mkdir()
    docker = FakeDocker(config.data_dir)
    assert run.audio_requests(config, docker) == 0
    assert docker.calls == [("audio", [RUN_ID])]
    assert not request.exists()
    assert run.audio_requests(config, docker) == 0
    assert len(docker.calls) == 1


def test_a_failed_audio_job_drops_the_request_too(config):
    request = _request_audio(config.data_dir)
    assert run.audio_requests(config, FakeDocker(config.data_dir, fail={"audio"})) == 1
    assert not request.exists()


def _request_import(data_dir: Path, state: str = "requested") -> Path:
    request = data_dir / run.IMPORT_REQUESTS_DIR_NAME / f"paper_1926-10-08.{state}"
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({"paper": "paper", "date": "1926-10-08", "requested_at": "2026-10-13T10:00:00Z"}))
    return request


def test_import_requests_run_fetch_and_the_chain_once(config):
    request = _request_import(config.data_dir)
    docker = FakeDocker(config.data_dir)
    assert run.import_requests(config, docker) == 0
    assert docker.jobs == ALL
    assert docker.calls[0] == ("fetch", ["paper", "--date", "1926-10-08", "--if-new"])
    assert list(request.parent.iterdir()) == []
    assert run.import_requests(config, docker) == 0
    assert docker.jobs == ALL


def test_a_failed_import_keeps_the_error_and_run_id(config):
    request = _request_import(config.data_dir)
    assert run.import_requests(config, FakeDocker(config.data_dir, fail={"layout"})) == 1
    (failed,) = request.parent.iterdir()
    body = json.loads(failed.read_text())
    assert failed.name == "paper_1926-10-08.failed"
    assert (body["run_id"], body["error"]) == (RUN_ID, f"layout failed -- restart with: run.py restart {RUN_ID}")
    # Not taken up again until asked again.
    docker = FakeDocker(config.data_dir)
    assert run.import_requests(config, docker) == 0
    assert docker.jobs == []


def test_a_failed_fetch_keeps_its_last_line(config):
    _request_import(config.data_dir)

    def docker(job: run.Job, args: list[str]) -> tuple[int, str]:
        return 1, "no issue of paper on 1926-10-08"

    assert run.import_requests(config, docker) == 1
    (failed,) = (config.data_dir / run.IMPORT_REQUESTS_DIR_NAME).iterdir()
    assert json.loads(failed.read_text())["error"] == "fetch: no issue of paper on 1926-10-08"


def test_an_import_cut_off_is_taken_up_again(config):
    _request_import(config.data_dir, state="running")
    for name in ("fetch", "layout"):
        write_step(config.data_dir, name, "succeeded")
    docker = FakeDocker(config.data_dir, fail={"already"})
    assert run.import_requests(config, docker) == 0
    assert docker.jobs == ["fetch", "articles", "narration", "publish"]


def test_docker_command(config, monkeypatch):
    (config.repo_dir / "jobs" / "3_narration").mkdir(parents=True)
    (config.repo_dir / "jobs" / "3_narration" / ".env").write_text("GEMINI_API_KEY=x\n")
    seen = []

    class Proc:
        stdout = iter(["working\n", f"{RUN_ID}\n", "\n"])
        returncode = 0

        def __init__(self, cmd, **kwargs):
            seen.append(cmd)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(run.subprocess, "Popen", Proc)
    narration = next(j for j in run.JOBS if j.name == "narration")
    assert run.docker_run(config)(narration, [RUN_ID]) == (0, RUN_ID)
    assert seen[0] == [
        "docker",
        "run",
        "--rm",
        "--user",
        "1000:1000",
        "-v",
        "/host/data:/data",
        "--env-file",
        str(config.repo_dir / "jobs/3_narration/.env"),
        "hoerbote-narration",
        RUN_ID,
    ]
