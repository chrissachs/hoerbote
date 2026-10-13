# Runner

Runs the pipeline, but only for what someone asked for in the web app,
because it costs money per issue. Every minute it looks for:

- issues to import (the backend leaves a `<paper>_<date>.requested` file
  in `data/import-requests/`): it fetches the issue and runs it through
  all jobs up to publish. It renames the file to `.running` meanwhile,
  deletes it when done, or renames it to `.failed` with the error.
- issues someone asked audio for (the backend leaves a
  `05_audio.requested` file in the issue's folder): it starts the audio
  job for them.

Each job runs in its own container, which the runner starts on the
host's Docker. There's no daily import anymore. The crontab has the line
to turn it back on.

A run that fails stays failed until you restart it, or ask for it again
in the web app, so a broken issue never runs up costs by retrying.

## Run it

From the repo root. Build the job images first. The runner starts them
but doesn't build them, so rebuild after changing a job:

    docker compose --profile jobs build

Start it:

    docker compose up -d runner

Import today's issue of some papers right away (slugs from
`config/papers.toml`):

    docker compose run --rm runner python run.py daily berliner-tageblatt

Continue a failed run at the job that failed, or at a given job:

    docker compose run --rm runner python run.py restart <run_id> [--from articles]

Render one issue's audio right away (about 3 minutes, ~30 ct for a
29-page issue):

    docker compose run --rm runner python run.py audio <run_id>

## Configuration

One optional environment variable, which compose passes on from the
shell or from a `.env` in the repo root:

| Variable | |
|---|---|
| `HOST_DATA_DIR` | the data folder's path on the host; found automatically |

The jobs get their own settings only from their `.env` files
(`jobs/1_layout/.env`, `jobs/3_narration/.env`, `jobs/5_audio/.env`),
which the runner hands to their containers.

## Tests

    uv run --project runner --group dev pytest runner/tests/
