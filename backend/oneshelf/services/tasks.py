"""Long library jobs as background tasks (Master §36; I-96, repair plan WP-8).

A Full Backup of a large library, a restore, an export or a migration can run for minutes. Asked with
`?background=true`, the API starts the job here and answers at once with a task id. The job's outcome, which is
the same status and body the synchronous call would have returned, is kept for `GET /api/tasks/{id}`, and a
`task.finished` event tells every open client. The synchronous form remains for existing clients.

Tasks live in memory: they describe work in progress, not library state. The work itself is persisted where it
always was (backup records, export jobs, migrations), so a restart loses only the task handle, never the result.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id

logger = logging.getLogger(__name__)

Outcome = tuple[int, dict]


@dataclass
class Task:
    id: str
    kind: str
    state: str                       # running | completed | failed
    started_at: str
    finished_at: str | None = None
    status: int | None = None        # the HTTP status the synchronous call would have answered
    result: dict = field(default_factory=dict)


class TaskRegistry:
    def __init__(self, events=None, *, keep: int = 100) -> None:
        self.events = events
        self.keep = keep
        self._tasks: OrderedDict[str, Task] = OrderedDict()
        self._running: set[asyncio.Task] = set()

    def start(self, kind: str, job: Callable[[], Awaitable[Outcome]]) -> Task:
        task = Task(new_id(), kind, "running", utcnow_iso())
        self._tasks[task.id] = task
        runner = asyncio.create_task(self._run(task, job))
        self._running.add(runner)
        runner.add_done_callback(self._running.discard)
        self._prune()
        return task

    async def _run(self, task: Task, job: Callable[[], Awaitable[Outcome]]) -> None:
        try:
            task.status, task.result = await job()
            task.state = "completed" if task.status < 400 else "failed"
        except Exception as exc:  # noqa: BLE001 — a task always ends with an answer, never silently
            logger.exception("background %s task failed", task.kind)
            task.status, task.state = 500, "failed"
            task.result = {"error": {"code": "TASK_FAILED", "message": f"{type(exc).__name__}: {exc}"}}
        task.finished_at = utcnow_iso()
        if self.events is not None:
            self.events.publish("task.finished", {"task_id": task.id, "kind": task.kind, "state": task.state})

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def view(self, task: Task) -> dict:
        return asdict(task)

    def _prune(self) -> None:
        finished = [t.id for t in self._tasks.values() if t.state != "running"]
        while len(self._tasks) > self.keep and finished:
            self._tasks.pop(finished.pop(0), None)

    async def drain(self) -> None:
        """Wait for running tasks (application shutdown and tests)."""
        if self._running:
            await asyncio.gather(*list(self._running), return_exceptions=True)
