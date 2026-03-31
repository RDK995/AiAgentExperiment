"""Minimal task scheduler interface for authoritative world ticks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.engine.event_bus import EventBus


@dataclass(slots=True)
class ScheduledTask:
    """A scheduled callback due at a specific simulation time."""

    due_at: datetime
    callback: Callable[[datetime, EventBus], None]
    interval: timedelta | None = None
    task_id: str = ""


class TaskScheduler:
    """In-memory scheduler for prototype simulation tasks."""

    def __init__(self) -> None:
        self._tasks: list[ScheduledTask] = []

    def schedule(self, task: ScheduledTask) -> None:
        """Register a task for future dispatch."""

        self._tasks.append(task)
        self._tasks.sort(key=lambda item: item.due_at)

    def dispatch_due_tasks(self, now: datetime, event_bus: EventBus) -> None:
        """Dispatch tasks whose due time has passed."""

        ready = [task for task in self._tasks if task.due_at <= now]
        self._tasks = [task for task in self._tasks if task.due_at > now]
        for task in ready:
            task.callback(now, event_bus)
            if task.interval is not None:
                self.schedule(
                    ScheduledTask(
                        due_at=task.due_at + task.interval,
                        callback=task.callback,
                        interval=task.interval,
                        task_id=task.task_id,
                    )
                )

    def pending_task_ids(self) -> list[str]:
        """Return scheduled task identifiers for debugging and tests."""

        return [task.task_id for task in self._tasks if task.task_id]
