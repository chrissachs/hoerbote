# Layout job

Finds the layout of every page: where the headlines, text columns,
pictures and captions are. It renders each page of `00_source.pdf` and
runs a vision model on it. It doesn't read the text: the articles job
matches the regions onto it afterwards.

Writes `01_layout/`: per page, its regions (`page{N}.layout.json`). The
page images the model sees aren't kept.

The model is currently [Surya 2](https://github.com/datalab-to/surya)
(set in `layout_model.py`). It needs a GPU for a whole issue. On a CPU
it takes minutes per page.

## Run it

On a GPU, which the pipeline does. It currently runs at
[Modal](https://modal.com), set up in `gpu_job.py`. It takes about
3 s per page plus a few minutes to start:

    uvx modal run jobs/1_layout/gpu_job.py --run-id <run_id>

On the CPU, for a page or two. With uv, from the repo root (this needs
llama.cpp's `llama-server` installed):

    uv run --project jobs/1_layout python jobs/1_layout/run.py <run_id>

Or with Docker, which includes `llama-server`. The cache mount keeps
the 1.5 GB of model weights between runs:

    docker build -f jobs/1_layout/Dockerfile -t hoerbote-layout .
    docker run --rm --user "$(id -u):$(id -g)" -v "$(pwd)/data:/data" \
      -v "$HOME/.cache/huggingface:/cache/huggingface" -e HF_HOME=/cache/huggingface \
      hoerbote-layout <run_id>

To see the result, every page with its regions drawn on top, open
`data/issues/<run_id>/01_layout_view.html` after:

    uv run --project jobs/1_layout python jobs/1_layout/debug_view.py <run_id>

## Configuration

Environment variables (a `.env` in this folder works too):

| Variable | |
|---|---|
| `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | GPU access, when started by the runner. A local `uvx modal` uses `~/.modal.toml` instead (`uvx modal token new`). |
| `LAYOUT_RENDER_DPI` | page render resolution, default 192 |
| `SURYA_INFERENCE_PARALLEL` | pages on the model at once, default 1 |

## Good to know

- A page the model fails on is retried once and then saved without
  regions, with a warning. If more than 10% of the pages fail, the job
  fails.
- Too low a resolution silently loses small text. Above ~150 DPI the
  model sees no extra detail, though.
- The GPU settings live in `gpu_job.py`, not in `Dockerfile.gpu`.
  Changing that file rebuilds the whole GPU image, model download
  included.

## Tests

    uv run --project jobs/1_layout --group dev pytest jobs/1_layout/tests/

The tests use a fake model, so they need no GPU.
