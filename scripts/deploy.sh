#!/usr/bin/env bash
# Deploys the current main on the server: pull, build every image, bring
# the backend and runner up to date, drop the old images. Run it on the
# server, from anywhere in the repo.
#
# It waits for a running job before restarting the runner: the job's
# container would outlive the runner, and the new runner would start the
# same job again on the same run.
set -euo pipefail
cd "$(dirname "$0")/.."

# The job images (compose.yaml, profile "jobs"), as the runner starts them.
JOB_IMAGES='^hoerbote-(fetch|layout-modal|articles|narration|publish|audio)(:|$)'

# Not in git, so not pulled: the backend won't start without its .env, and
# a job without its .env fails at its first API call.
[[ -f backend/.env ]] || { echo "backend/.env is missing (see backend/.env.example)"; exit 1; }
for env in jobs/1_layout/.env jobs/3_narration/.env jobs/5_audio/.env; do
    [[ -f $env ]] || echo "warning: $env is missing, that job will fail"
done

git pull --ff-only
docker compose --profile '*' build

# Checked after the build (minutes) rather than before, to keep the
# window small in which the runner could start a new job.
while docker ps --format '{{.Image}}' | grep -Eq "$JOB_IMAGES"; do
    echo "waiting for a running job to finish: $(docker ps --format '{{.Image}}' | grep -E "$JOB_IMAGES" | tr '\n' ' ')"
    sleep 30
done

docker compose up -d
docker image prune -f
docker compose ps
