"""Tests for the iCloud Drive filesystem API."""

import errno
import os
import socket
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mag.config import get_settings
from mag.main import app
from mag.models.icloud import (
    ICloudDeleteResponse,
    ICloudDirectoryListing,
    ICloudEntry,
    ICloudMove,
)
from mag.services.icloud_drive import (
    ICloudDriveError,
    ICloudDriveService,
    ICloudFile,
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
        # macOS AF_UNIX path limit is 104 chars; use a short system tmp path for
        # the socket file itself, then hard-link it into tmp_path for the listing.
        with tempfile.TemporaryDirectory() as short_tmp:
            socket_path = Path(short_tmp) / "s.sock"
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(socket_path))
            # Create the socket entry inside tmp_path via hard-link so it shows up
            # in the directory listing without requiring a long bind path.
            dest_sock = tmp_path / "service.sock"
            dest_sock.hardlink_to(socket_path)
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

        expected = {
            "folder": "unsupported_type",
            "link.txt": "symlink_forbidden",
            "events.fifo": "unsupported_type",
        }
        for path, code in expected.items():
            with pytest.raises(ICloudDriveError) as exc_info:
                await service.put(path, byte_chunks(b"data"))
            assert exc_info.value.code == code

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
        try:
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
        finally:
            get_settings.cache_clear()
