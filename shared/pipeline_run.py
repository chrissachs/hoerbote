"""Run directories and status.json: a job takes only a run_id, finds the
run under DATA_ROOT and records its progress in the run's status.json.

DATA_ROOT defaults to ./data relative to the CWD (local runs from the repo
root); the Dockerfiles set /data."""

import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def run_id_from_args() -> str:
    """The run_id an entrypoint was started for: its first CLI argument, or
    the RUN_ID env var (how a container gets it)."""
    run_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("RUN_ID")
    if not run_id:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} <run_id>  (or set RUN_ID)")
    return run_id


def data_root() -> Path:
    return Path(os.environ.get("DATA_ROOT", "./data"))


def run_dir(run_id: str, root: Path | None = None) -> Path:
    return (root or data_root()) / "issues" / run_id


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_status(path: Path, run_id: str) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"run_id": run_id, "status": "running", "started_at": _now(), "steps": []}


def _save_status(path: Path, status: dict) -> None:
    # The run's status follows its steps: failed while any step is, running
    # while any step is, otherwise succeeded (so far -- which job is the
    # last one is for the caller to know). A failed step re-run to success
    # thus clears the run's failure.
    states = {s["status"] for s in status["steps"]}
    status["status"] = "failed" if "failed" in states else "running" if "running" in states else "succeeded"
    status["updated_at"] = _now()
    path.write_text(json.dumps(status, indent=2, ensure_ascii=False))


def _find_or_add_step(status: dict, name: str) -> dict:
    for s in status["steps"]:
        if s["name"] == name:
            return s
    s = {"name": name}
    status["steps"].append(s)
    return s


class StepHandle:
    def __init__(self) -> None:
        self.output_path: str | None = None
        self.warnings: list[str] = []

    def finish(self, output_path: str) -> None:
        self.output_path = output_path

    def warn(self, message: str) -> None:
        """Something worth a look that doesn't fail the step (e.g. one page
        processed with degraded quality). Recorded as the step's `warnings`
        in status.json, whether the step then succeeds or fails."""
        self.warnings.append(message)


@contextmanager
def step(run_id: str, name: str, input_path: str):
    """Marks `name` running/succeeded/failed in run_id's status.json around
    the wrapped work. Call `.finish(output_path)` on the yielded handle once
    the stage's output has actually been written. A stage only records its
    output_path (and therefore only fires whatever watches for it) on
    success -- an exception marks the step failed with the exception
    message, re-raises so the process exits non-zero, and leaves no
    output_path behind, which is what halts the chain."""
    rd = run_dir(run_id)
    rd.mkdir(parents=True, exist_ok=True)
    status_path = rd / "status.json"

    status = _load_status(status_path, run_id)
    s = _find_or_add_step(status, name)
    s.update(status="running", started_at=_now(), finished_at=None, input_path=input_path, error=None)
    s.pop("output_path", None)
    s.pop("warnings", None)
    _save_status(status_path, status)

    handle = StepHandle()
    try:
        yield handle
    except Exception as e:
        s.update(status="failed", finished_at=_now(), error=str(e))
        _record_warnings(s, handle)
        _save_status(status_path, status)
        raise
    else:
        s.update(status="succeeded", finished_at=_now(), output_path=handle.output_path)
        _record_warnings(s, handle)
        _save_status(status_path, status)


def _record_warnings(s: dict, handle: StepHandle) -> None:
    # Only present when there are any, so status.json of a clean run looks
    # as it always did.
    if handle.warnings:
        s["warnings"] = handle.warnings
