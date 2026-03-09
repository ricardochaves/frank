from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Task:
    id: str
    text: str
    source: str
    meta: dict = field(default_factory=dict)


class TaskSource(Protocol):
    def get_tasks(self) -> list[Task]: ...
    def mark_done(self, task: Task) -> bool: ...
    def reply(self, task: Task, message: str) -> bool: ...
