# syntax=docker/dockerfile:1
# (A current Dockerfile frontend, whatever the Docker version: ADD
# --checksum below needs one newer than older engines bundle.)

# Pipeline runner: supercronic (a cron for containers) runs run.py, which
# starts each job's image on the host's Docker (socket mounted, see
# compose.yaml) for what was asked for in the web app. Build from the
# repo root:
#   docker build -f runner/Dockerfile -t hoerbote-runner .

FROM docker:29-cli AS docker-cli

FROM python:3.14-slim

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
# SHA-1 as published with the release, e63c11a9726b775a6a11801e81af4f3fb926aa68.
ADD --chmod=755 --checksum=sha256:a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1 \
    https://github.com/aptible/supercronic/releases/download/v0.2.49/supercronic-linux-amd64 \
    /usr/local/bin/supercronic

WORKDIR /runner
COPY runner/run.py runner/crontab ./

ENV PYTHONUNBUFFERED="1"
# By hand: docker compose run --rm runner python run.py restart <run_id>
CMD ["supercronic", "/runner/crontab"]
