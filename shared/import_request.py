"""The backend -> runner contract for importing an issue: one file per
asked-for issue in data/import-requests/, its state in the extension.

    <paper>_<date>.requested  the backend wrote it (logged-in users only)
    <paper>_<date>.running    the runner renamed it on starting fetch + the
                              chain, and adds the run_id once fetch has one
    <paper>_<date>.failed     the runner renamed it, adding the error
    (gone)                    imported: the issue is in the list

The runner rewrites the file in place rather than replacing it, so it
stays the backend's (the runner runs as root) and the backend can delete
it when asked again."""

import datetime
from enum import StrEnum

from pydantic import BaseModel

REQUESTS_DIR_NAME = "import-requests"


class ImportStatus(StrEnum):
    REQUESTED = "requested"
    RUNNING = "running"
    FAILED = "failed"


class ImportRequest(BaseModel):
    paper: str
    date: datetime.date
    requested_at: datetime.datetime
    # Set by the runner.
    run_id: str | None = None
    error: str | None = None


def file_stem(paper: str, date: datetime.date) -> str:
    return f"{paper}_{date.isoformat()}"
