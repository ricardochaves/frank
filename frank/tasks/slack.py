import os
import sys

import requests

from frank.tasks.base import Task

SLACK_LIST_ID = "F09SH4T1B8Q"
SLACK_DONE_COLUMN_ID = "Col00"
TASK_COLUMN_ID = "Col09R7BY1SAK"
MESSAGE_COLUMN_ID = "Col09V53TL7JB"


class SlackTaskSource:
    def __init__(self):
        self.token = os.getenv("SLACK_TOKEN")
        self.list_id = SLACK_LIST_ID
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def get_tasks(self) -> list[Task]:
        url = "https://slack.com/api/slackLists.items.list"
        tasks = []
        cursor = None

        while True:
            payload = {"list_id": self.list_id, "limit": 100}
            if cursor:
                payload["cursor"] = cursor

            response = requests.post(url, headers=self.headers, json=payload)
            data = response.json()

            if not data.get("ok"):
                error = data.get("error", "unknown")
                print(f"Slack API error: {error}")
                sys.exit(1)

            for item in data.get("items", []):
                task = self._parse_item(item)
                if task:
                    tasks.append(task)

            response_metadata = data.get("response_metadata", {})
            cursor = response_metadata.get("next_cursor")
            if not cursor:
                break

        return tasks

    def mark_done(self, task: Task) -> bool:
        url = "https://slack.com/api/slackLists.items.update"
        payload = {
            "list_id": self.list_id,
            "cells": [
                {
                    "row_id": task.id,
                    "column_id": SLACK_DONE_COLUMN_ID,
                    "checkbox": True,
                }
            ],
        }

        response = requests.post(url, headers=self.headers, json=payload)
        data = response.json()

        if not data.get("ok"):
            print(f"Slack API error: {data.get('error', 'unknown')}")
            return False
        return True

    def reply(self, task: Task, message: str) -> bool:
        channel_id = task.meta.get("channel_id")
        thread_ts = task.meta.get("thread_ts")
        if not channel_id or not thread_ts:
            return False

        url = "https://slack.com/api/chat.postMessage"
        payload = {
            "channel": channel_id,
            "thread_ts": thread_ts,
            "text": message,
        }

        response = requests.post(url, headers=self.headers, json=payload)
        data = response.json()

        if not data.get("ok"):
            print(f"Slack API error: {data.get('error', 'unknown')}")
            return False
        return True

    def _parse_item(self, item: dict) -> Task | None:
        item_id = item.get("id")
        raw_fields = item.get("fields", [])
        if isinstance(raw_fields, list):
            fields = {f["column_id"]: f for f in raw_fields if "column_id" in f}
        else:
            fields = raw_fields

        # Skip items already marked as done
        done_field = fields.get(SLACK_DONE_COLUMN_ID, {})
        if done_field.get("checkbox") is True:
            return None

        # Extract task text
        task_field = fields.get(TASK_COLUMN_ID, {})
        text = task_field.get("text")
        if not text:
            return None

        # Extract message thread info
        message_field = fields.get(MESSAGE_COLUMN_ID, {})
        messages = message_field.get("message", [])
        channel_id = None
        thread_ts = None
        if messages:
            channel_id = messages[0].get("channel_id")
            raw_thread_ts = messages[0].get("thread_ts", "")
            if raw_thread_ts and raw_thread_ts != "0000000000.000000":
                thread_ts = raw_thread_ts
            else:
                thread_ts = messages[0].get("ts")

        # Fetch full message from thread (the list column truncates it)
        if channel_id and thread_ts:
            full_text = self._get_thread_first_message(channel_id, thread_ts)
            if full_text:
                text = full_text

        return Task(
            id=item_id,
            text=text,
            source="slack",
            meta={"channel_id": channel_id, "thread_ts": thread_ts},
        )

    def _get_thread_first_message(self, channel_id: str, thread_ts: str) -> str | None:
        url = "https://slack.com/api/conversations.replies"
        params = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 1,
            "inclusive": True,
        }

        response = requests.get(url, headers=self.headers, params=params)
        data = response.json()

        if not data.get("ok") and data.get("error") == "not_in_channel":
            print(f"[frank] Bot not in channel {channel_id}, joining...")
            self._join_channel(channel_id)
            response = requests.get(url, headers=self.headers, params=params)
            data = response.json()

        if not data.get("ok"):
            raise RuntimeError(f"Slack API error (conversations.replies): {data.get('error', 'unknown')}")

        messages = data.get("messages", [])
        if messages:
            return messages[0].get("text")
        return None

    def _join_channel(self, channel_id: str) -> None:
        response = requests.post(
            "https://slack.com/api/conversations.join",
            headers=self.headers,
            json={"channel": channel_id},
        )
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error (conversations.join): {data.get('error', 'unknown')}")
