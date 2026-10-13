# hoerbote -- agent notes

Turns a newspaper issue into a narration you listen to page by page.
Start with [README.md](README.md): what each folder does, how the jobs
connect, how to run things. Every job, `backend/`, `runner/` and
`frontend/` has its own README with how it works and its gotchas. This
file only adds what matters when changing the code.

## Before you edit

- `scripts/check.sh` runs ruff (`ruff.toml`), the frontend's oxlint +
  tsc, and every project's tests. It's the pre-commit hook once
  `git config core.hooksPath scripts/hooks` is set. Otherwise run it
  yourself before committing.
- Run a project's commands from the repo root with
  `uv run --project <project> ...`, not after `cd`-ing into it, so `data/`
  resolves.
- After editing `shared/`, run
  `uv sync --project <project> --reinstall-package hoerbote-shared` for
  every project you then run. Otherwise it keeps the old copy.
- Python >= 3.14 everywhere.

## Boundaries

- Jobs exchange data only through files in `data/issues/<run_id>/`. Each
  job's Dockerfile copies `shared/` and its own folder as whole
  directories, so a job can't import another job's code. If two jobs
  need something, it goes into `shared/`, which holds only the on-disk
  formats.
- Every job takes only a run_id (fetch creates one) and overwrites its
  own output. Keep it that way: re-running is how runs get resumed.
- Name folders, files and identifiers after the role, not the tool
  (`1_layout`, `layout_model.py`, not `surya`), so the tool can be
  swapped. Naming the tool in comments is fine.
- `config/` is copied whole into the images that read it (fetch,
  backend), like `shared/`.
- No rules for one specific newspaper in code. Per-paper behaviour is
  config in `config/papers.toml` (or the gitignored
  `papers_local.toml`), passed on via `00_source.json`.
- A non-Python file a module reads at runtime (e.g.
  `viewer_template.html`) must be in what its Dockerfile copies.

## Costs and data

- The layout job (Modal GPU), the narration job and the audio job
  (Gemini) cost money per run. Don't start them on a whole issue unless
  asked. The layout job on CPU and the other jobs are free.
- `data/` and `extracted/` hold copyrighted newspaper content and are
  gitignored. Never commit anything from them. The only committed
  newspaper content is the public-domain fixture in
  `jobs/2_articles/tests/fixtures/`.
- `docker run` against `data/` needs `--user "$(id -u):$(id -g)"`.

## Checking the frontend

Build it, then start a backend on a spare port, because the backend
reads the build's file list at startup:

    npm --prefix frontend run build
    ACCESS_PASSWORD=test-pw uv run --project backend uvicorn app:app --app-dir backend --port 8011

Log in via `http://localhost:8011/#key=test-pw`. Restart the backend
after every rebuild.
