# iCloud Drive API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated, binary-safe file CRUD and read-only directory listing for every path beneath `~/Library/Mobile Documents`.

**Architecture:** Keep MAG's existing model/service/router layering. A root-confined `ICloudDriveService` validates relative paths, blocks symbolic links and special files, streams uploads into atomic temporary files, and returns either JSON metadata or a file descriptor for FastAPI to serve; the router owns capability checks and HTTP error mapping.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pathlib/os/tempfile/asyncio from the standard library, pytest, Ruff.

---

## File Structure

- Create `src/mag/models/icloud.py`: Pydantic request and metadata response contracts.
- Create `src/mag/services/icloud_drive.py`: root-relative path validation, filesystem metadata, binary read/write, move, and delete operations.
- Create `src/mag/routers/icloud.py`: authenticated HTTP routes, capability enforcement, dynamic file/list responses, and service error mapping.
- Create `tests/test_icloud.py`: model, capability, service, security, router, and error-mapping coverage using temporary directories only.
- Modify `src/mag/config.py`: add `MAG_ICLOUD_READ`, `MAG_ICLOUD_WRITE`, and the `icloud` capabilities response.
- Modify `src/mag/main.py`: mount the router, allow `PUT` through CORS, mention iCloud Drive in metadata, and log disabled iCloud capabilities.
- Modify `.env.example`: document iCloud capability settings.
- Modify `README.md`: document feature scope, configuration, endpoints, examples, safety rules, and limitations.

## Task 1: Models And Capability Configuration

**Files:**
- Create: `src/mag/models/icloud.py`
- Create: `tests/test_icloud.py`
- Modify: `src/mag/config.py:91-151`

- [ ] **Step 1: Write failing model and capability tests**

Create `tests/test_icloud.py` with the following initial content:

```python
"""Tests for the iCloud Drive filesystem API."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mag.config import get_settings
from mag.main import app
from mag.models.icloud import (
    ICloudDirectoryListing,
    ICloudEntry,
    ICloudMove,
)


class TestICloudModels:
    def test_move_requires_non_blank_destination(self) -> None:
        with pytest.raises(ValidationError):
            ICloudMove(destination="   ")

    def test_directory_listing_serializes_metadata(self) -> None:
        listing = ICloudDirectoryListing(
            path="com~apple~CloudDocs",
            entries=[
                ICloudEntry(
                    path="com~apple~CloudDocs/report.pdf",
                    name="report.pdf",
                    kind="file",
                    size=42,
                    modified_at=datetime(2026, 6, 11, 12, 0, 0),
                )
            ],
        )

        data = listing.model_dump(mode="json")

        assert data["path"] == "com~apple~CloudDocs"
        assert data["entries"][0]["kind"] == "file"
        assert data["entries"][0]["size"] == 42


class TestICloudCapabilities:
    def test_capabilities_include_icloud(self) -> None:
        client = TestClient(app)

        response = client.get("/v1/capabilities")

        assert response.status_code == 200
        assert response.json()["icloud"] == {"read": True, "write": True}

    def test_capabilities_reflect_disabled_icloud_settings(self, monkeypatch) -> None:
        monkeypatch.setenv("MAG_ICLOUD_READ", "false")
        monkeypatch.setenv("MAG_ICLOUD_WRITE", "false")
        get_settings.cache_clear()
        client = TestClient(app)

        response = client.get("/v1/capabilities")

        assert response.json()["icloud"] == {"read": False, "write": False}
        get_settings.cache_clear()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudModels tests/test_icloud.py::TestICloudCapabilities -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'mag.models.icloud'`.

- [ ] **Step 3: Add the iCloud Pydantic models**

Create `src/mag/models/icloud.py`:

```python
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
```

- [ ] **Step 4: Add iCloud settings and capability serialization**

In `src/mag/config.py`, add settings after the Notes settings:

```python
    # iCloud Drive capabilities
    icloud_read: bool = True  # List directories and read files
    icloud_write: bool = True  # Create, replace, move, and delete files
```

Add the nested capability model and field:

```python
    class ICloudCapabilities(BaseModel):
        read: bool
        write: bool

    messages: MessagesCapabilities
    reminders: RemindersCapabilities
    notes: NotesCapabilities
    icloud: ICloudCapabilities
```

Add this argument to `get_capabilities()`:

```python
        icloud=Capabilities.ICloudCapabilities(
            read=settings.icloud_read,
            write=settings.icloud_write,
        ),
```

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudModels tests/test_icloud.py::TestICloudCapabilities -v
```

Expected: all four tests pass.

- [ ] **Step 6: Commit models and capabilities**

```bash
git add src/mag/models/icloud.py src/mag/config.py tests/test_icloud.py
git commit -m "feat: add iCloud Drive models and capabilities"
```

## Task 2: Safe Path Resolution, Listing, And File Reads

**Files:**
- Create: `src/mag/services/icloud_drive.py`
- Modify: `tests/test_icloud.py`

- [ ] **Step 1: Add failing service tests for listing and reads**

Add these imports to the module import block in `tests/test_icloud.py`:

```python
import os
import socket
from pathlib import Path
from unittest.mock import patch

