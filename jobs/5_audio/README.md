# Audio job

Turns a published issue's narration into speech: one Ogg Opus file per segment,
for the whole issue at once. Importing an issue doesn't run it, because
it costs money per issue. It runs when someone asks for an issue's audio
in the web app (the runner starts it), or by hand.

Text-to-speech is Gemini Flash-Lite TTS with German storyteller voices
(set in `speech.py`). The voices alternate between female and male, so
you hear when the story changes. A paper can set its own speaking style
(`speech_style` in `config/papers.toml`).

All segments go into one Gemini Batch API job. That's half the price of
one call per segment and not subject to the per-minute TTS limit. It
takes about 3 minutes (up to 24 h in the worst case). A 29-page issue
costs about 30 ct at Gemini's 2026 introductory price, double that from
January 2027.

Writes `05_audio/`:

- `page{N}/segment{K}-{fingerprint}.ogg`: one take per segment, Opus at
  ~19 kbps (about 60 KB for 25 s of speech). Plays in every major browser,
  Safari since 18.4
- `audio.json`: which take belongs to which segment, with a hash of the
  text it was rendered from. The backend serves only what's listed there
  and still matches the published text.

## Run it

Needs the publish job's output. With uv, from the repo root:

    uv run --project jobs/5_audio python jobs/5_audio/run.py <run_id>

Or with Docker:

    docker build -f jobs/5_audio/Dockerfile -t hoerbote-audio .
    docker run --rm --user "$(id -u):$(id -g)" -v "$(pwd)/data:/data" \
      --env-file jobs/5_audio/.env hoerbote-audio <run_id>

## Configuration

Environment variables (a `.env` in this folder works too):

| Variable | |
|---|---|
| `GEMINI_API_KEY` | required, from https://aistudio.google.com/apikey |

## Good to know

- A re-run only renders what's missing or changed: a segment that
  failed, new narration text, or a new voice, style or model. They're
  all part of each take's file name. Takes no longer needed are deleted.
- If some segments fail, the job fails but keeps the others. Run it
  again to render just the missing ones.
- An interrupted run picks up the same batch again instead of paying for
  a second one (`05_audio/batch_job.json`).

## Tests

    uv run --project jobs/5_audio --group dev pytest jobs/5_audio/tests/
