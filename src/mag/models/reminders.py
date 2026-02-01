"""Pydantic models for Apple Reminders."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ReminderFilter(str, Enum):
    """Filter options for listing reminders."""

    TODAY = "today"
    TOMORROW = "tomorrow"
    WEEK = "week"
    OVERDUE = "overdue"
    UPCOMING = "upcoming"
    COMPLETED = "completed"
    ALL = "all"


class ReminderPriority(int, Enum):
    """Priority levels for reminders."""

    NONE = 0
    HIGH = 1
    MEDIUM = 5
    LOW = 9


class ReminderCreate(BaseModel):
    """Request model for creating a reminder."""

    title: str = Field(..., min_length=1, description="The reminder title")
    list: str | None = Field(None, description="The reminder list name")
    due: str | None = Field(None, description="Due date (ISO 8601, or natural: today, tomorrow)")
    notes: str | None = Field(None, description="Additional notes")
    priority: ReminderPriority = Field(
        default=ReminderPriority.NONE, description="Priority level"
    )


class ReminderUpdate(BaseModel):
    """Request model for updating a reminder."""

    title: str | None = Field(None, min_length=1, description="New title")
    list: str | None = Field(None, description="Move to a different list")
    due: str | None = Field(None, description="New due date")
    clear_due: bool = Field(default=False, description="Clear the due date")
    notes: str | None = Field(None, description="New notes")
    priority: ReminderPriority | None = Field(None, description="New priority")
    completed: bool | None = Field(None, description="Set completion status (true=complete, false=incomplete)")


class Reminder(BaseModel):
    """Response model for a reminder."""

    id: str = Field(..., description="Unique reminder identifier")
    title: str = Field(..., description="The reminder title")
    list: str = Field(..., description="The reminder list name")
    due: datetime | None = Field(None, description="Due date and time")
    completed: bool = Field(default=False, description="Whether the reminder is completed")
    completed_date: datetime | None = Field(None, description="When the reminder was completed")
    notes: str | None = Field(None, description="Additional notes")
    priority: int = Field(default=0, description="Priority level (0=none, 1=high, 5=medium, 9=low)")


class ReminderList(BaseModel):
    """Response model for a reminder list."""

    name: str = Field(..., description="List name")
    count: int = Field(default=0, description="Number of reminders in the list")


class BulkIds(BaseModel):
    """Request model for bulk operations."""

    ids: list[str] = Field(..., min_length=1, description="List of reminder IDs")


class ListCreate(BaseModel):
    """Request model for creating a reminder list."""

    name: str = Field(..., min_length=1, description="List name")


class ListRename(BaseModel):
    """Request model for renaming a reminder list."""

    new_name: str = Field(..., min_length=1, description="New list name")


class CLIError(BaseModel):
    """Error response from CLI execution."""

    error: str = Field(..., description="Error message")
    code: int = Field(..., description="CLI exit code")
    stderr: str = Field(default="", description="CLI stderr output")
