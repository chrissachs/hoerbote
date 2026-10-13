# Publish job: reshapes articles + narration into frontend-ready JSON. Build
# from the repo root, so the path dependency on shared/ resolves:
#   docker build -f jobs/4_publish/Dockerfile -t hoerbote-publish .

FROM python:3.14-slim

RUN pip install --no-cache-dir uv

WORKDIR /repo

# Manifests first (small, change rarely) for layer caching...
COPY jobs/4_publish/pyproject.toml jobs/4_publish/uv.lock jobs/4_publish/
COPY shared/pyproject.toml shared/pyproject.toml

# ...then the actual source -- this stage's whole owned directory as a
# unit, no cherry-picked files from elsewhere.
COPY shared/ shared/
COPY jobs/4_publish/ jobs/4_publish/

WORKDIR /repo/jobs/4_publish
RUN uv sync --frozen --no-dev

ENV PATH="/repo/jobs/4_publish/.venv/bin:${PATH}" DATA_ROOT="/data" PYTHONUNBUFFERED="1"

ENTRYPOINT ["python", "run.py"]
