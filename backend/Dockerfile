# Backend: serves the published issues, their audio and the frontend's
# build; a shared-password cookie unlocks what isn't openly licensed.
# Build from the repo root:
#   docker build -f backend/Dockerfile -t hoerbote-backend .

# The frontend is only built here; Node doesn't end up in the image.
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14-slim

RUN pip install --no-cache-dir uv

WORKDIR /repo

COPY backend/pyproject.toml backend/uv.lock backend/
COPY shared/pyproject.toml shared/pyproject.toml

COPY shared/ shared/
# The papers the import form offers.
COPY config/ config/
COPY backend/ backend/
# Where app.py's FRONTEND_DIR default looks.
COPY --from=frontend /frontend/dist frontend/dist

WORKDIR /repo/backend
RUN uv sync --frozen --no-dev

ENV PATH="/repo/backend/.venv/bin:${PATH}" DATA_ROOT="/data" CONFIG_DIR="/repo/config" PYTHONUNBUFFERED="1"

EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
