# Articles job (CPU only; reads the layout job's cache, never runs the model).
# Build from the repo root, so the path dependency on shared/ resolves:
#   docker build -f jobs/2_articles/Dockerfile -t hoerbote-articles .

FROM python:3.14-slim

RUN pip install --no-cache-dir uv

WORKDIR /repo

# Manifests first (small, change rarely) for layer caching...
COPY jobs/2_articles/pyproject.toml jobs/2_articles/uv.lock jobs/2_articles/
COPY shared/pyproject.toml shared/pyproject.toml

# ...then the actual source. The path dependency needs real files present
# to install (no PyPI/registry involved), and this stage's whole owned
# directory is copied as a unit -- no cherry-picked files from elsewhere.
COPY shared/ shared/
COPY jobs/2_articles/ jobs/2_articles/

WORKDIR /repo/jobs/2_articles
RUN uv sync --frozen --no-dev

ENV PATH="/repo/jobs/2_articles/.venv/bin:${PATH}" DATA_ROOT="/data" PYTHONUNBUFFERED="1"

ENTRYPOINT ["python", "run.py"]
