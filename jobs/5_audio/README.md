# Audio job

Turns a published issue's narration into speech: one Ogg Opus file per segment,
for the whole issue at once. Importing an issue doesn't run it, because
it costs money per issue. It runs when someone asks for an issue's audio
in the web app (the runner starts it), or by hand.

Two speech engines do the rendering (`speech_engine.py`), picked with
`SPEECH_ENGINE`. Unlike the rest of the repo, they're named after the
tool: they're alternatives side by side, and another one would be
another file. Everything else (which segments need a take, saving,
the manifest) is the same for both (`run.py`).

- **`gemini`** (default, `gemini_tts.py`): Gemini Flash-Lite TTS with German
  storyteller voices, four of them alternating female and male, so you
  hear when the story changes. A paper can set its own speaking style
  (`speech_style` in `config/papers.toml`). All segments go into one
  Gemini Batch API job: half the price of one call per segment, and not
  subject to the per-minute TTS limit. It takes about 3 minutes (up to
  24 h in the worst case). A 29-page issue costs about 30 ct at Gemini's
  2026 introductory price, double that from January 2027.
- **`qwen3-tts`** (`qwen3_tts.py` + `qwen3_tts_gpu.py`): Qwen3-TTS (1.7B) on a
  [Modal](https://modal.com) L4 GPU, speaking in two voices (female,
  male) cloned from reference clips in `voices/`. The job itself runs
  where it always does; only the rendering goes to the GPU. A whole
  issue took about 9 minutes and cost 0.13 EUR (2026-10-16), close to
  Gemini in quality. Names and abbreviations are sometimes mispronounced.
  `speech_style` doesn't apply: the voice's tone comes from its clip.

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

Environment variables (a `.env` in this folder works too, see
`.env.example`):

| Variable | |
|---|---|
| `SPEECH_ENGINE` | `gemini` (default) or `qwen3-tts` |
| `GEMINI_API_KEY` | for `gemini`, from https://aistudio.google.com/apikey |
| `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | for `qwen3-tts`. A local run can use `~/.modal.toml` instead (`uvx modal token new`). |

## Qwen3-TTS's voices

`voices/voices.toml` lists the voices in the order they take turns, each
with its reference clip. The clips are Gemini's storyteller voices
reading texts of our own (never takes from an issue, which read newspaper
content). To render them, or to switch to another of the three texts:

    uv run --project jobs/5_audio python jobs/5_audio/make_voices.py [--use a|b|c]

It renders only candidates that aren't in `voices/candidates/` yet, a
few cents once. A changed clip changes the fingerprint of every take
read in that voice.

## Good to know

- A re-run only renders what's missing or changed: a segment that
  failed, new narration text, a new voice, style, model or engine.
  They're all part of each take's file name. Takes no longer needed are
  deleted, so switching engines replaces every take (copy `05_audio/`
  first to keep the old ones).
- If some segments fail, the job fails but keeps the others. Run it
  again to render just the missing ones.
- `gemini`: an interrupted run picks up the same batch again instead of
  paying for a second one (`05_audio/batch_job.json`).
- `qwen3-tts`: takes are saved as soon as all their sentences are back. Modal
  can stop a GPU container at any time (preemption) and runs the call
  again on a new one; each call holds only two batches of sentences, so
  that costs a minute or two, not the issue. A segment whose call fails
  for good is reported as failed like any other.
- `qwen3-tts`: a batch runs until its longest sentence is done, so sentences
  are batched by length across the whole issue, voices mixed. A sentence
  that doesn't stop is cut off at twice its expected length and rendered
  once more; if that happens again, the log says which.
- `qwen3-tts`: the GPU image (`Dockerfile.qwen3-tts`, built on Modal by
  `qwen3_tts_gpu.py`) holds the model weights. Changing the Dockerfile or
  the model rebuilds it, download included (several minutes, once);
  editing the code or a voice doesn't.

## Tests

    uv run --project jobs/5_audio --group dev pytest jobs/5_audio/tests/
