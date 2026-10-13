# Narration job

Writes a spoken overview of each page in German, from the articles on
it. Every sentence is tagged with the article it's about, which is how
the web app knows what to highlight.

Writes `03_rewritten/`: per page, a list of sentences with their
article. A page without real articles (e.g. a full-page ad) gets no
file.

The LLM is currently Gemini Flash-Lite (`LLM_MODEL_ID` in `stages.py`),
called through its batch API, which is half price. That takes minutes,
rarely hours. An interrupted run picks up the same batch again.

## Run it

With uv, from the repo root:

    uv run --project jobs/3_narration python jobs/3_narration/run.py <run_id>

Or with Docker:

    docker build -f jobs/3_narration/Dockerfile -t hoerbote-narration .
    docker run --rm --user "$(id -u):$(id -g)" -v "$(pwd)/data:/data" \
      -e GEMINI_API_KEY hoerbote-narration <run_id>

To read the result as one page, open
`data/issues/<run_id>/03_rewritten_readthrough.html` after:

    uv run --project jobs/3_narration python jobs/3_narration/render_narration.py <run_id>

## Configuration

Environment variables (a `.env` in this folder works too):

| Variable | |
|---|---|
| `GEMINI_API_KEY` | required, from https://aistudio.google.com/apikey |
| `NARRATION_TONE` | optional, overrides the paper's tone for a try-out |

The paper's settings come from `00_source.json`, set per paper in
`config/papers.toml`:

- `narration_tone`: `colloquial` (default), `formal`, `radio_host`,
  `storyteller` or `brief`. They're described in `TONES` in `stages.py`.
- `tone_prompt`: extra wording, e.g. "an occasional regional word".
- `narration_context`: `from_article` keeps context a modern listener
  needs (who a person was), but only what the article itself says.

## How it works

Two LLM steps (`stages.py`):

1. **Article step**, once per article: a clean headline, a short
   summary and a topic. Fragments that aren't real articles (teasers,
   stray captions, bare headlines) get an empty summary and are dropped.
2. **Page step**, once per page: weaves the page's summaries into one
   flowing text. Longer articles get more sentences.

Both steps are told not to add any fact that isn't in their input. The
article step's results are cached in `03_rewritten/cache/`, so trying
another tone only re-runs the page step. Editing a prompt invalidates
the cache by itself.

## Good to know

- The page step only sees summaries. A mistake in a summary therefore
  goes unnoticed, and the sentence tags are how to trace it back.
- Mixed-up input (two articles glued together) has to be fixed in the
  articles job, not left to the LLM.

## Tests

    uv run --project jobs/3_narration --group dev pytest jobs/3_narration/tests/

They use a fake LLM, so no key is needed.
