# Narration job: LLM API calls only, no GPU. Build from the repo root, so
# the path dependency on shared/ resolves:
#   docker build -f jobs/3_narration/Dockerfile -t hoerbote-narration .
# GEMINI_API_KEY (and optionally NARRATION_TONE) come in at `docker run -e`.

FROM python:3.14-slim

RUN pip install --no-cache-dir uv

WORKDIR /repo

# Manifests first (small, change rarely) for layer caching...
COPY jobs/3_narration/pyproject.toml jobs/3_narration/uv.lock jobs/3_narration/
COPY shared/pyproject.toml shared/pyproject.toml

# ...then the actual source. The path dependency needs real files present
# to install (no PyPI/registry involved), and this stage's whole owned
# directory is copied as a unit -- no cherry-picked files from elsewhere.
# .dockerignore excludes jobs/3_narration/.env, so the real API key
# never ends up in this layer.
COPY shared/ shared/
COPY jobs/3_narration/ jobs/3_narration/

WORKDIR /repo/jobs/3_narration
RUN uv sync --frozen --no-dev

ENV PATH="/repo/jobs/3_narration/.venv/bin:${PATH}" DATA_ROOT="/data" PYTHONUNBUFFERED="1"

ENTRYPOINT ["python", "run.py"]
