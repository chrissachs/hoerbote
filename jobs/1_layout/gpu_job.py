"""Runs the layout job for one issue on a hosted GPU (Modal, an L4):
3.3 s per page, ~7.5 min for a 58-page issue including startup.

    uvx modal run jobs/1_layout/gpu_job.py --run-id <run_id>

Uses DATA_ROOT/issues/<run_id>/ (default: the repo's data/). Uploads
00_source.pdf (+ status.json if present) to a persistent volume, starts the
inference server (vLLM) on the GPU, runs `run.py <run_id>` against it
unchanged (in its own Python 3.14 venv, built from Dockerfile.gpu), stops
the server, then downloads 01_layout/ and the updated status.json. Like
run.py itself, safe to re-invoke: it overwrites 01_layout/."""

import json
import os
import time
from pathlib import Path

import modal

REPO_ROOT = Path(__file__).resolve().parents[2]
# The local data dir: DATA_ROOT as for every job (the runner's container
# sets /data), else the repo's data/.
LOCAL_DATA = Path(os.environ.get("DATA_ROOT", REPO_ROOT / "data"))
REMOTE_DATA = "/data"
STAGE_DIR = "/repo/jobs/1_layout"
# Outputs (01_layout/ + status.json) are fetched as this one archive: each
# Volume download costs ~0.8 s regardless of size (measured 2026-10-08), so
# one file per page spent more time on that than on transfer.
OUTPUT_BUNDLE = "layout_outputs.tar"
MODEL = "datalab-to/surya-ocr-2"
SERVER_PORT = 8000

# Settings we tune live here, not in Dockerfile.gpu, where any change would
# rebuild everything incl. weights.
#
# The inference server: Surya's own vLLM launch (surya/inference/backends/
# vllm.py + settings.py) with its L4 sizing (24 GB -> 32 sequences, 8192
# batched tokens). max_pixels matches what Surya sends (~6.29 MP).
SERVER_ARGS = [
    "--served-model-name",
    MODEL,  # Surya checks this matches exactly
    "--dtype",
    "bfloat16",
    "--max-model-len",
    "18000",
    "--max-num-seqs",
    "32",
    "--max-num-batched-tokens",
    "8192",
    "--gpu-memory-utilization",
    "0.85",
    "--enable-prefix-caching",
    "--mm-processor-kwargs",
    json.dumps({"min_pixels": 3136, "max_pixels": 6291456}),
    "--speculative-config",
    json.dumps({"method": "mtp", "num_speculative_tokens": 2}),
    "--no-enforce-eager",
    "--disable-uvicorn-access-log",  # one line per page request otherwise
    "--port",
    str(SERVER_PORT),
]
# run.py's environment. SURYA_INFERENCE_PARALLEL must be set: run.py falls
# back to its CPU workaround (1) otherwise.
RUN_ENV = {
    # Surya scales pages to ~6.29 MP, about 151 DPI for a 992 pt wide page;
    # rendering higher only costs time (see layout_cache.LAYOUT_RENDER_DPI).
    "LAYOUT_RENDER_DPI": "152",
    "SURYA_INFERENCE_BACKEND": "vllm",
    "SURYA_INFERENCE_URL": f"http://127.0.0.1:{SERVER_PORT}/v1",
    # Pages run.py keeps on the model at once (of the server's 32 sequences).
    "SURYA_INFERENCE_PARALLEL": "16",
    # Output limit per page. Surya's default (3072) cut off a dense page
    # mid-answer (2026-10-08: page 42 of 2026-10-02, ~200 regions at ~16
    # tokens each). Not much higher, though: a page that loops runs to this
    # limit, and Surya retries it up to 3 times (~95 tok/s for a lone
    # request on the L4 with vLLM, so ~45 s per attempt at 4096).
    "SURYA_MAX_TOKENS_LAYOUT": "4096",
    # Unbuffered, so per-page progress streams to the caller's terminal live.
    "PYTHONUNBUFFERED": "1",
}
# Give up on the server when it isn't healthy after this long (warm start
# ~3 min, 2026-10-08), or has printed nothing for this long (e.g. its engine
# process was killed silently, which happened in Colab, and the API process
# just waits).
STARTUP_LIMIT_S = 12 * 60
SILENCE_LIMIT_S = 5 * 60

