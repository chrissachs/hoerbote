# Audio job: renders an issue's narration segments to Ogg Opus. Build from the
# repo root, so the path dependency on shared/ resolves:
#   docker build -f jobs/5_audio/Dockerfile -t hoerbote-audio .
# SPEECH_ENGINE and the engine's credentials (GEMINI_API_KEY, or
# MODAL_TOKEN_ID / MODAL_TOKEN_SECRET) come in at `docker run --env-file`.

FROM python:3.14-slim

RUN pip install --no-cache-dir uv

WORKDIR /repo

# Manifests first (small, change rarely) for layer caching...
COPY jobs/5_audio/pyproject.toml jobs/5_audio/uv.lock jobs/5_audio/
COPY shared/pyproject.toml shared/pyproject.toml

# ...then the actual source -- this stage's whole owned directory as a
# unit, no cherry-picked files from elsewhere. .dockerignore keeps the
# .env (the API key) out of this layer.
COPY shared/ shared/
COPY jobs/5_audio/ jobs/5_audio/

WORKDIR /repo/jobs/5_audio
RUN uv sync --frozen --no-dev

# HOME: the Qwen3-TTS engine's modal client writes its config there; the
# runner starts this as the data dir's owner, who has no home in the image.
ENV PATH="/repo/jobs/5_audio/.venv/bin:${PATH}" DATA_ROOT="/data" HOME="/tmp" PYTHONUNBUFFERED="1"

ENTRYPOINT ["python", "run.py"]
