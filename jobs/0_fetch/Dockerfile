# Fetch job: downloads one issue into a new run dir. Build from the repo
# root, so the path dependency on shared/ resolves:
#   docker build -f jobs/0_fetch/Dockerfile -t hoerbote-fetch .

FROM python:3.14-slim

RUN pip install --no-cache-dir uv

WORKDIR /repo

# Manifests first (small, change rarely) for layer caching...
COPY jobs/0_fetch/pyproject.toml jobs/0_fetch/uv.lock jobs/0_fetch/
COPY shared/pyproject.toml shared/pyproject.toml

# ...then the actual source -- this stage's whole owned directory as a
# unit, no cherry-picked files from elsewhere.
COPY shared/ shared/
COPY config/ config/
COPY jobs/0_fetch/ jobs/0_fetch/

WORKDIR /repo/jobs/0_fetch
RUN uv sync --frozen --no-dev

ENV PATH="/repo/jobs/0_fetch/.venv/bin:${PATH}" DATA_ROOT="/data" CONFIG_DIR="/repo/config" PYTHONUNBUFFERED="1"

# Takes <paper> [--date ...] [--edition ...], not a run_id -- see run.py.
ENTRYPOINT ["python", "run.py"]
