"""Filesystem service for paths beneath ~/Library/Mobile Documents."""

from __future__ import annotations

import asyncio
import errno
import mimetypes
import os
import stat
import tempfile
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mag.models.icloud import ICloudDeleteResponse, ICloudDirectoryListing, ICloudEntry


class ICloudDriveError(Exception):
    """Sanitized filesystem error suitable for router translation."""

    def __init__(self, code: str, message: str, path: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path

    def to_detail(self) -> dict[str, str]:
        detail = {"error": self.message, "code": self.code}
        if self.path is not None:
            detail["path"] = self.path
        return detail


@dataclass(frozen=True)
class ICloudFile:
    """Validated regular file ready for a FastAPI FileResponse."""

    path: Path
    media_type: str


class ICloudDriveService:
    """Perform safe, root-relative Mobile Documents operations."""

    def __init__(self, root: Path | None = None) -> None:
        configured_root = root or Path("~/Library/Mobile Documents")
        self.root = configured_root.expanduser().absolute()

    def _validate_root(self) -> None:
        try:
            root_stat = os.lstat(self.root)
        except OSError as exc:
            raise self._os_error(exc, "") from None
        if stat.S_ISLNK(root_stat.st_mode):
            raise ICloudDriveError(
                "symlink_forbidden", "Mobile Documents root cannot be a symbolic link", ""
            )
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ICloudDriveError(
                "filesystem_error", "Mobile Documents root is not a directory", ""
            )

    def _target(self, relative_path: str, *, allow_root: bool = False) -> Path:
        self._validate_root()
        if "\x00" in relative_path or relative_path.startswith("/"):
            raise ICloudDriveError("invalid_path", "Path must be relative", relative_path)
        if relative_path == "":
            if allow_root:
                return self.root
            raise ICloudDriveError("invalid_path", "A file path is required", relative_path)

        parts = relative_path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ICloudDriveError(
                "invalid_path", "Path contains an invalid component", relative_path
            )

        current = self.root
        for part in parts:
            current = current / part
            try:
                current_stat = os.lstat(current)
            except FileNotFoundError:
                break
            except NotADirectoryError:
                raise ICloudDriveError(
                    "invalid_path", "A path component is not a directory", relative_path
                ) from None
            except OSError as exc:
                raise self._os_error(exc, relative_path) from None
            if stat.S_ISLNK(current_stat.st_mode):
                raise ICloudDriveError(
                    "symlink_forbidden", "Symbolic links cannot be accessed", relative_path
                )
        return self.root.joinpath(*parts)

    def _os_error(self, exc: OSError, relative_path: str) -> ICloudDriveError:
        if isinstance(exc, PermissionError):
            return ICloudDriveError(
                "permission_denied", "Filesystem permission denied", relative_path
            )
        if exc.errno == errno.ENOSPC:
            return ICloudDriveError(
                "insufficient_storage", "Insufficient storage for file operation", relative_path
            )
        if isinstance(exc, FileNotFoundError):
            return ICloudDriveError("not_found", "Path not found", relative_path)
        return ICloudDriveError("filesystem_error", "Filesystem operation failed", relative_path)

    def _entry_from_stat(
        self, relative_path: str, name: str, entry_stat: os.stat_result
    ) -> ICloudEntry:
        mode = entry_stat.st_mode
        if stat.S_ISREG(mode):
            kind = "file"
            size = entry_stat.st_size
        elif stat.S_ISDIR(mode):
            kind = "directory"
            size = None
        elif stat.S_ISLNK(mode):
            kind = "symlink"
            size = None
        else:
            kind = "other"
            size = None
        return ICloudEntry(
            path=relative_path,
            name=name,
            kind=kind,
            size=size,
            modified_at=datetime.fromtimestamp(entry_stat.st_mtime).astimezone(),
        )

    def _list_directory(self, relative_path: str, target: Path) -> ICloudDirectoryListing:
        entries: list[ICloudEntry] = []
        try:
            children = sorted(
                target.iterdir(), key=lambda child: (child.name.casefold(), child.name)
            )
        except OSError as exc:
            raise self._os_error(exc, relative_path) from None
        for child in children:
            child_relative = f"{relative_path}/{child.name}" if relative_path else child.name
            try:
                child_stat = os.lstat(child)
            except OSError:
                entries.append(
                    ICloudEntry(
                        path=child_relative,
                        name=child.name,
                        kind="other",
                        size=None,
                        modified_at=None,
                    )
                )
                continue
            entries.append(self._entry_from_stat(child_relative, child.name, child_stat))
        return ICloudDirectoryListing(path=relative_path, entries=entries)

    def read(self, relative_path: str) -> ICloudDirectoryListing | ICloudFile:
        target = self._target(relative_path, allow_root=True)
        try:
            target_stat = os.lstat(target)
        except OSError as exc:
            raise self._os_error(exc, relative_path) from None
        if stat.S_ISDIR(target_stat.st_mode):
            return self._list_directory(relative_path, target)
        if stat.S_ISREG(target_stat.st_mode):
            media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            return ICloudFile(path=target, media_type=media_type)
        raise ICloudDriveError(
            "unsupported_type", "Only regular files and directories are supported", relative_path
        )

    def _require_parent_directory(self, target: Path, relative_path: str) -> None:
        try:
            parent_stat = os.lstat(target.parent)
        except FileNotFoundError:
            raise ICloudDriveError(
                "parent_missing", "Destination parent directory does not exist", relative_path
            ) from None
        except OSError as exc:
            raise self._os_error(exc, relative_path) from None
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ICloudDriveError(
                "parent_missing", "Destination parent is not a directory", relative_path
            )

    async def put(
        self, relative_path: str, chunks: AsyncIterable[bytes]
    ) -> tuple[ICloudEntry, bool]:
        target = self._target(relative_path)
        self._require_parent_directory(target, relative_path)
        created = True
        try:
            existing_stat = os.lstat(target)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise self._os_error(exc, relative_path) from None
        else:
            created = False
            if not stat.S_ISREG(existing_stat.st_mode):
                raise ICloudDriveError(
                    "unsupported_type", "Only regular files can be replaced", relative_path
                )

        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".mag-upload-", dir=target.parent
            )
        except OSError as exc:
            raise self._os_error(exc, relative_path) from None
        temporary_path = Path(temporary_name)

        try:
            temporary_file = os.fdopen(descriptor, "wb")
        except OSError as exc:
            os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
            raise self._os_error(exc, relative_path) from None

        try:
            with temporary_file:
                async for chunk in chunks:
                    if chunk:
                        await asyncio.to_thread(temporary_file.write, chunk)
                await asyncio.to_thread(temporary_file.flush)
                await asyncio.to_thread(os.fsync, temporary_file.fileno())
            await asyncio.to_thread(os.replace, temporary_path, target)
        except asyncio.CancelledError:
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise self._os_error(exc, relative_path) from None
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise ICloudDriveError(
                "filesystem_error", "Upload stream failed", relative_path
            ) from None

        try:
            target_stat = os.lstat(target)
        except OSError as exc:
            raise self._os_error(exc, relative_path) from None
        return self._entry_from_stat(relative_path, target.name, target_stat), created

    def _require_regular_file(self, relative_path: str) -> tuple[Path, os.stat_result]:
        target = self._target(relative_path)
        try:
            target_stat = os.lstat(target)
        except OSError as exc:
            raise self._os_error(exc, relative_path) from None
        if not stat.S_ISREG(target_stat.st_mode):
            raise ICloudDriveError(
                "unsupported_type", "Operation requires a regular file", relative_path
            )
        return target, target_stat

    def move(self, source_path: str, destination_path: str) -> ICloudEntry:
        source, _ = self._require_regular_file(source_path)
        destination = self._target(destination_path)
        if source_path == destination_path:
            raise ICloudDriveError(
                "invalid_path", "Source and destination must be different", source_path
            )
        self._require_parent_directory(destination, destination_path)
        try:
            os.lstat(destination)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise self._os_error(exc, destination_path) from None
        else:
            raise ICloudDriveError(
                "conflict", "Destination already exists", destination_path
            )
        try:
            os.rename(source, destination)
            destination_stat = os.lstat(destination)
        except OSError as exc:
            raise self._os_error(exc, destination_path) from None
        return self._entry_from_stat(destination_path, destination.name, destination_stat)

    def delete(self, relative_path: str) -> ICloudDeleteResponse:
        target, _ = self._require_regular_file(relative_path)
        try:
            os.unlink(target)
        except OSError as exc:
            raise self._os_error(exc, relative_path) from None
        return ICloudDeleteResponse(path=relative_path)
