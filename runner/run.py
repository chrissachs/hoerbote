"""Pipeline runner: starts the jobs, one container each, in order.

    run.py import-requests               # what the cron runs every minute
    run.py audio-requests                # likewise
    run.py daily <paper>...              # fetch today's issues, by hand
    run.py restart <run_id> [--from JOB] # continue (or redo) one run by hand
    run.py audio <run_id>                # render one issue's audio by hand

Nothing runs on its own: every job costs money or leads to one that does,
so the cron only does what someone asked for in the web app.
`import-requests` fetches each issue asked for (the backend writes a
request file) and runs it through all jobs up to publish, continuing a
run that's already there.

`daily` fetches today's issue of each paper given and runs each new
one through all jobs up to publish. An issue whose run dir already exists
is left alone, failed or not: a failed run stays failed until it's
restarted by hand. `restart` continues a run at its first job that hasn't
succeeded (status.json), or at JOB.

Audio isn't part of that: it costs money per issue, so the audio job
only runs for an issue someone asked for. `audio-requests` starts it for
every run with a request file (the backend writes it).

Each job runs as `docker run` on the host's Docker (the socket is mounted
into this container), so the data dir it gets is the host path of this
container's /data (or HOST_DATA_DIR), and it runs as the data dir's owner.
Env files (jobs' .env) are read from the repo, mounted at REPO_DIR."""

import argparse
import datetime
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path


@dataclass(frozen=True)
class Job:
    name: str  # its step name in status.json
    image: str
    # Relative to the repo root; passed to `docker run --env-file` if present.
    env_file: str | None = None


FETCH = Job("fetch", "hoerbote-fetch")
JOBS = [
    Job("layout", "hoerbote-layout-modal", "jobs/1_layout/.env"),
    Job("articles", "hoerbote-articles"),
    Job("narration", "hoerbote-narration", "jobs/3_narration/.env"),
    Job("publish", "hoerbote-publish"),
]
# Only on request, not in the chain.
AUDIO = Job("audio", "hoerbote-audio", "jobs/5_audio/.env")
# Written by the backend into the run dir (shared/audio.py's
# REQUEST_FILE_NAME -- the runner has no dependencies to import it from).
AUDIO_REQUEST_FILE_NAME = "05_audio.requested"
# Likewise shared/import_request.py: <paper>_<date>.<state> in this dir
# under the data dir, the state one of these.
IMPORT_REQUESTS_DIR_NAME = "import-requests"
REQUESTED, RUNNING, FAILED = "requested", "running", "failed"

# (job, args) -> (exit code, stdout); the tests swap in a fake.
Docker = Callable[[Job, list[str]], tuple[int, str]]


@dataclass(frozen=True)
class Config:
    data_dir: Path  # this container's view of the data dir
    host_data_dir: str
    user: str  # uid:gid for the job containers
    repo_dir: Path  # for the env files

    @classmethod
    def from_env(cls) -> Config:
        data_dir = Path(os.environ.get("DATA_ROOT", "/data"))
        owner = data_dir.stat()
        return cls(
            data_dir=data_dir,
            host_data_dir=os.environ.get("HOST_DATA_DIR") or _host_path_of(data_dir),
            user=f"{owner.st_uid}:{owner.st_gid}",
            repo_dir=Path(os.environ.get("REPO_DIR", "/repo")),
        )


def _host_path_of(mount_point: Path) -> str:
    """Where `mount_point` of this container is on the host, from Docker
    itself (a container's hostname is its id)."""
    fmt = f'{{{{range .Mounts}}}}{{{{if eq .Destination "{mount_point}"}}}}{{{{.Source}}}}{{{{end}}}}{{{{end}}}}'
    out = subprocess.run(
        ["docker", "inspect", "--format", fmt, os.uname().nodename], capture_output=True, text=True, check=True
    )
    if not out.stdout.strip():
        raise SystemExit(f"{mount_point} isn't a bind mount of this container; set HOST_DATA_DIR")
    return out.stdout.strip()


def docker_run(config: Config) -> Docker:
    def run(job: Job, args: list[str]) -> tuple[int, str]:
        cmd = ["docker", "run", "--rm", "--user", config.user, "-v", f"{config.host_data_dir}:/data"]
        if job.env_file and (config.repo_dir / job.env_file).is_file():
            cmd += ["--env-file", str(config.repo_dir / job.env_file)]
        cmd += [job.image, *args]
        log(f"$ {' '.join(cmd)}")
        # Output streams to our log as it comes; only the last line is kept
        # (the fetch job prints its run_id there).
        last = ""
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            for line in proc.stdout:
                print(line, end="", flush=True)
                last = line.strip() or last
        return proc.returncode, last

    return run


