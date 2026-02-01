"""Service adapter for remindctl CLI."""

import json
import subprocess
from datetime import datetime
from typing import Any

from mag.models.reminders import (
    CLIError,
    Reminder,
    ReminderCreate,
    ReminderFilter,
    ReminderList,
    ReminderUpdate,
)

REMINDCTL_BIN = "remindctl"

# Map remindctl priority strings to integer values
PRIORITY_MAP = {
    "none": 0,
    "low": 9,
    "medium": 5,
    "high": 1,
}

# Reverse map for converting integers to CLI strings
PRIORITY_TO_STR = {
    0: "none",
    1: "high",
    5: "medium",
    9: "low",
}


def _parse_priority(value: Any) -> int:
    """Convert remindctl priority value to integer."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return PRIORITY_MAP.get(value.lower(), 0)
    return 0


class RemindctlError(Exception):
    """Exception raised when remindctl CLI fails."""

    def __init__(self, message: str, code: int, stderr: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.stderr = stderr

    def to_dict(self) -> dict[str, Any]:
        """Convert to error response dict."""
        return CLIError(error=self.message, code=self.code, stderr=self.stderr).model_dump()


def _run_remindctl(*args: str, allow_empty: bool = False) -> dict[str, Any] | list[Any] | None:
    """Execute remindctl with arguments and return parsed JSON output."""
    cmd = [REMINDCTL_BIN, *args, "--json"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise RemindctlError(
            message="remindctl not found. Install with: brew install steipete/tap/remindctl",
            code=-1,
            stderr="",
        )
    except subprocess.TimeoutExpired:
        raise RemindctlError(
            message="remindctl timed out after 30 seconds",
            code=-1,
            stderr="",
        )

    if result.returncode != 0:
        raise RemindctlError(
            message=f"remindctl failed with exit code {result.returncode}",
            code=result.returncode,
            stderr=result.stderr.strip(),
        )

    # Handle empty output (some commands like rename/delete don't output JSON)
    if not result.stdout.strip():
        if allow_empty:
            return None
        raise RemindctlError(
            message="No output from remindctl",
            code=0,
            stderr="",
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RemindctlError(
            message=f"Failed to parse remindctl output: {e}",
            code=0,
            stderr=result.stdout,
        )


def _parse_reminder(data: dict[str, Any]) -> Reminder:
    """Parse a reminder from remindctl JSON output."""
    due = None
    if data.get("dueDate"):
        try:
            due = datetime.fromisoformat(data["dueDate"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    completed_date = None
    if data.get("completionDate"):
        try:
            completed_date = datetime.fromisoformat(data["completionDate"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    return Reminder(
        id=data.get("id", data.get("externalId", "")),
        title=data.get("title", ""),
        list=data.get("list", data.get("listName", "")),
        due=due,
        completed=data.get("isCompleted", False),
        completed_date=completed_date,
        notes=data.get("notes"),
        priority=_parse_priority(data.get("priority")),
    )


async def list_reminders(
    filter_type: ReminderFilter = ReminderFilter.ALL,
    date: str | None = None,
    list_name: str | None = None,
) -> list[Reminder]:
    """List reminders with optional filters."""
    args = ["show"]

    if filter_type != ReminderFilter.ALL:
        args.append(filter_type.value)
    elif date:
        args.append(date)

    if list_name:
        args.extend(["--list", list_name])

    result = _run_remindctl(*args)
    if isinstance(result, list):
        return [_parse_reminder(r) for r in result]
    return []


async def list_lists() -> list[ReminderList]:
    """List all reminder lists."""
    result = _run_remindctl("list")
    if isinstance(result, list):
        return [
            ReminderList(name=item.get("title", ""), count=item.get("reminderCount", 0))
            for item in result
        ]
    return []


async def create_reminder(data: ReminderCreate) -> Reminder:
    """Create a new reminder."""
    args = ["add", data.title]

    if data.list:
        args.extend(["--list", data.list])
    if data.due:
        args.extend(["--due", data.due])
    if data.notes:
        args.extend(["--notes", data.notes])
    if data.priority and data.priority.value != 0:
        priority_str = PRIORITY_TO_STR.get(data.priority.value, "none")
        args.extend(["--priority", priority_str])

    result = _run_remindctl(*args)
    if isinstance(result, dict):
        return _parse_reminder(result)
    raise RemindctlError(message="Unexpected response format", code=0, stderr=str(result))


async def update_reminder(reminder_id: str, data: ReminderUpdate) -> Reminder:
    """Update an existing reminder."""
    args = ["edit", reminder_id]

    if data.title:
        args.extend(["--title", data.title])
    if data.list:
        args.extend(["--list", data.list])
    if data.clear_due:
        args.append("--clear-due")
    elif data.due:
        args.extend(["--due", data.due])
    if data.notes:
        args.extend(["--notes", data.notes])
    if data.priority is not None:
        priority_str = PRIORITY_TO_STR.get(data.priority.value, "none")
        args.extend(["--priority", priority_str])
    if data.completed is True:
        args.append("--complete")
    elif data.completed is False:
        args.append("--incomplete")

    result = _run_remindctl(*args)
    if isinstance(result, dict):
        return _parse_reminder(result)
    raise RemindctlError(message="Unexpected response format", code=0, stderr=str(result))


async def complete_reminder(reminder_id: str) -> Reminder:
    """Mark a reminder as complete."""
    result = _run_remindctl("complete", reminder_id)
    if isinstance(result, dict):
        return _parse_reminder(result)
    raise RemindctlError(message="Unexpected response format", code=0, stderr=str(result))


async def delete_reminder(reminder_id: str) -> dict[str, str]:
    """Delete a reminder."""
    _run_remindctl("delete", reminder_id, "--force", allow_empty=True)
    return {"status": "deleted", "id": reminder_id}


async def bulk_complete(reminder_ids: list[str]) -> list[Reminder]:
    """Mark multiple reminders as complete."""
    result = _run_remindctl("complete", *reminder_ids)
    if isinstance(result, list):
        return [_parse_reminder(r) for r in result]
    if isinstance(result, dict):
        return [_parse_reminder(result)]
    raise RemindctlError(message="Unexpected response format", code=0, stderr=str(result))


async def bulk_delete(reminder_ids: list[str]) -> dict[str, Any]:
    """Delete multiple reminders."""
    _run_remindctl("delete", *reminder_ids, "--force", allow_empty=True)
    return {"status": "deleted", "ids": reminder_ids}


async def create_list(name: str) -> ReminderList:
    """Create a new reminder list."""
    result = _run_remindctl("list", name, "--create")
    if isinstance(result, list) and len(result) > 0:
        item = result[0]
        return ReminderList(name=item.get("title", name), count=item.get("reminderCount", 0))
    if isinstance(result, dict):
        return ReminderList(name=result.get("title", name), count=result.get("reminderCount", 0))
    raise RemindctlError(message="Unexpected response format", code=0, stderr=str(result))


async def rename_list(name: str, new_name: str) -> ReminderList:
    """Rename a reminder list."""
    _run_remindctl("list", name, "--rename", new_name, allow_empty=True)
    # Rename doesn't return the updated list, so we return the new name
    return ReminderList(name=new_name, count=0)


async def delete_list(name: str) -> dict[str, str]:
    """Delete a reminder list."""
    _run_remindctl("list", name, "--delete", "--force", allow_empty=True)
    return {"status": "deleted", "name": name}
