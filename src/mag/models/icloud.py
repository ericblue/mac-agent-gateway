"""Pydantic models for iCloud Drive file operations."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ICloudEntryKind = Literal["file", "directory", "symlink", "other"]


class ICloudEntry(BaseModel):
    """Metadata for one Mobile Documents entry."""

    path: str = Field(..., description="Path relative to the Mobile Documents root")
    name: str = Field(..., description="Final path component")
    kind: ICloudEntryKind = Field(..., description="Filesystem entry type")
    size: int | None = Field(None, ge=0, description="File size in bytes")
    modified_at: datetime | None = Field(None, description="Filesystem modification time")


class ICloudDirectoryListing(BaseModel):
    """Non-recursive directory listing."""

    path: str = Field(..., description="Relative directory path; empty for the root")
    entries: list[ICloudEntry] = Field(default_factory=list)


class ICloudMove(BaseModel):
    """Request to rename or move a regular file."""

    destination: str = Field(..., min_length=1, description="Complete relative destination path")

    @field_validator("destination")
    @classmethod
    def destination_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("destination must not be blank")
        return value


class ICloudDeleteResponse(BaseModel):
    """Successful file deletion response."""

    status: Literal["deleted"] = "deleted"
    path: str
