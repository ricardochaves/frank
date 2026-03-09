from frank.tasks.base import Task, TaskSource
from frank.tasks.slack import SlackTaskSource
from frank.tasks.monday import MondayTaskSource


def get_task_source(source_name: str) -> TaskSource:
    sources = {
        "slack": SlackTaskSource,
        "monday": MondayTaskSource,
    }
    cls = sources.get(source_name)
    if cls is None:
        raise ValueError(f"Unknown task source: {source_name}. Available: {', '.join(sources)}")
    return cls()
