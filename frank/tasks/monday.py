import os

import requests

from frank.tasks.base import Task

MONDAY_API_URL = "https://api.monday.com/v2"


class MondayTaskSource:
    def __init__(self):
        self.token = os.getenv("MONDAY_TOKEN")
        if not self.token:
            raise ValueError("MONDAY_TOKEN environment variable is required")
        self.board_id = os.getenv("MONDAY_BOARD_ID")
        if not self.board_id:
            raise ValueError("MONDAY_BOARD_ID environment variable is required")
        self.status_column_id = os.getenv("MONDAY_STATUS_COLUMN_ID", "status")
        self.status_label = os.getenv("MONDAY_STATUS_LABEL", "To Do")
        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "API-Version": "2024-10",
        }

    def get_tasks(self) -> list[Task]:
        query = """
        query ($board_id: [ID!]!) {
            boards(ids: $board_id) {
                items_page(limit: 100) {
                    items {
                        id
                        name
                        column_values {
                            id
                            text
                        }
                    }
                }
            }
        }
        """
        variables = {"board_id": [self.board_id]}
        data = self._request(query, variables)

        boards = data.get("data", {}).get("boards", [])
        if not boards:
            return []

        items = boards[0].get("items_page", {}).get("items", [])
        tasks = []

        for item in items:
            status = self._get_column_value(item, self.status_column_id)
            if status and status.lower() == self.status_label.lower():
                description_parts = []
                for col in item.get("column_values", []):
                    if col.get("id") != self.status_column_id and col.get("text"):
                        description_parts.append(col["text"])

                task_text = item["name"]
                if description_parts:
                    task_text += "\n\n" + "\n".join(description_parts)

                tasks.append(Task(
                    id=item["id"],
                    text=task_text,
                    source="monday",
                    meta={"board_id": self.board_id, "item_id": item["id"]},
                ))

        return tasks

    def mark_done(self, task: Task) -> bool:
        board_id = task.meta.get("board_id", self.board_id)
        query = """
        mutation ($board_id: ID!, $item_id: ID!, $column_id: String!, $value: String!) {
            change_simple_column_value(
                board_id: $board_id,
                item_id: $item_id,
                column_id: $column_id,
                value: $value
            ) {
                id
            }
        }
        """
        variables = {
            "board_id": board_id,
            "item_id": task.id,
            "column_id": self.status_column_id,
            "value": "Done",
        }
        try:
            self._request(query, variables)
            return True
        except RuntimeError as e:
            print(f"Monday API error: {e}")
            return False

    def reply(self, task: Task, message: str) -> bool:
        query = """
        mutation ($item_id: ID!, $body: String!) {
            create_update(
                item_id: $item_id,
                body: $body
            ) {
                id
            }
        }
        """
        variables = {
            "item_id": task.id,
            "body": message,
        }
        try:
            self._request(query, variables)
            return True
        except RuntimeError as e:
            print(f"Monday API error: {e}")
            return False

    def _request(self, query: str, variables: dict | None = None) -> dict:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        response = requests.post(MONDAY_API_URL, headers=self.headers, json=payload)
        data = response.json()

        if "errors" in data:
            raise RuntimeError(f"Monday API errors: {data['errors']}")

        return data

    def _get_column_value(self, item: dict, column_id: str) -> str | None:
        for col in item.get("column_values", []):
            if col.get("id") == column_id:
                return col.get("text")
        return None
