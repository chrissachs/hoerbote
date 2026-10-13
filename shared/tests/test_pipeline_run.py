"""status.json transitions around a step: running -> succeeded/failed,
warnings, and the run's overall status following its steps."""

import json

import pytest

from pipeline_run import run_dir, step

RUN_ID = "paper-morning-1926-10-08"


@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))


def _status() -> dict:
    return json.loads((run_dir(RUN_ID) / "status.json").read_text())


def _step(name: str) -> dict:
    return next(s for s in _status()["steps"] if s["name"] == name)


def test_running_then_succeeded():
    with step(RUN_ID, "fetch", input_path="in") as s:
        assert _step("fetch")["status"] == "running"
        assert _status()["status"] == "running"
        s.finish("out")
    assert _step("fetch") | {"started_at": None, "finished_at": None} == {
        "name": "fetch",
        "status": "succeeded",
        "input_path": "in",
        "output_path": "out",
        "error": None,
        "started_at": None,
        "finished_at": None,
    }
    assert _status()["status"] == "succeeded"


def test_failure_records_error_and_reraises():
    with pytest.raises(ValueError):
        with step(RUN_ID, "fetch", input_path="in") as s:
            s.warn("page 3 degraded")
            raise ValueError("boom")
    st = _step("fetch")
    assert (st["status"], st["error"], st["warnings"]) == ("failed", "boom", ["page 3 degraded"])
    assert "output_path" not in st
    assert _status()["status"] == "failed"


def test_successful_rerun_clears_the_failure():
    with pytest.raises(ValueError):
        with step(RUN_ID, "layout", input_path="in") as s:
            s.warn("old warning")
            raise ValueError("boom")
    with step(RUN_ID, "layout", input_path="in") as s:
        s.finish("out")
    st = _step("layout")
    assert (st["status"], st["error"], st.get("warnings")) == ("succeeded", None, None)
    assert _status()["status"] == "succeeded"


def test_steps_keep_their_order_and_one_failure_fails_the_run():
    with step(RUN_ID, "fetch", input_path="in") as s:
        s.finish("out")
    with pytest.raises(RuntimeError):
        with step(RUN_ID, "layout", input_path="in"):
            raise RuntimeError("no GPU")
    assert [s["name"] for s in _status()["steps"]] == ["fetch", "layout"]
    assert _status()["status"] == "failed"
