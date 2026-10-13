# Fetch job

Downloads one issue of a newspaper and starts a new run for it. It's the
only job that takes a paper instead of a run_id, and every run starts
here: the other jobs need its `00_source.json`. It creates the run_id
(`<paper>-<edition>-<date>`) and prints it as its last line.

Writes to `data/issues/<run_id>/`:

- `00_source.pdf`: the issue
- `00_page_text/`: OCR text per page (ALTO XML), if the archive has it
- `00_source.json`: where it came from, its rights, and how to narrate it

## Run it

With uv, from the repo root:

    uv run --project jobs/0_fetch jobs/0_fetch/run.py berliner-tageblatt

Or with Docker:

    docker build -f jobs/0_fetch/Dockerfile -t hoerbote-fetch .
    docker run --rm --user "$(id -u):$(id -g)" -v "$(pwd)/data:/data" hoerbote-fetch berliner-tageblatt

Options: `--date 1926-10-08` (default: today minus the paper's
`years_back`, 100 for historic papers), `--edition morning`,
`--dry-run` (look up only, download nothing), `--if-new` (skip an issue
that is already there).

It reads the papers from `config/papers.toml`, no other configuration
is needed.

## Adding a paper

Papers are tables in [`config/papers.toml`](../../config/papers.toml),
keyed by slug. Each one names a provider, how that provider finds an
issue, the editions, and optional narration and speech settings.
`shared/papers.py` describes every field. Papers you'd rather not commit
go into a gitignored `config/papers_local.toml` (see
`papers_local.example.toml`).

The backend reads the same file to offer the papers in the web app's
import form. The Docker images copy `config/` when they're built, so
rebuild the fetch and backend images after adding a paper.

Providers so far:

- `ddb`: the Deutsches Zeitungsportal. Any paper there, by its ZDB id,
  with OCR text and a rights statement.
- `url`: a PDF at a predictable URL, e.g.
  `https://example.org/epaper/{date:%Y%m%d}.pdf`. Rights count as not
  open.

A new archive is a new provider (`provider.py`): `find` looks an issue
up, `download` writes the files.

## Good to know

- An issue whose rights aren't open is fetched anyway, with a warning.
  It must not be shown publicly.

## Tests

    uv run --project jobs/0_fetch --group dev pytest jobs/0_fetch/tests/
