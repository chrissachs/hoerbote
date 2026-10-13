# Layout job on the CPU (slow: minutes per page; see Dockerfile.gpu for the
# GPU version). The only job with model dependencies (torch, surya-ocr).
# Build from the repo root, so the path dependency on shared/ resolves:
#   docker build -f jobs/1_layout/Dockerfile -t hoerbote-layout .

# surya-ocr's CPU inference backend shells out to a separate llama-server
# binary (llama.cpp) -- not a Python package, so not something `uv sync`
# can install. Pulled from llama.cpp's own official image rather than
# downloading/building it ourselves.
FROM ghcr.io/ggml-org/llama.cpp:server AS llama_cpp

FROM python:3.14-slim

# surya-ocr pins pillow<11, and pillow 10.x has no prebuilt wheel yet for
# this Python version -- these are needed to build it from source.
# libssl3/libgomp1 are runtime dependencies of llama-server (see COPY
# below), not present in this base image by default.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential zlib1g-dev libjpeg-dev \
    libssl3 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=llama_cpp /app/ /opt/llama-cpp/
ENV PATH="/opt/llama-cpp:${PATH}" LLAMA_CPP_BINARY="/opt/llama-cpp/llama-server" \
    LD_LIBRARY_PATH="/opt/llama-cpp"

RUN pip install --no-cache-dir uv

WORKDIR /repo

# Manifests first (small, change rarely) for layer caching...
COPY jobs/1_layout/pyproject.toml jobs/1_layout/uv.lock jobs/1_layout/
COPY shared/pyproject.toml shared/pyproject.toml

# ...then the actual source (path dependency needs real files to install).
COPY shared/ shared/
COPY jobs/1_layout/ jobs/1_layout/

WORKDIR /repo/jobs/1_layout
RUN uv sync --frozen --no-dev

# HOME must be writable regardless of which UID `docker run --user` picks
# (an arbitrary numeric UID has no passwd entry, so $HOME would otherwise
# resolve to `/`) -- surya-ocr needs it for its own inter-process sentinel
# cache (~/.cache/datalab/surya), separate from the HF_HOME weight cache.
ENV PATH="/repo/jobs/1_layout/.venv/bin:${PATH}" DATA_ROOT="/data" PYTHONUNBUFFERED="1" HOME="/tmp"

ENTRYPOINT ["python", "run.py"]
