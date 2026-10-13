#!/usr/bin/env bash
# Lint + tests for the whole repo: ruff over all Python, oxlint + tsc for
# the frontend, and every Python project's tests (each is its own uv
# project, so one pytest run per project). Exits non-zero if anything
# fails. Also the pre-commit hook (scripts/hooks/pre-commit).
set -uo pipefail
cd "$(dirname "$0")/.."

RUFF="uvx --quiet ruff@0.17.0"
failed=()

check() {
    local name=$1
    shift
    printf '== %s: ' "$name"
    if output=$("$@" 2>&1); then
        [[ -n $output ]] && echo "$output" | tail -n 1 || echo "ok"
    else
        echo "FAILED"
        echo "$output" | tail -n 30
        failed+=("$name")
    fi
}

check "ruff check" $RUFF check --quiet .
check "ruff format" $RUFF format --check --quiet .
if [[ -d frontend/node_modules ]]; then
    check "frontend lint" npm --prefix frontend run --silent lint
    check "frontend types" npx --prefix frontend tsc -b frontend
else
    echo "== frontend: skipped (npm --prefix frontend ci first)"
fi
for project in shared jobs/*/ backend runner; do
    project=${project%/}
    check "$project" uv run --quiet --project "$project" --group dev pytest "$project" -q -p no:warnings
done

if (( ${#failed[@]} )); then
    echo "failed: ${failed[*]}"
    exit 1
fi