from mag.services.icloud_drive import (
    ICloudDriveError,
    ICloudDriveService,
    ICloudFile,
)
```

Append these tests:

```python


class TestICloudDriveReads:
    def test_lists_root_non_recursively_and_sorts_case_insensitively(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "zeta.txt").write_bytes(b"z")
        (tmp_path / "Alpha").mkdir()
        (tmp_path / "Alpha" / "nested.txt").write_bytes(b"nested")
        service = ICloudDriveService(root=tmp_path)

        result = service.read("")

        assert isinstance(result, ICloudDirectoryListing)
        assert [entry.name for entry in result.entries] == ["Alpha", "zeta.txt"]
        assert [entry.kind for entry in result.entries] == ["directory", "file"]
        assert "nested.txt" not in [entry.name for entry in result.entries]

        nested = service.read("Alpha")
        assert isinstance(nested, ICloudDirectoryListing)
        assert nested.path == "Alpha"
        assert [entry.name for entry in nested.entries] == ["nested.txt"]

    def test_lists_symlink_and_special_entries_without_following_them(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "target.txt"
        target.write_bytes(b"target")
        (tmp_path / "link.txt").symlink_to(target)
        socket_path = tmp_path / "service.sock"
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(socket_path))
        try:
            result = ICloudDriveService(root=tmp_path).read("")
        finally:
            sock.close()

        assert isinstance(result, ICloudDirectoryListing)
        kinds = {entry.name: entry.kind for entry in result.entries}
        assert kinds["link.txt"] == "symlink"
        assert kinds["service.sock"] == "other"

    def test_unreadable_entry_metadata_does_not_fail_directory_listing(
        self, tmp_path: Path
    ) -> None:
        blocked = tmp_path / "blocked.txt"
        blocked.write_bytes(b"blocked")
        real_lstat = os.lstat

        def selective_lstat(path):
            if Path(path) == blocked:
                raise PermissionError("denied")
            return real_lstat(path)

        service = ICloudDriveService(root=tmp_path)
        with patch("mag.services.icloud_drive.os.lstat", side_effect=selective_lstat):
            result = service.read("")

        assert isinstance(result, ICloudDirectoryListing)
        entry = result.entries[0]
        assert entry.kind == "other"
        assert entry.size is None
        assert entry.modified_at is None

    def test_reads_binary_file_metadata(self, tmp_path: Path) -> None:
        source = tmp_path / "image.bin"
        source.write_bytes(b"\x00\xffbinary")
        service = ICloudDriveService(root=tmp_path)

        result = service.read("image.bin")

        assert isinstance(result, ICloudFile)
        assert result.path == source
        assert result.media_type == "application/octet-stream"

    @pytest.mark.parametrize(
        "path",
        ["/etc/passwd", "../outside", "folder/../outside", "./file", "folder//file"],
    )
    def test_rejects_invalid_paths(self, tmp_path: Path, path: str) -> None:
        service = ICloudDriveService(root=tmp_path)

        with pytest.raises(ICloudDriveError) as exc_info:
            service.read(path)

        assert exc_info.value.code == "invalid_path"
        assert str(tmp_path) not in str(exc_info.value)

    def test_rejects_symlink_target_and_symlink_parent(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / f"{tmp_path.name}-outside"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"secret")
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
        service = ICloudDriveService(root=tmp_path)

        for path in ("linked", "linked/secret.txt"):
            with pytest.raises(ICloudDriveError) as exc_info:
                service.read(path)
            assert exc_info.value.code == "symlink_forbidden"

    def test_rejects_missing_and_special_direct_reads(self, tmp_path: Path) -> None:
        fifo = tmp_path / "events.fifo"
        os.mkfifo(fifo)
        service = ICloudDriveService(root=tmp_path)

        with pytest.raises(ICloudDriveError) as missing:
            service.read("missing.txt")
        with pytest.raises(ICloudDriveError) as special:
            service.read("events.fifo")

        assert missing.value.code == "not_found"
        assert special.value.code == "unsupported_type"

    def test_permission_error_is_sanitized(self, tmp_path: Path) -> None:
        service = ICloudDriveService(root=tmp_path)

        with patch(
            "mag.services.icloud_drive.os.lstat",
            side_effect=PermissionError("private absolute path detail"),
        ):
            with pytest.raises(ICloudDriveError) as exc_info:
                service.read("")

        assert exc_info.value.code == "permission_denied"
        assert str(tmp_path) not in str(exc_info.value.to_detail())
```

- [ ] **Step 2: Run the service read tests and verify RED**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudDriveReads -v
```

Expected: collection fails because `mag.services.icloud_drive` does not exist.

- [ ] **Step 3: Implement errors, path validation, listings, and reads**

Create `src/mag/services/icloud_drive.py`:

```python
"""Filesystem service for paths beneath ~/Library/Mobile Documents."""

from __future__ import annotations

import errno
import mimetypes
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mag.models.icloud import ICloudDirectoryListing, ICloudEntry


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
```