# Dependencies + weights come from the Dockerfile; the source is layered on
# top as separate, separately cached steps, so a code edit only reruns those
# (seconds) instead of the whole Dockerfile (see its comment). No
# add_python: the vLLM image's own Python (in /usr/local, where add_python
# would copy another one) runs this file.
SOURCE_IGNORE = ["**/.venv", "**/__pycache__", "**/.pytest_cache", "**/tests", "**/.env", "Dockerfile*"]
image = (
    modal.Image.from_dockerfile(Path(__file__).parent / "Dockerfile.gpu", context_dir=REPO_ROOT)
    .add_local_dir(REPO_ROOT / "shared", "/repo/shared", copy=True, ignore=SOURCE_IGNORE)
    .add_local_dir(Path(__file__).parent, STAGE_DIR, copy=True, ignore=SOURCE_IGNORE)
    .run_commands(f"cd {STAGE_DIR} && uv sync --frozen --no-dev --python 3.14 --managed-python")
)
volume = modal.Volume.from_name("hoerbote-data", create_if_missing=True)
# vLLM's compiled kernels; reusing them is most of the difference between a
# cold and a warm start.
compile_cache = modal.Volume.from_name("hoerbote-inference-cache", create_if_missing=True)
app = modal.App("hoerbote-layout", image=image)


# cpu: Modal only guarantees 0.125 cores by default (more only if the worker
# has some spare), and the server's image preprocessing, scheduling and
# JSON-schema checks per token run on the CPU, as does run.py's rendering.
# The first vLLM run (2026-10-08) looked CPU-starved: ~30 tok/s per request
# with 10 running.
@app.function(gpu="L4", cpu=8.0, volumes={REMOTE_DATA: volume, "/root/.cache/vllm": compile_cache}, timeout=25 * 60)
def detect(run_id: str) -> str | None:
    """Returns None if run.py succeeded, else what failed. A run.py failure
    doesn't raise, so the pages that did succeed (and status.json with the
    error) are still committed and downloaded. A server that doesn't come up
    raises: run.py never ran, nothing to download."""
    import os
    import subprocess

    volume.reload()
    server = _start_server()
    try:
        result = subprocess.run(
            [f"{STAGE_DIR}/.venv/bin/python", "run.py", run_id],
            cwd=STAGE_DIR,
            env={**os.environ, **RUN_ENV},
        )
    finally:
        _stop(server)
        compile_cache.commit()
        _bundle_outputs(run_id)
        volume.commit()
    return None if result.returncode == 0 else f"run.py exited with code {result.returncode}"


def _bundle_outputs(run_id: str) -> None:
    import tarfile

    issue_dir = Path(REMOTE_DATA) / "issues" / run_id
    with tarfile.open(issue_dir / OUTPUT_BUNDLE, "w") as tar:
        for name in ("01_layout", "status.json"):
            if (issue_dir / name).exists():
                tar.add(issue_dir / name, arcname=name)