def log(message: str) -> None:
    print(f"[runner {datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def _status(config: Config, run_id: str) -> dict:
    path = config.data_dir / "issues" / run_id / "status.json"
    return json.loads(path.read_text()) if path.is_file() else {"steps": []}


def daily(config: Config, docker: Docker, papers: list[str]) -> int:
    """Fetch + full run for each paper's new issue. Non-zero if anything
    failed (a day without an issue counts: the fetch job can't tell)."""
    failures = 0
    for paper in papers:
        started = datetime.datetime.now(datetime.UTC).isoformat()
        code, run_id = docker(FETCH, [paper, "--if-new"])
        if code != 0:
            log(f"{paper}: fetch failed (or no issue today), see above")
            failures += 1
            continue
        fetch_step = next((s for s in _status(config, run_id)["steps"] if s["name"] == FETCH.name), None)
        if fetch_step is None or fetch_step["started_at"] < started:
            log(f"{run_id}: already fetched before, left alone")
            continue
        failures += restart(config, docker, run_id) != 0
    return 1 if failures else 0


def restart(config: Config, docker: Docker, run_id: str, from_job: str | None = None) -> int:
    """Runs the jobs from `from_job`, or from the first one that hasn't
    succeeded, to the end. Stops at the first failure."""
    names = [j.name for j in JOBS]
    if from_job is not None:
        start = names.index(from_job)
    else:
        done = {s["name"] for s in _status(config, run_id)["steps"] if s["status"] == "succeeded"}
        start = next((i for i, name in enumerate(names) if name not in done), len(names))
    for job in JOBS[start:]:
        log(f"{run_id}: {job.name}")
        if docker(job, [run_id])[0] != 0:
            log(f"{run_id}: {job.name} failed -- restart with: run.py restart {run_id}")
            return 1
    log(f"{run_id}: done")
    return 0


def audio(docker: Docker, run_id: str) -> int:
    log(f"{run_id}: audio")
    code = docker(AUDIO, [run_id])[0]
    log(f"{run_id}: audio {'failed' if code else 'done'}")
    return code


def audio_requests(config: Config, docker: Docker) -> int:
    """The audio job for every run someone asked audio for. The request is
    deleted only when the job is over, success or not -- the backend shows
    "rendering" meanwhile and offers to ask again after a failure. Quiet
    when there's nothing to do (it runs every minute)."""
    failures = 0
    for request in sorted((config.data_dir / "issues").glob(f"*/{AUDIO_REQUEST_FILE_NAME}")):
        failures += audio(docker, request.parent.name) != 0
        request.unlink(missing_ok=True)
    return 1 if failures else 0


def _failed_job(config: Config, run_id: str) -> str | None:
    return next((s["name"] for s in _status(config, run_id)["steps"] if s["status"] == "failed"), None)


def import_issue(config: Config, docker: Docker, paper: str, date: str, on_run_id: Callable[[str], None]) -> str | None:
    """Fetch (unless the issue is there) and every job up to publish.
    Returns the error, None on success."""
    log(f"{paper} {date}: import")
    code, run_id = docker(FETCH, [paper, "--date", date, "--if-new"])
    if code != 0:
        # The fetch job's last line is its error, e.g. no issue that day.
        return f"fetch: {run_id}"
    on_run_id(run_id)
    if restart(config, docker, run_id) != 0:
        return f"{_failed_job(config, run_id) or 'a job'} failed -- restart with: run.py restart {run_id}"
    return None


def _rewrite(path: Path, **fields: str) -> None:
    # In place, not replaced: the file stays the backend's.
    body = json.loads(path.read_text())
    path.write_text(json.dumps(body | fields))


def _rewrite_run_id(path: Path, run_id: str) -> None:
    _rewrite(path, run_id=run_id)


def import_requests(config: Config, docker: Docker) -> int:
    """Imports every issue someone asked for, renaming its request file to
    show where it stands: .running, then gone, or .failed with the error.
    A .running one found here was cut off (the cron never overlaps itself),
    so it's taken up again. Quiet when there's nothing to do."""
    requests_dir = config.data_dir / IMPORT_REQUESTS_DIR_NAME
    pending = sorted(requests_dir.glob(f"*.{RUNNING}")) + sorted(requests_dir.glob(f"*.{REQUESTED}"))
    failures = 0
    for request in pending:
        running = request.rename(request.with_suffix(f".{RUNNING}"))
        body = json.loads(running.read_text())
        error = import_issue(config, docker, body["paper"], body["date"], partial(_rewrite_run_id, running))
        if error is None:
            running.unlink()
            continue
        log(f"{body['paper']} {body['date']}: import failed: {error}")
        failures += 1
        _rewrite(running, error=error)
        running.rename(running.with_suffix(f".{FAILED}"))
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("import-requests", help="import every issue it was asked for")
    daily_cmd = commands.add_parser("daily", help="fetch and run today's issue of each paper")
    daily_cmd.add_argument("papers", nargs="+", metavar="paper", help="a slug from config/papers.toml")
    commands.add_parser("audio-requests", help="render the audio of every issue it was asked for")
    audio_cmd = commands.add_parser("audio", help="render one issue's audio")
    audio_cmd.add_argument("run_id")
    restart_cmd = commands.add_parser("restart", help="continue one run")
    restart_cmd.add_argument("run_id")
    restart_cmd.add_argument("--from", dest="from_job", choices=[j.name for j in JOBS])
    args = parser.parse_args(argv)

    config = Config.from_env()
    if args.command == "import-requests":
        return import_requests(config, docker_run(config))
    if args.command == "daily":
        return daily(config, docker_run(config), args.papers)
    if args.command == "audio-requests":
        return audio_requests(config, docker_run(config))
    if args.command == "audio":
        return audio(docker_run(config), args.run_id)
    return restart(config, docker_run(config), args.run_id, args.from_job)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
