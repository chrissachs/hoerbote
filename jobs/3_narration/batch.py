"""Runs one LLMStage over many inputs via the Gemini Batch API -- half the
price of synchronous calls, in exchange for a turnaround of minutes up to
24h, which a once-a-day issue run doesn't mind.

Uses the same request (LLMStage.request_config, user content) and the
same parsing (LLMStage.parse) as a synchronous LLMStage.run, so the two
paths can't drift apart.

Any request the batch doesn't answer usably (a per-request error, or a
response that doesn't validate against the stage's response model) falls
back to that stage's synchronous run(), with its retry policy -- so one
bad item never fails the whole issue.

The job name is persisted in `job_file` while waiting, so a run that gets
interrupted mid-wait resumes polling the same job on re-run instead of
paying for a second one."""

import hashlib
import json
import logging
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from google import genai
from pydantic import ValidationError

from stages import LLM_MODEL_ID, LLMStage

log = logging.getLogger(__name__)

POLL_SECONDS = 30
_DONE_STATES = {"JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"}
_FAILED_STATES = {"JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}


def _request(stage: LLMStage, input) -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": stage.build_user_content(input)}]}],
        "config": stage.request_config(),
    }


def _fingerprint(requests: list[dict]) -> str:
    # default=str: response_schema is a class, not JSON -- its name is
    # enough here, since a schema change without a prompt or input change
    # never needs to tell two otherwise identical jobs apart.
    return hashlib.sha256(json.dumps([LLM_MODEL_ID, requests], sort_keys=True, default=str).encode()).hexdigest()[:12]


def _submit_or_resume(client: genai.Client, stage: LLMStage, requests: list[dict], job_file: Path) -> str:
    fingerprint = _fingerprint(requests)
    if job_file.exists():
        saved = json.loads(job_file.read_text())
        if saved["fingerprint"] == fingerprint:
            state = client.batches.get(name=saved["job"]).state.name
            if state not in _FAILED_STATES:
                log.info("%s: resuming batch job %s (%s)", stage.name, saved["job"], state)
                return saved["job"]
    job = client.batches.create(model=LLM_MODEL_ID, src=requests, config={"display_name": f"hoerbote {stage.name}"})
    job_file.parent.mkdir(parents=True, exist_ok=True)
    job_file.write_text(json.dumps({"job": job.name, "fingerprint": fingerprint}))
    log.info("%s: submitted batch job %s (%d requests)", stage.name, job.name, len(requests))
    return job.name


def run_batch[TIn, TOut](stage: LLMStage[TIn, Any, TOut], inputs: Sequence[TIn], job_file: Path) -> list[TOut]:
    """Outputs in the same order as `inputs`. Blocks until the batch job
    is done (polling every POLL_SECONDS)."""
    if not inputs:
        return []
    client = genai.Client()
    requests = [_request(stage, i) for i in inputs]
    job_name = _submit_or_resume(client, stage, requests, job_file)

    while True:
        job = client.batches.get(name=job_name)
        state = job.state.name
        if state in _DONE_STATES:
            break
        if state in _FAILED_STATES:
            job_file.unlink(missing_ok=True)
            raise RuntimeError(f"{stage.name}: batch job {job_name} ended in {state}: {job.error}")
        log.info("%s: batch job %s, waiting %ds...", stage.name, state, POLL_SECONDS)
        time.sleep(POLL_SECONDS)

    outputs: list[TOut] = []
    responses = job.dest.inlined_responses
    for input, item in zip(inputs, responses, strict=True):
        try:
            if item.error is not None:
                raise RuntimeError(item.error)
            outputs.append(stage.parse(input, item.response.text))
        except (RuntimeError, ValidationError, AttributeError, TypeError) as e:
            log.warning("%s: batch item failed (%r) -- retrying synchronously", stage.name, e)
            outputs.append(stage.run(input))
    job_file.unlink(missing_ok=True)
    return outputs
