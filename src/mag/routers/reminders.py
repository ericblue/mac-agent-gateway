"""Reminders API router for Mac Agent Gateway."""

import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from mag.auth import verify_api_key
from mag.config import get_settings
from mag.models.reminders import (
    BulkIds,
    ListCreate,
    ListRename,
    Reminder,
    ReminderCreate,
    ReminderFilter,
    ReminderList,
    ReminderUpdate,
)
from mag.services import remindctl
from mag.services.remindctl import RemindctlError

router = APIRouter(prefix="/reminders", dependencies=[Depends(verify_api_key)])

# Security: Pattern for validating reminder IDs and list names
# Allows alphanumeric, hyphens, underscores, and some UUID formats
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:/.]+$")
_MAX_ID_LENGTH = 200


def _validate_id(value: str, field_name: str) -> str:
    """Validate that an ID or name is safe for CLI usage.
    
    Security: Prevents command injection by restricting characters.
    """
    if len(value) > _MAX_ID_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} is too long (max {_MAX_ID_LENGTH} characters)",
        )
    if not _SAFE_ID_PATTERN.match(value):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}: contains disallowed characters",
        )
    return value


def _handle_cli_error(e: RemindctlError) -> HTTPException:
    """Convert RemindctlError to HTTPException."""
    return HTTPException(status_code=500, detail=e.to_dict())


def _require_capability(capability: str) -> None:
    """Check if a capability is enabled, raise 403 if not."""
    settings = get_settings()
    capability_map = {
        "read": settings.reminders_read,
        "write": settings.reminders_write,
    }
    if not capability_map.get(capability, False):
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"Capability 'reminders.{capability}' is disabled",
                "hint": f"Set MAG_REMINDERS_{capability.upper()}=true to enable",
            },
        )


@router.get("", response_model=list[Reminder])
async def list_reminders(
    filter: ReminderFilter = Query(default=ReminderFilter.ALL, description="Filter reminders"),
    date: str | None = Query(default=None, description="Specific date (YYYY-MM-DD)"),
    list: str | None = Query(default=None, description="Filter by list name"),
) -> list[Reminder]:
    """List reminders with optional filters.

    Filter options: today, tomorrow, week, overdue, upcoming, completed, all
    """
    _require_capability("read")
    try:
        return await remindctl.list_reminders(filter_type=filter, date=date, list_name=list)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.get("/lists", response_model=list[ReminderList])
async def list_reminder_lists() -> list[ReminderList]:
    """List all available reminder lists."""
    _require_capability("read")
    try:
        return await remindctl.list_lists()
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.post("/lists", response_model=ReminderList, status_code=201)
async def create_reminder_list(data: ListCreate) -> ReminderList:
    """Create a new reminder list."""
    _require_capability("write")
    try:
        return await remindctl.create_list(data.name)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.patch("/lists/{list_name}", response_model=ReminderList)
async def rename_reminder_list(list_name: str, data: ListRename) -> ReminderList:
    """Rename a reminder list."""
    _require_capability("write")
    _validate_id(list_name, "list_name")
    try:
        return await remindctl.rename_list(list_name, data.new_name)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.delete("/lists/{list_name}")
async def delete_reminder_list(list_name: str) -> dict[str, str]:
    """Delete a reminder list."""
    _require_capability("write")
    _validate_id(list_name, "list_name")
    try:
        return await remindctl.delete_list(list_name)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.post("", response_model=Reminder, status_code=201)
async def create_reminder(data: ReminderCreate) -> Reminder:
    """Create a new reminder.

    Due date accepts ISO 8601 format or natural language: today, tomorrow, etc.
    """
    _require_capability("write")
    try:
        return await remindctl.create_reminder(data)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.patch("/{reminder_id}", response_model=Reminder)
async def update_reminder(reminder_id: str, data: ReminderUpdate) -> Reminder:
    """Update an existing reminder."""
    _require_capability("write")
    _validate_id(reminder_id, "reminder_id")
    try:
        return await remindctl.update_reminder(reminder_id, data)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.post("/{reminder_id}/complete", response_model=Reminder)
async def complete_reminder(reminder_id: str) -> Reminder:
    """Mark a reminder as complete."""
    _require_capability("write")
    _validate_id(reminder_id, "reminder_id")
    try:
        return await remindctl.complete_reminder(reminder_id)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.delete("/{reminder_id}")
async def delete_reminder(reminder_id: str) -> dict[str, str]:
    """Delete a reminder."""
    _require_capability("write")
    _validate_id(reminder_id, "reminder_id")
    try:
        return await remindctl.delete_reminder(reminder_id)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.post("/bulk/complete", response_model=list[Reminder])
async def bulk_complete_reminders(data: BulkIds) -> list[Reminder]:
    """Mark multiple reminders as complete.

    Provide a list of reminder IDs to complete in one request.
    """
    _require_capability("write")
    try:
        return await remindctl.bulk_complete(data.ids)
    except RemindctlError as e:
        raise _handle_cli_error(e)


@router.post("/bulk/delete")
async def bulk_delete_reminders(data: BulkIds) -> dict:
    """Delete multiple reminders.

    Provide a list of reminder IDs to delete in one request.
    """
    _require_capability("write")
    try:
        return await remindctl.bulk_delete(data.ids)
    except RemindctlError as e:
        raise _handle_cli_error(e)