- [ ] **Step 4: Run the read tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudDriveReads -v
```

Expected: all read, listing, traversal, symlink, and special-file tests pass.

- [ ] **Step 5: Commit safe read support**

```bash
git add src/mag/services/icloud_drive.py tests/test_icloud.py
git commit -m "feat: add safe iCloud Drive reads"
```

## Task 3: Atomic Streamed PUT

**Files:**
- Modify: `src/mag/services/icloud_drive.py`
- Modify: `tests/test_icloud.py`

- [ ] **Step 1: Add failing atomic upload tests**

Add `import errno` to the standard-library import block, then append:

```python
import errno
```

Append to `tests/test_icloud.py`:

```python
async def byte_chunks(*chunks: bytes):
    for chunk in chunks:
        yield chunk


async def failing_chunks():
    yield b"partial"
    raise RuntimeError("stream interrupted")


class TestICloudDriveWrites:
    async def test_put_creates_and_replaces_binary_file_atomically(self, tmp_path: Path) -> None:
        (tmp_path / "folder").mkdir()
        service = ICloudDriveService(root=tmp_path)

        created_entry, created = await service.put(
            "folder/data.bin", byte_chunks(b"\x00", b"\xffpayload")
        )

        assert created is True
        assert created_entry.kind == "file"
        assert (tmp_path / "folder" / "data.bin").read_bytes() == b"\x00\xffpayload"

        replaced_entry, created = await service.put(
            "folder/data.bin", byte_chunks(b"replacement")
        )

        assert created is False
        assert replaced_entry.size == len(b"replacement")
        assert (tmp_path / "folder" / "data.bin").read_bytes() == b"replacement"

    async def test_failed_put_preserves_destination_and_removes_temp_file(
        self, tmp_path: Path
    ) -> None:
        destination = tmp_path / "data.bin"
        destination.write_bytes(b"original")
        service = ICloudDriveService(root=tmp_path)

        with pytest.raises(ICloudDriveError) as exc_info:
            await service.put("data.bin", failing_chunks())

        assert exc_info.value.code == "filesystem_error"
        assert destination.read_bytes() == b"original"
        assert list(tmp_path.glob(".mag-upload-*")) == []

    @pytest.mark.parametrize("path", ["missing/file.txt", ""])
    async def test_put_rejects_missing_parent_and_root(self, tmp_path: Path, path: str) -> None:
        service = ICloudDriveService(root=tmp_path)

        with pytest.raises(ICloudDriveError) as exc_info:
            await service.put(path, byte_chunks(b"data"))

        assert exc_info.value.code in {"invalid_path", "parent_missing"}

    async def test_put_rejects_directory_symlink_and_special_targets(self, tmp_path: Path) -> None:
        (tmp_path / "folder").mkdir()
        (tmp_path / "source.txt").write_bytes(b"source")
        (tmp_path / "link.txt").symlink_to(tmp_path / "source.txt")
        os.mkfifo(tmp_path / "events.fifo")
        service = ICloudDriveService(root=tmp_path)

        for path in ("folder", "link.txt", "events.fifo"):
            with pytest.raises(ICloudDriveError):
                await service.put(path, byte_chunks(b"data"))

    async def test_put_rejects_symlink_parent(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / f"{tmp_path.name}-put-outside"
        outside.mkdir()
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
        service = ICloudDriveService(root=tmp_path)

        with pytest.raises(ICloudDriveError) as exc_info:
            await service.put("linked/new.txt", byte_chunks(b"data"))

        assert exc_info.value.code == "symlink_forbidden"

    async def test_put_maps_insufficient_storage_without_leaking_paths(
        self, tmp_path: Path
    ) -> None:
        service = ICloudDriveService(root=tmp_path)
        error = OSError(errno.ENOSPC, "no space", str(tmp_path / "private"))

        with patch("mag.services.icloud_drive.tempfile.mkstemp", side_effect=error):
            with pytest.raises(ICloudDriveError) as exc_info:
                await service.put("file.txt", byte_chunks(b"data"))

        assert exc_info.value.code == "insufficient_storage"
        assert str(tmp_path) not in str(exc_info.value.to_detail())
```

- [ ] **Step 2: Run upload tests and verify RED**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudDriveWrites -v
```

Expected: tests fail with `AttributeError: 'ICloudDriveService' object has no attribute 'put'`.

- [ ] **Step 3: Implement atomic streamed writes**

Add the upload imports to `src/mag/services/icloud_drive.py`:

```python
import asyncio
import tempfile
from collections.abc import AsyncIterable
```

Add these methods inside `ICloudDriveService` in `src/mag/services/icloud_drive.py`:

```python
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
            with os.fdopen(descriptor, "wb") as temporary_file:
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
```

- [ ] **Step 4: Run upload tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudDriveWrites -v
```

Expected: all streamed create, replace, cleanup, parent, and target-type tests pass.

- [ ] **Step 5: Commit atomic PUT support**

```bash
git add src/mag/services/icloud_drive.py tests/test_icloud.py
git commit -m "feat: add atomic iCloud Drive uploads"
```

## Task 4: File Move And Delete Operations

**Files:**
- Modify: `src/mag/services/icloud_drive.py`
- Modify: `tests/test_icloud.py`

- [ ] **Step 1: Add failing move and delete tests**

Append to `tests/test_icloud.py`:

```python
class TestICloudDriveMutations:
    def test_move_renames_file_into_existing_directory(self, tmp_path: Path) -> None:
        (tmp_path / "source.txt").write_bytes(b"content")
        (tmp_path / "archive").mkdir()
        service = ICloudDriveService(root=tmp_path)

        entry = service.move("source.txt", "archive/renamed.txt")

        assert entry.path == "archive/renamed.txt"
        assert not (tmp_path / "source.txt").exists()
        assert (tmp_path / "archive" / "renamed.txt").read_bytes() == b"content"

    def test_move_never_overwrites_existing_destination(self, tmp_path: Path) -> None:
        (tmp_path / "source.txt").write_bytes(b"source")
        (tmp_path / "destination.txt").write_bytes(b"destination")
        service = ICloudDriveService(root=tmp_path)

        with pytest.raises(ICloudDriveError) as exc_info:
            service.move("source.txt", "destination.txt")

        assert exc_info.value.code == "conflict"
        assert (tmp_path / "source.txt").read_bytes() == b"source"
        assert (tmp_path / "destination.txt").read_bytes() == b"destination"

    @pytest.mark.parametrize(
        ("source", "destination", "expected_code"),
        [
            ("missing.txt", "new.txt", "not_found"),
            ("source.txt", "source.txt", "invalid_path"),
            ("source.txt", "missing/new.txt", "parent_missing"),
        ],
    )
    def test_move_rejects_invalid_operations(
        self, tmp_path: Path, source: str, destination: str, expected_code: str
    ) -> None:
        (tmp_path / "source.txt").write_bytes(b"source")
        service = ICloudDriveService(root=tmp_path)

        with pytest.raises(ICloudDriveError) as exc_info:
            service.move(source, destination)

        assert exc_info.value.code == expected_code

    def test_delete_removes_regular_file(self, tmp_path: Path) -> None:
        (tmp_path / "delete.txt").write_bytes(b"delete")
        service = ICloudDriveService(root=tmp_path)

        result = service.delete("delete.txt")

        assert result.path == "delete.txt"
        assert not (tmp_path / "delete.txt").exists()

    def test_delete_rejects_missing_directory_symlink_and_special_targets(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "folder").mkdir()
        (tmp_path / "source.txt").write_bytes(b"source")
        (tmp_path / "link.txt").symlink_to(tmp_path / "source.txt")
        os.mkfifo(tmp_path / "events.fifo")
        service = ICloudDriveService(root=tmp_path)

        expected = {
            "missing.txt": "not_found",
            "folder": "unsupported_type",
            "link.txt": "symlink_forbidden",
            "events.fifo": "unsupported_type",
        }
        for path, code in expected.items():
            with pytest.raises(ICloudDriveError) as exc_info:
                service.delete(path)
            assert exc_info.value.code == code

    def test_move_and_delete_reject_symlink_parent(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / f"{tmp_path.name}-mutation-outside"
        outside.mkdir()
        (outside / "source.txt").write_bytes(b"source")
        (tmp_path / "local.txt").write_bytes(b"local")
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
        service = ICloudDriveService(root=tmp_path)

        operations = (
            lambda: service.move("linked/source.txt", "moved.txt"),
            lambda: service.move("local.txt", "linked/moved.txt"),
            lambda: service.delete("linked/source.txt"),
        )
        for operation in operations:
            with pytest.raises(ICloudDriveError) as exc_info:
                operation()
            assert exc_info.value.code == "symlink_forbidden"

    def test_move_rejects_directory_and_root_sources(self, tmp_path: Path) -> None:
        (tmp_path / "folder").mkdir()
        service = ICloudDriveService(root=tmp_path)

        with pytest.raises(ICloudDriveError) as directory_error:
            service.move("folder", "renamed")
        with pytest.raises(ICloudDriveError) as root_error:
            service.move("", "renamed")

        assert directory_error.value.code == "unsupported_type"
        assert root_error.value.code == "invalid_path"

    def test_mutations_reject_traversal_and_root_delete(self, tmp_path: Path) -> None:
        (tmp_path / "source.txt").write_bytes(b"source")
        service = ICloudDriveService(root=tmp_path)

        operations = (
            lambda: service.move("source.txt", "../outside.txt"),
            lambda: service.delete("../outside.txt"),
            lambda: service.delete(""),
        )
        for operation in operations:
            with pytest.raises(ICloudDriveError) as exc_info:
                operation()
            assert exc_info.value.code == "invalid_path"
```

- [ ] **Step 2: Run mutation tests and verify RED**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudDriveMutations -v
```

Expected: tests fail because `move` and `delete` are not defined.

- [ ] **Step 3: Implement regular-file validation, move, and delete**

Add the model import:

```python
from mag.models.icloud import ICloudDeleteResponse, ICloudDirectoryListing, ICloudEntry
```

Add these methods inside `ICloudDriveService`:

```python
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
```

- [ ] **Step 4: Run mutation tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudDriveMutations -v
```

Expected: all move, conflict, missing-parent, delete, directory, symlink, and special-file tests pass.

- [ ] **Step 5: Run all service tests**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudDriveReads tests/test_icloud.py::TestICloudDriveWrites tests/test_icloud.py::TestICloudDriveMutations -v
```

Expected: all iCloud service tests pass without accessing the real Mobile Documents directory.

- [ ] **Step 6: Commit move and delete support**

```bash
git add src/mag/services/icloud_drive.py tests/test_icloud.py
git commit -m "feat: add iCloud Drive file mutations"
```

## Task 5: Authenticated FastAPI Endpoints

**Files:**
- Create: `src/mag/routers/icloud.py`
- Modify: `src/mag/main.py:19-174,266-280`
- Modify: `tests/test_icloud.py`

- [ ] **Step 1: Add failing router tests**

Change the mock import to include `AsyncMock`, and add `ICloudDeleteResponse` to the existing `mag.models.icloud` grouped import:

```python
from unittest.mock import AsyncMock, patch

from mag.models.icloud import (
    ICloudDeleteResponse,
    ICloudDirectoryListing,
    ICloudEntry,
    ICloudMove,
)
```

Append these tests to `tests/test_icloud.py`:

```python
class TestICloudRouter:
    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self) -> dict[str, str]:
        return {"X-API-Key": "test-api-key-for-unit-tests-only-1234567890"}

    def test_routes_require_api_key(self, client: TestClient) -> None:
        assert client.get("/v1/icloud").status_code == 401
        assert client.get("/v1/icloud/file.txt").status_code == 401
        assert client.put("/v1/icloud/file.txt", content=b"data").status_code == 401
        assert client.patch(
            "/v1/icloud/file.txt", json={"destination": "moved.txt"}
        ).status_code == 401
        assert client.delete("/v1/icloud/file.txt").status_code == 401

    def test_cors_preflight_allows_put(self, client: TestClient) -> None:
        response = client.options(
            "/v1/icloud/file.txt",
            headers={
                "Origin": "http://localhost:8123",
                "Access-Control-Request-Method": "PUT",
            },
        )

        assert response.status_code == 200
        assert "PUT" in response.headers["access-control-allow-methods"]

    def test_root_mutations_return_bad_request(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        for method in ("PUT", "PATCH", "DELETE"):
            response = client.request(method, "/v1/icloud", headers=auth_headers)
            assert response.status_code == 400
            assert response.json()["detail"]["code"] == "invalid_path"

    def test_root_and_directory_get_return_json_listing(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        listing = ICloudDirectoryListing(
            path="", entries=[ICloudEntry(path="container", name="container", kind="directory")]
        )
        with patch("mag.routers.icloud.icloud_drive.read", return_value=listing) as read:
            response = client.get("/v1/icloud", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["entries"][0]["name"] == "container"
        read.assert_called_once_with("")

    def test_file_get_returns_exact_binary_body_and_content_type(
        self, tmp_path: Path, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        source = tmp_path / "image.png"
        source.write_bytes(b"\x89PNG\x00payload")
        file_result = ICloudFile(path=source, media_type="image/png")
        with patch("mag.routers.icloud.icloud_drive.read", return_value=file_result):
            response = client.get("/v1/icloud/image.png", headers=auth_headers)

        assert response.status_code == 200
        assert response.content == b"\x89PNG\x00payload"
        assert response.headers["content-type"] == "image/png"
        assert response.headers["content-length"] == str(len(b"\x89PNG\x00payload"))
        assert "last-modified" in response.headers

    @pytest.mark.parametrize(("created", "status_code"), [(True, 201), (False, 200)])
    def test_put_streams_body_and_returns_dynamic_status(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        created: bool,
        status_code: int,
    ) -> None:
        entry = ICloudEntry(path="file.bin", name="file.bin", kind="file", size=4)

        async def consume_body(path, chunks):
            assert path == "file.bin"
            assert b"".join([chunk async for chunk in chunks]) == b"data"
            return entry, created

        with patch(
            "mag.routers.icloud.icloud_drive.put", new_callable=AsyncMock
        ) as put:
            put.side_effect = consume_body
            response = client.put(
                "/v1/icloud/file.bin", headers=auth_headers, content=b"data"
            )

        assert response.status_code == status_code
        assert response.json()["size"] == 4
        assert put.await_count == 1

    def test_patch_rejects_blank_destination(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            "/v1/icloud/file.txt",
            headers=auth_headers,
            json={"destination": "   "},
        )

        assert response.status_code == 422

    def test_patch_moves_file_and_delete_returns_status(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        moved = ICloudEntry(
            path="archive/new.txt", name="new.txt", kind="file", size=7
        )
        with patch("mag.routers.icloud.icloud_drive.move", return_value=moved) as move:
            patch_response = client.patch(
                "/v1/icloud/old.txt",
                headers=auth_headers,
                json={"destination": "archive/new.txt"},
            )
        with patch(
            "mag.routers.icloud.icloud_drive.delete",
            return_value=ICloudDeleteResponse(path="archive/new.txt"),
        ):
            delete_response = client.delete(
                "/v1/icloud/archive/new.txt", headers=auth_headers
            )

        assert patch_response.status_code == 200
        assert patch_response.json()["path"] == "archive/new.txt"
        move.assert_called_once_with("old.txt", "archive/new.txt")
        assert delete_response.json() == {
            "status": "deleted",
            "path": "archive/new.txt",
        }

    @pytest.mark.parametrize(
        ("code", "status_code"),
        [
            ("invalid_path", 400),
            ("parent_missing", 400),
            ("unsupported_type", 400),
            ("symlink_forbidden", 403),
            ("permission_denied", 403),
            ("not_found", 404),
            ("conflict", 409),
            ("insufficient_storage", 507),
            ("filesystem_error", 500),
        ],
    )
    def test_service_errors_map_to_http_statuses(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        code: str,
        status_code: int,
    ) -> None:
        error = ICloudDriveError(code, "Operation failed", "file.txt")
        with patch("mag.routers.icloud.icloud_drive.read", side_effect=error):
            response = client.get("/v1/icloud/file.txt", headers=auth_headers)

        assert response.status_code == status_code
        assert response.json()["detail"] == {
            "error": "Operation failed",
            "code": code,
            "path": "file.txt",
        }


class TestICloudRouterCapabilities:
    def test_read_and_write_capabilities_are_independent(self, monkeypatch) -> None:
        monkeypatch.setenv("MAG_ICLOUD_READ", "false")
        monkeypatch.setenv("MAG_ICLOUD_WRITE", "true")
        get_settings.cache_clear()
        client = TestClient(app)
        headers = {"X-API-Key": "test-api-key-for-unit-tests-only-1234567890"}
        entry = ICloudEntry(path="file.txt", name="file.txt", kind="file", size=4)

        assert client.get("/v1/icloud", headers=headers).status_code == 403
        with patch(
            "mag.routers.icloud.icloud_drive.put", new_callable=AsyncMock
        ) as put:
            put.return_value = (entry, True)
            assert client.put(
                "/v1/icloud/file.txt", headers=headers, content=b"data"
            ).status_code == 201

        monkeypatch.setenv("MAG_ICLOUD_READ", "true")
        monkeypatch.setenv("MAG_ICLOUD_WRITE", "false")
        get_settings.cache_clear()
        listing = ICloudDirectoryListing(path="", entries=[])
        with patch("mag.routers.icloud.icloud_drive.read", return_value=listing):
            assert client.get("/v1/icloud", headers=headers).status_code == 200
        assert client.put(
            "/v1/icloud/file.txt", headers=headers, content=b"data"
        ).status_code == 403

        get_settings.cache_clear()
```

- [ ] **Step 2: Run router tests and verify RED**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudRouter tests/test_icloud.py::TestICloudRouterCapabilities -v
```

Expected: requests return `404` because the iCloud router is not mounted.

- [ ] **Step 3: Implement the iCloud router**

Create `src/mag/routers/icloud.py`:

```python
"""iCloud Drive filesystem API router."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from mag.auth import verify_api_key
from mag.config import get_settings
from mag.models.icloud import (
    ICloudDeleteResponse,
    ICloudDirectoryListing,
    ICloudEntry,
    ICloudMove,
)
from mag.services.icloud_drive import ICloudDriveError, ICloudDriveService, ICloudFile

router = APIRouter(prefix="/icloud", dependencies=[Depends(verify_api_key)])
icloud_drive = ICloudDriveService()

_ERROR_STATUS = {
    "invalid_path": 400,
    "parent_missing": 400,
    "unsupported_type": 400,
    "symlink_forbidden": 403,
    "permission_denied": 403,
    "not_found": 404,
    "conflict": 409,
    "insufficient_storage": 507,
    "filesystem_error": 500,
}


def _require_capability(capability: str) -> None:
    settings = get_settings()
    enabled = {
        "read": settings.icloud_read,
        "write": settings.icloud_write,
    }.get(capability, False)
    if not enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"Capability 'icloud.{capability}' is disabled",
                "hint": f"Set MAG_ICLOUD_{capability.upper()}=true to enable",
            },
        )


def _http_error(error: ICloudDriveError) -> HTTPException:
    return HTTPException(
        status_code=_ERROR_STATUS.get(error.code, 500),
        detail=error.to_detail(),
    )


def _read_path(path: str) -> ICloudDirectoryListing | FileResponse:
    _require_capability("read")
    try:
        result = icloud_drive.read(path)
    except ICloudDriveError as error:
        raise _http_error(error) from None
    if isinstance(result, ICloudFile):
        return FileResponse(path=result.path, media_type=result.media_type)
    return result


@router.get("", response_model=None)
async def get_icloud_root() -> ICloudDirectoryListing | Response:
    """List the Mobile Documents root."""
    return _read_path("")


@router.api_route("", methods=["PUT", "PATCH", "DELETE"], include_in_schema=False)
async def reject_icloud_root_mutation() -> None:
    """Reject mutations without a relative file path."""
    _require_capability("write")
    raise _http_error(ICloudDriveError("invalid_path", "A file path is required", ""))


@router.get("/{path:path}", response_model=None)
async def get_icloud_path(path: str) -> ICloudDirectoryListing | Response:
    """List a directory or stream a regular file."""
    return _read_path(path)


@router.put("/{path:path}", response_model=ICloudEntry)
async def put_icloud_file(path: str, request: Request, response: Response) -> ICloudEntry:
    """Create or fully replace a regular file from the raw request body."""
    _require_capability("write")
    try:
        entry, created = await icloud_drive.put(path, request.stream())
    except ICloudDriveError as error:
        raise _http_error(error) from None
    response.status_code = 201 if created else 200
    return entry


@router.patch("/{path:path}", response_model=ICloudEntry)
async def move_icloud_file(path: str, data: ICloudMove) -> ICloudEntry:
    """Rename or move a regular file without overwriting a destination."""
    _require_capability("write")
    try:
        return icloud_drive.move(path, data.destination)
    except ICloudDriveError as error:
        raise _http_error(error) from None


@router.delete("/{path:path}", response_model=ICloudDeleteResponse)
async def delete_icloud_file(path: str) -> ICloudDeleteResponse:
    """Delete one regular file."""
    _require_capability("write")
    try:
        return icloud_drive.delete(path)
    except ICloudDriveError as error:
        raise _http_error(error) from None
```

- [ ] **Step 4: Mount the router and update application metadata**

In `src/mag/main.py`, change the router import and description:

```python
from mag.routers import icloud, messages, notes, reminders

app = FastAPI(
    title="Mac Agent Gateway",
    description=(
        "Local macOS HTTP API gateway for Apple Reminders, Messages, Notes, and iCloud Drive"
    ),
```

Allow `PUT` in CORS and mount the router:

```python
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],

app.include_router(icloud.router, prefix="/v1", tags=["icloud"])
```

Add disabled capability logging after the Notes checks:

```python
    if not caps.icloud.read:
        disabled.append("icloud.read")
    if not caps.icloud.write:
        disabled.append("icloud.write")
```

- [ ] **Step 5: Run router tests and verify GREEN**

Run:

```bash
uv run pytest tests/test_icloud.py::TestICloudRouter tests/test_icloud.py::TestICloudRouterCapabilities -v
```

Expected: authentication, JSON listing, binary response, dynamic PUT status, move/delete, capability, and error mapping tests pass.

- [ ] **Step 6: Run all iCloud tests**

Run:

```bash
uv run pytest tests/test_icloud.py -v
```

Expected: every iCloud model, capability, service, and router test passes.

- [ ] **Step 7: Commit the API routes**

```bash
git add src/mag/routers/icloud.py src/mag/main.py tests/test_icloud.py
git commit -m "feat: expose iCloud Drive file API"
```

## Task 6: Configuration And User Documentation

**Files:**
- Modify: `.env.example:82-102`
- Modify: `README.md:7,151-161,189-210,242-254,361-451,671-684`

- [ ] **Step 1: Document environment capability flags**

Add to `.env.example` after Notes capabilities:

```dotenv

# iCloud Drive capabilities
MAG_ICLOUD_READ=true        # List Mobile Documents directories and read files
MAG_ICLOUD_WRITE=true       # Create, replace, move, and delete files
```

- [ ] **Step 2: Add iCloud Drive to feature and configuration sections**

Replace the opening description with:

```markdown
A local macOS HTTP API gateway that exposes Apple-protected capabilities (Reminders, Messages, Notes, and iCloud Drive) via a stable, agent-friendly REST API.
```

Update the "What This Means for You" paragraph to say that assistants can work with Apple Reminders, Messages, Notes, and files stored in Mobile Documents. Add these configuration lines beside the existing Notes flags:

```dotenv
MAG_ICLOUD_READ=true             # Enable/disable directory listing and file reads
MAG_ICLOUD_WRITE=true            # Enable/disable file create/replace/move/delete
```

Add this feature bullet:

```markdown
- **iCloud Drive API** — List directories and read, create, replace, move, or delete files across `~/Library/Mobile Documents`
```

State in prerequisites that filesystem access may prompt macOS for Files and Folders or Full Disk Access depending on how MAG is launched and the user's macOS privacy settings.

- [ ] **Step 3: Add the endpoint reference and examples**

Insert after the Notes API section:

````markdown
### iCloud Drive API

All `{path}` values are relative to `~/Library/Mobile Documents`. This includes the user-visible iCloud Drive container at `com~apple~CloudDocs` and application-specific containers.

> **Security:** Application containers can contain sensitive or app-private data. Enabling `MAG_ICLOUD_READ` or `MAG_ICLOUD_WRITE` grants authenticated clients access across the full Mobile Documents tree, not only `com~apple~CloudDocs`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/icloud` | List the Mobile Documents root |
| GET | `/v1/icloud/{path}` | List a directory or stream a file |
| PUT | `/v1/icloud/{path}` | Create or fully replace a file from the raw body |
| PATCH | `/v1/icloud/{path}` | Rename or move a file |
| DELETE | `/v1/icloud/{path}` | Delete a file |

```bash
# List the user-visible iCloud Drive root
curl -H "X-API-Key: $KEY" \
  "http://localhost:8123/v1/icloud/com~apple~CloudDocs"

# Upload or replace a binary file
curl -X PUT -H "X-API-Key: $KEY" \
  --data-binary @report.pdf \
  "http://localhost:8123/v1/icloud/com~apple~CloudDocs/Reports/report.pdf"

# Download a file
curl -H "X-API-Key: $KEY" \
  "http://localhost:8123/v1/icloud/com~apple~CloudDocs/Reports/report.pdf" \
  --output report.pdf

# Rename or move a file
curl -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"destination":"com~apple~CloudDocs/Archive/report.pdf"}' \
  "http://localhost:8123/v1/icloud/com~apple~CloudDocs/Reports/report.pdf"
```

**iCloud Drive Safety And Limitations:**

- Directory access is read-only and non-recursive; directory create, move, rename, and delete are blocked.
- Symbolic links, traversal components, absolute paths, and special files are blocked.
- `PUT` requires an existing parent directory and atomically replaces regular files.
- `PATCH` requires a full destination filename and returns `409` if that destination exists.
- Reading an evicted iCloud file may cause macOS to download it. MAG does not expose sync state, version history, sharing links, or conflict resolution.
````

- [ ] **Step 4: Update the capabilities table**

Add rows to the README capabilities table:

```markdown
| `MAG_NOTES_READ` | true | List, search, and fetch notes |
| `MAG_NOTES_WRITE` | true | Create, update, move, and delete notes and folders |
| `MAG_ICLOUD_READ` | true | List Mobile Documents directories and read files |
| `MAG_ICLOUD_WRITE` | true | Create, replace, move, and delete files |
```

- [ ] **Step 5: Verify documentation formatting and commit**

Run:

```bash
git diff --check -- .env.example README.md
```

Expected: no whitespace errors.

Commit:

```bash
git add .env.example README.md
git commit -m "docs: document iCloud Drive API"
```

## Task 7: Full Verification And Security Regression Check

**Files:**
- Verify: `src/mag/models/icloud.py`
- Verify: `src/mag/services/icloud_drive.py`
- Verify: `src/mag/routers/icloud.py`
- Verify: `src/mag/config.py`
- Verify: `src/mag/main.py`
- Verify: `tests/test_icloud.py`
- Verify: `.env.example`
- Verify: `README.md`

- [ ] **Step 1: Run the focused iCloud suite**

```bash
uv run pytest tests/test_icloud.py -v
```

Expected: all iCloud tests pass and every service test uses `tmp_path` rather than the real `~/Library/Mobile Documents` directory.

- [ ] **Step 2: Run existing security tests**

```bash
uv run pytest tests/test_security.py -v
```

Expected: all authentication, CORS, error-sanitization, and path-traversal regression tests pass.

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest -v
```

Expected: the complete repository test suite passes.

- [ ] **Step 4: Run Ruff on all changed Python files**

```bash
uv run ruff check src/mag/models/icloud.py src/mag/services/icloud_drive.py src/mag/routers/icloud.py src/mag/config.py src/mag/main.py tests/test_icloud.py
```

Expected: `All checks passed!`

- [ ] **Step 5: Verify formatting, route registration, and working-tree scope**

```bash
git diff --check
uv run python -c "from mag.main import app; print(sorted((r.path, ','.join(sorted(r.methods or []))) for r in app.routes if r.path.startswith('/v1/icloud')))"
git status --short
```

Expected: no whitespace errors; output lists root `GET`, the hidden root-mutation rejection route, and path `GET`, `PUT`, `PATCH`, and `DELETE`; status contains only intentional changes or pre-existing unrelated files.

- [ ] **Step 6: Review the final diff for security invariants**

```bash
git diff f9d4b55..HEAD -- src/mag/models/icloud.py src/mag/services/icloud_drive.py src/mag/routers/icloud.py src/mag/config.py src/mag/main.py tests/test_icloud.py .env.example README.md
```

Confirm all of the following from the diff:

- No endpoint accepts an absolute filesystem path.
- No mutation can target the Mobile Documents root or a directory.
- Existing path components are checked with `os.lstat`, not followed with `Path.resolve()`.
- Failed uploads remove `.mag-upload-*` files and preserve existing destinations.
- Service errors contain only client-relative paths.
- Tests never instantiate the default production service for filesystem mutations.

- [ ] **Step 7: Commit any verification-only corrections**

If verification required code or test corrections, commit exactly those files:

```bash
git add src/mag/models/icloud.py src/mag/services/icloud_drive.py src/mag/routers/icloud.py src/mag/config.py src/mag/main.py tests/test_icloud.py .env.example README.md
git commit -m "fix: harden iCloud Drive API verification"
```

If no correction was needed, do not create an empty commit.
