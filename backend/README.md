# Backend

Serves the published issues, their audio and the web app. It renders no
audio itself: the [audio job](../jobs/5_audio/) does, when someone asks
for it.

## Run it

With uv, from the repo root. Build the web app first, because the
backend serves it:

    npm --prefix frontend ci && npm --prefix frontend run build
    uv run --project backend uvicorn app:app --app-dir backend --port 8001

Or with Docker, which builds the web app itself:

    docker compose up -d backend

Then open http://localhost:8001. Compose runs it as user 1000, so it
can write into `data/`. If `data/` belongs to someone else, export
`HOST_UID` and `HOST_GID` first.

## Configuration

Environment variables (a `.env` in this folder works too):

| Variable | |
|---|---|
| `ACCESS_PASSWORD` | required, the shared password |
| `DATA_ROOT` | where `issues/` and `import-requests/` are, default `./data` (`/data` in the image) |
| `CONFIG_DIR` | where `papers.toml` is, default `./config` (the Dockerfile copies it in) |
| `FRONTEND_DIR` | where the web app's build is, default `../frontend/dist` |

## API

Interactive docs at http://localhost:8001/api/docs.

## Access

- Without logging in, you see only the issues whose rights statement
  allows showing them publicly (`rights.open` in `00_source.json`). The
  others answer 404, as if they didn't exist.
- One password for everyone, no accounts. Logging in sets a cookie that
  lasts a year, and shows every issue.
- Share `https://<host>/#key=<password>` to log someone in with one
  click. The key never reaches the server's logs.
- Changing `ACCESS_PASSWORD` logs everyone out.
- Anonymous visitors only get the public paths (`PUBLIC_PATHS` in
  `access.py`: login, logout, session, the web app's files, the API docs)
  and reads under `/api/issues`, where every route checks the rights. A
  new route anywhere else, and any write (like asking for audio), needs
  the login automatically.

## Audio

`POST /api/issues/<run_id>/audio` (logged in only) asks for an issue's
audio: it writes `05_audio.requested` into the run's folder. The runner
looks for these every minute and starts the audio job, which takes about
3 minutes. `GET` on the same path says where that stands, and the web app
asks every 10 seconds while it waits.

Without the runner (e.g. locally), nothing picks the request up. Run the
audio job yourself, or with the runner's `audio` command.

## Imports

`POST /api/imports` with `{"paper", "date"}` (logged in only) asks for
an issue: it writes `<paper>_<date>.requested` into
`data/import-requests/`. The runner looks for these every minute, fetches
the issue and runs every job up to publish, about 10 minutes. It renames
the file meanwhile, so `GET /api/imports` can tell: `.running` (with the
job at work), gone when the issue is published, `.failed` with the error.
`DELETE /api/imports/<paper>/<date>` forgets a failed one. The papers
are those in `config/papers.toml`, with their title and default date. Unlike
everything under `/api/issues`, all of this needs the login, reads too.

The web app shows the form below the issue list, and asks every 10
seconds while an import is on its way.

Asking for an issue that's already there costs nothing: the runner only
runs the jobs that haven't succeeded, so it's also how a failed run is
retried from the web app.

## Good to know

- Audio counts only while it matches the published text. After the
  narration or publish job runs again, the issue has no audio until
  someone asks for it again.
- The backend reads the web app's file list at startup, so restart it
  after rebuilding the web app.
- The cookie is `Secure`: browsers accept it on `http://localhost`, but
  curl doesn't send it back over plain HTTP.

## Tests

    uv run --project backend --group dev pytest backend/tests/
