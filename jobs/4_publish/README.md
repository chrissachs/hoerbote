# Publish job

Prepares an issue for the web app: combines the articles and the
narration into JSON the backend serves as-is, and renders the page
images. No model, no network. It takes seconds per issue.

Writes `04_published/`:

- `issue.json`: paper, date, credit line, and the list of pages
- `page{N}.json`: the page's articles (position as fractions of the
  page) and its narration segments
- `page{N}.webp` and `page{N}.thumb.webp`: the page, large and small

A **segment** is a run of sentences about one article. It's the unit
the audio job turns into speech, and the voice changes between segments.

## Run it

Needs the articles and narration jobs' output. With uv, from the repo
root:

    uv run --project jobs/4_publish python jobs/4_publish/run.py <run_id>

Or with Docker:

    docker build -f jobs/4_publish/Dockerfile -t hoerbote-publish .
    docker run --rm --user "$(id -u):$(id -g)" -v "$(pwd)/data:/data" hoerbote-publish <run_id>

No configuration is needed.

## Good to know

- The new output replaces the old one only when it's complete, so a
  failed run leaves the previous version online.
- If the articles job ran again after the narration job, this job fails
  and asks you to re-run the narration.

## Tests

    uv run --project jobs/4_publish --group dev pytest jobs/4_publish/tests/
