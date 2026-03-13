import os

from frank.tasks.base import Task


DEFAULT_TASKS_FILE = "tasks.txt"


class FileTaskSource:
    def __init__(self):
        self.path = os.getenv("FRANK_TASKS_FILE", DEFAULT_TASKS_FILE)

    def get_tasks(self) -> list[Task]:
        if not os.path.exists(self.path):
            return []

        tasks = []
        with open(self.path) as f:
            for i, line in enumerate(f, start=1):
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                tasks.append(Task(
                    id=str(i),
                    text=text,
                    source="file",
                    meta={"file": self.path, "line": i},
                ))
        return tasks

    def mark_done(self, task: Task) -> bool:
        if not os.path.exists(self.path):
            return False

        with open(self.path) as f:
            lines = f.readlines()

        line_num = task.meta.get("line")
        if line_num is None or line_num < 1 or line_num > len(lines):
            return False

        lines[line_num - 1] = f"# [done] {lines[line_num - 1].strip()}\n"

        with open(self.path, "w") as f:
            f.writelines(lines)
        return True

    def reply(self, task: Task, message: str) -> bool:
        reply_path = self.path.rsplit(".", 1)[0] + ".log"
        with open(reply_path, "a") as f:
            f.write(f"--- Task {task.id}: {task.text[:60]} ---\n{message}\n\n")
        return True