def _start_server():
    """Starts vLLM and waits until it's healthy; raises (with the log tail)
    if it exits, hangs or takes too long instead."""
    import os
    import subprocess

    t0 = time.monotonic()
    env = {
        **os.environ,
        # Weights are baked into the image; offline keeps vLLM from still
        # asking the Hub for metadata on every start.
        "HF_HUB_OFFLINE": "1",
        # Triton's compiled kernels (this model's linear-attention kernels
        # among them) next to vLLM's own compile cache on the volume. Not
        # there by default (~/.triton/cache), so every start recompiled them:
        # likely most of the 92 s "initial profiling/warmup run" (2026-10-08).
        "TRITON_CACHE_DIR": "/root/.cache/vllm/triton",
    }
    proc = subprocess.Popen(
        ["vllm", "serve", MODEL, *SERVER_ARGS],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    output = _ServerOutput(proc)
    ready_s, why = _wait_for_health(proc, output, t0)
    if ready_s is None:
        _stop(proc)
        tail = "\n".join(output.lines()[-40:])
        raise RuntimeError(f"inference server didn't start: {why}\n--- last log lines ---\n{tail}")
    print(f"=== inference server ready after {ready_s:.0f}s")
    return proc


class _ServerOutput:
    """Streams the server's output to our stdout as it comes (so it shows
    live in the caller's terminal, between run.py's progress lines), keeps
    it for an error report, and records when it last printed anything. Reads
    raw chunks, not lines, so progress bars that redraw with \\r count as
    activity too."""

    def __init__(self, proc) -> None:
        import threading

        self.chunks: list[bytes] = []
        self.last_output = time.monotonic()
        self._proc = proc
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        import os
        import sys

        fd = self._proc.stdout.fileno()
        while chunk := os.read(fd, 4096):
            self.chunks.append(chunk)
            self.last_output = time.monotonic()
            sys.stdout.buffer.write(chunk)
            sys.stdout.flush()

    def lines(self) -> list[str]:
        return b"".join(self.chunks).decode(errors="replace").replace("\r", "\n").splitlines()


def _wait_for_health(proc, output: _ServerOutput, t0: float) -> tuple[float | None, str]:
    """Polls /health until it answers. Returns (seconds until healthy or
    None, why it stopped): also stops when the server exits, takes too long
    overall, or goes silent, instead of always running into the timeout."""
    import urllib.request

    while True:
        elapsed = time.monotonic() - t0
        if (code := proc.poll()) is not None:
            return None, f"server exited early with code {code}"
        if elapsed > STARTUP_LIMIT_S:
            return None, f"not healthy after {STARTUP_LIMIT_S}s"
        if (silent := time.monotonic() - output.last_output) > SILENCE_LIMIT_S:
            return None, f"no output for {silent:.0f}s (hung? e.g. engine process killed)"
        try:
            if urllib.request.urlopen(f"http://127.0.0.1:{SERVER_PORT}/health", timeout=2).status == 200:
                return elapsed, "healthy"
        except Exception:
            pass
        time.sleep(2)


def _stop(proc) -> None:
    """Stops the server and everything it spawned (vLLM runs its engine in
    a child process, which must not outlive the job)."""
    import os
    import signal
    import subprocess

    for sig, wait in ((signal.SIGTERM, 30), (signal.SIGKILL, 10)):
        try:
            os.killpg(proc.pid, sig)
            proc.wait(timeout=wait)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            continue


def _upload(run_id: str) -> None:
    local = LOCAL_DATA / "issues" / run_id
    with volume.batch_upload(force=True) as batch:
        for name in ("00_source.pdf", "status.json"):
            if (local / name).exists():
                batch.put_file(local / name, f"issues/{run_id}/{name}")


def _download(run_id: str) -> None:
    """Fetches the output bundle, unpacks it next to the issue's folder, then
    swaps 01_layout/ in whole. So the local folder is never half-written
    (even if the download breaks off), and it mirrors the remote one rather
    than merging into it: a stale local layout cache would hide a page the
    remote run couldn't save from the articles job."""
    import tarfile
    import tempfile

    local = LOCAL_DATA / "issues" / run_id
    with tempfile.TemporaryDirectory(dir=local, prefix=".download-") as tmp:
        tmp = Path(tmp)
        _download_file(f"issues/{run_id}/{OUTPUT_BUNDLE}", tmp / OUTPUT_BUNDLE)
        with tarfile.open(tmp / OUTPUT_BUNDLE) as tar:
            tar.extractall(tmp, filter="data")
        if (tmp / "01_layout").exists():
            if (local / "01_layout").exists():
                (local / "01_layout").rename(tmp / "01_layout.previous")  # removed with tmp
            (tmp / "01_layout").rename(local / "01_layout")
        if (tmp / "status.json").exists():
            (tmp / "status.json").replace(local / "status.json")


def _download_file(remote: str, local: Path) -> None:
    with open(local, "wb") as f:
        for chunk in volume.read_file(remote):
            f.write(chunk)


@app.local_entrypoint()
def main(run_id: str) -> None:
    if not (LOCAL_DATA / "issues" / run_id / "00_source.pdf").exists():
        raise SystemExit(f"missing {LOCAL_DATA}/issues/{run_id}/00_source.pdf")
    _upload(run_id)
    error = detect.remote(run_id)
    _download(run_id)
    print(f"01_layout/ downloaded to {LOCAL_DATA}/issues/{run_id}/")
    if error:
        raise SystemExit(f"layout detection failed ({error}), see {LOCAL_DATA}/issues/{run_id}/status.json")
