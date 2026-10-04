"""Tests for Notes API endpoints and service adapter."""

import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mag.config import get_settings
from mag.models.notes import (
    Note,
    NoteAccount,
    NoteAttachment,
    NoteCreate,
    NoteFolder,
    NoteFolderCreate,
    NoteMove,
    NoteUpdate,
)


class TestNoteModels:
    """Tests for Notes Pydantic models."""

    def test_note_create_defaults_attachments_to_empty_list(self) -> None:
        """Should default attachments to an empty list."""
        data = NoteCreate(name="Trip", body="<p>Plan</p>")

        assert data.name == "Trip"
        assert data.body == "<p>Plan</p>"
        assert data.account is None
        assert data.folder is None
        assert data.attachments == []

    def test_note_create_rejects_empty_name(self) -> None:
        """Should reject an empty note name."""
        with pytest.raises(ValidationError):
            NoteCreate(name="", body="<p>Plan</p>")

    def test_note_response_accepts_optional_fields(self) -> None:
        """Should accept optional note fields and attachment metadata."""
        note = Note(
            id="note-1",
            name="Trip",
            account="iCloud",
            folder="Notes",
            body="<p>Plan</p>",
            plaintext="Plan",
            creation_date=datetime(2026, 5, 31, 12, 0, 0),
            modification_date=None,
            password_protected=False,
            attachments=[
                NoteAttachment(
                    id="att-1",
                    name="file.txt",
                    content_identifier=None,
                    url=None,
                    creation_date=None,
                    modification_date=None,
                )
            ],
        )

        assert note.attachments[0].name == "file.txt"

    def test_note_update_requires_at_least_one_field(self) -> None:
        """Should reject empty note update payloads."""
        with pytest.raises(ValidationError):
            NoteUpdate()

    def test_note_update_accepts_name_or_body(self) -> None:
        """Should accept either title or body updates."""
        assert NoteUpdate(name="New title").name == "New title"
        assert NoteUpdate(body="<p>New body</p>").body == "<p>New body</p>"

    def test_note_move_requires_folder(self) -> None:
        """Should require a destination folder."""
        with pytest.raises(ValidationError):
            NoteMove(folder="")

    def test_note_folder_create_requires_name(self) -> None:
        """Should require a folder name."""
        with pytest.raises(ValidationError):
            NoteFolderCreate(name="")


class TestNotesService:
    """Tests for the macnotesapp service adapter."""

    def test_parse_note_handles_missing_optional_fields(self) -> None:
        """Should parse note-like objects with missing optional fields."""
        from mag.services.notesapp import _parse_note

        raw = SimpleNamespace(
            id="note-1",
            name="Trip",
            account="iCloud",
            folder="Notes",
            body="<p>Plan</p>",
            plaintext="Plan",
            password_protected=False,
            attachments=[],
        )

        note = _parse_note(raw)

        assert note.id == "note-1"
        assert note.account == "iCloud"
        assert note.attachments == []

    def test_parse_attachment_handles_uppercase_url_attribute(self) -> None:
        """Should parse macnotesapp Attachment.URL into response url."""
        from mag.services.notesapp import _parse_attachment

        raw = SimpleNamespace(
            id="att-1",
            name="file.txt",
            content_identifier="cid",
            URL="file:///tmp/file.txt",
        )

        attachment = _parse_attachment(raw)

        assert attachment.url == "file:///tmp/file.txt"

    async def test_list_notes_passes_filters_and_applies_pagination(self) -> None:
        """Should pass filters to macnotesapp and apply response pagination."""
        from mag.services.notesapp import list_notes

        raw_notes = [
            SimpleNamespace(id=f"note-{i}", name=f"Note {i}", account="iCloud", folder="Notes")
            for i in range(3)
        ]
        app = Mock()
        app.notes.return_value = raw_notes

        with patch("mag.services.notesapp._notes_app", return_value=app):
            notes = await list_notes(
                accounts=["iCloud"],
                name=["Trip"],
                body=None,
                text=["Plan"],
                password_protected=False,
                limit=1,
                offset=1,
            )

        app.notes.assert_called_once_with(
            accounts=["iCloud"],
            name=["Trip"],
            body=None,
            text=["Plan"],
            password_protected=False,
        )
        assert [note.id for note in notes] == ["note-1"]

    async def test_get_note_returns_none_when_id_not_found(self) -> None:
        """Should return None when macnotesapp finds no note."""
        from mag.services.notesapp import get_note

        app = Mock()
        app.notes.return_value = []

        with patch("mag.services.notesapp._notes_app", return_value=app):
            note = await get_note("missing")

        assert note is None

    async def test_create_note_uses_account_when_provided(self) -> None:
        """Should create through the selected account when account or folder is provided."""
        from mag.services.notesapp import create_note

        raw_note = SimpleNamespace(id="note-1", name="Trip", account="iCloud", folder="Notes")
        account = Mock()
        account.make_note.return_value = raw_note
        app = Mock()
        app.account.return_value = account

        with patch("mag.services.notesapp._notes_app", return_value=app):
            note = await create_note(
                name="Trip",
                body="<p>Plan</p>",
                account="iCloud",
                folder="Travel",
                attachments=["/tmp/a.txt"],
            )

        app.account.assert_called_once_with("iCloud")
        account.make_note.assert_called_once_with(
            "Trip", "<p>Plan</p>", folder="Travel", attachments=["/tmp/a.txt"]
        )
        assert note.id == "note-1"

    async def test_list_accounts_returns_account_models(self) -> None:
        """Should return Notes account models."""
        from mag.services.notesapp import list_accounts

        app = Mock()
        app.accounts = ["iCloud", "On My Mac"]

        with patch("mag.services.notesapp._notes_app", return_value=app):
            accounts = await list_accounts()

        assert [account.name for account in accounts] == ["iCloud", "On My Mac"]

    async def test_list_folders_uses_default_account_when_omitted(self) -> None:
        """Should list folders for the default account when account is omitted."""
        from mag.services.notesapp import list_folders

        account = Mock()
        account.folders = ["Notes", "Travel"]
        app = Mock()
        app.account.return_value = account

        with patch("mag.services.notesapp._notes_app", return_value=app):
            folders = await list_folders(account=None)

        app.account.assert_called_once_with(None)
        assert [folder.name for folder in folders] == ["Notes", "Travel"]

    async def test_update_note_sets_name_and_body(self) -> None:
        """Should update note title and body, then return the parsed note."""
        from mag.services.notesapp import update_note

        raw_note = SimpleNamespace(
            id="note-1", name="Old", body="<p>Old</p>", account="iCloud", folder="Notes"
        )
        app = Mock()
        app.notes.return_value = [raw_note]

        with patch("mag.services.notesapp._notes_app", return_value=app):
            note = await update_note("note-1", name="New", body="<p>New</p>")

        assert raw_note.name == "New"
        assert raw_note.body == "<p>New</p>"
        assert note.id == "note-1"

    async def test_update_note_returns_none_when_missing(self) -> None:
        """Should return None when updating a missing note."""
        from mag.services.notesapp import update_note

        app = Mock()
        app.notes.return_value = []

        with patch("mag.services.notesapp._notes_app", return_value=app):
            note = await update_note("missing", name="New", body=None)

        assert note is None

    async def test_move_note_calls_note_move(self) -> None:
        """Should move a note to the requested folder."""
        from mag.services.notesapp import move_note

        raw_note = Mock()
        raw_note.id = "note-1"
        raw_note.name = "Trip"
        raw_note.account = "iCloud"
        raw_note.folder = "Archive"
        raw_note.body = None
        raw_note.plaintext = None
        raw_note.attachments = []
        app = Mock()
        app.notes.return_value = [raw_note]

        with patch("mag.services.notesapp._notes_app", return_value=app):
            note = await move_note("note-1", folder="Archive", account="iCloud")

        app.account.assert_called_once_with("iCloud")
        raw_note.move.assert_called_once_with("Archive")
        assert note.id == "note-1"

    async def test_delete_note_calls_note_delete(self) -> None:
        """Should delete a note and return a status dictionary."""
        from mag.services.notesapp import delete_note

        raw_note = Mock()
        app = Mock()
        app.notes.return_value = [raw_note]

        with patch("mag.services.notesapp._notes_app", return_value=app):
            result = await delete_note("note-1")

        raw_note.delete.assert_called_once_with()
        assert result == {"status": "deleted", "id": "note-1"}

    async def test_create_folder_returns_folder_model(self) -> None:
        """Should create a folder through the selected account."""
        from mag.services.notesapp import create_folder

        account = Mock()
        account.make_folder.return_value = SimpleNamespace(name="Work")
        app = Mock()
        app.account.return_value = account

        with patch("mag.services.notesapp._notes_app", return_value=app):
            folder = await create_folder(name="Work", account="iCloud")

        app.account.assert_called_once_with("iCloud")
        account.make_folder.assert_called_once_with("Work")
        assert folder.name == "Work"

    async def test_delete_folder_returns_status(self) -> None:
        """Should delete a folder through the selected account."""
        from mag.services.notesapp import delete_folder

        account = Mock()
        app = Mock()
        app.account.return_value = account

        with patch("mag.services.notesapp._notes_app", return_value=app):
            result = await delete_folder(name="Work", account="iCloud")

        app.account.assert_called_once_with("iCloud")
        account.delete_folder.assert_called_once_with("Work")
        assert result == {"status": "deleted", "name": "Work"}

    def test_missing_macnotesapp_error_has_hint(self) -> None:
        """Should include an install hint when macnotesapp cannot be imported."""
        from mag.services.notesapp import NotesAppError, _notes_app

        with patch("builtins.__import__", side_effect=ImportError("missing")):
            with pytest.raises(NotesAppError) as exc_info:
                _notes_app()

        assert "macnotesapp not found" in exc_info.value.message
        assert "pip install macnotesapp" in exc_info.value.hint


class TestNotesRouter:
    """Tests for Notes API routes."""

    def test_list_notes_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should list notes and pass filters to the service."""
        note = Note(id="note-1", name="Trip", account="iCloud", folder="Notes")
        with patch("mag.routers.notes.notesapp.list_notes", new_callable=AsyncMock) as mock:
            mock.return_value = [note]
            response = client.get(
                "/v1/notes?account=iCloud&name=Trip&text=Plan&limit=10&offset=2",
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json()[0]["id"] == "note-1"
        mock.assert_called_once_with(
            accounts=["iCloud"],
            name=["Trip"],
            body=None,
            text=["Plan"],
            password_protected=None,
            limit=10,
            offset=2,
        )

    def test_get_note_returns_404_when_missing(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should return 404 when a note id is not found."""
        with patch("mag.routers.notes.notesapp.get_note", new_callable=AsyncMock) as mock:
            mock.return_value = None
            response = client.get("/v1/notes/missing", headers=auth_headers)

        assert response.status_code == 404

    def test_create_note_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should create and return a note."""
        note = Note(id="note-1", name="Trip", account="iCloud", folder="Travel")
        with patch("mag.routers.notes.notesapp.create_note", new_callable=AsyncMock) as mock:
            mock.return_value = note
            response = client.post(
                "/v1/notes",
                headers=auth_headers,
                json={
                    "name": "Trip",
                    "body": "<p>Plan</p>",
                    "account": "iCloud",
                    "folder": "Travel",
                },
            )

        assert response.status_code == 201
        mock.assert_called_once_with(
            name="Trip",
            body="<p>Plan</p>",
            account="iCloud",
            folder="Travel",
            attachments=[],
        )

    def test_update_note_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should update and return a note."""
        note = Note(id="note-1", name="New", account="iCloud", folder="Notes")
        with patch("mag.routers.notes.notesapp.update_note", new_callable=AsyncMock) as mock:
            mock.return_value = note
            response = client.patch(
                "/v1/notes/note-1",
                headers=auth_headers,
                json={"name": "New", "body": "<p>New</p>"},
            )

        assert response.status_code == 200
        assert response.json()["name"] == "New"
        mock.assert_called_once_with("note-1", name="New", body="<p>New</p>")

    def test_update_note_returns_404_when_missing(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should return 404 when updating a missing note."""
        with patch("mag.routers.notes.notesapp.update_note", new_callable=AsyncMock) as mock:
            mock.return_value = None
            response = client.patch(
                "/v1/notes/missing",
                headers=auth_headers,
                json={"name": "New"},
            )

        assert response.status_code == 404

    def test_move_note_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should move and return a note."""
        note = Note(id="note-1", name="Trip", account="iCloud", folder="Archive")
        with patch("mag.routers.notes.notesapp.move_note", new_callable=AsyncMock) as mock:
            mock.return_value = note
            response = client.post(
                "/v1/notes/note-1/move",
                headers=auth_headers,
                json={"folder": "Archive", "account": "iCloud"},
            )

        assert response.status_code == 200
        assert response.json()["folder"] == "Archive"
        mock.assert_called_once_with("note-1", folder="Archive", account="iCloud")

    def test_delete_note_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should delete a note."""
        with patch("mag.routers.notes.notesapp.delete_note", new_callable=AsyncMock) as mock:
            mock.return_value = {"status": "deleted", "id": "note-1"}
            response = client.delete("/v1/notes/note-1", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"status": "deleted", "id": "note-1"}

    def test_create_folder_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should create a Notes folder."""
        with patch("mag.routers.notes.notesapp.create_folder", new_callable=AsyncMock) as mock:
            mock.return_value = NoteFolder(name="Work")
            response = client.post(
                "/v1/notes/folders",
                headers=auth_headers,
                json={"name": "Work", "account": "iCloud"},
            )

        assert response.status_code == 201
        assert response.json() == {"name": "Work"}
        mock.assert_called_once_with(name="Work", account="iCloud")

    def test_delete_folder_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should delete a Notes folder."""
        with patch("mag.routers.notes.notesapp.delete_folder", new_callable=AsyncMock) as mock:
            mock.return_value = {"status": "deleted", "name": "Work"}
            response = client.delete(
                "/v1/notes/folders/Work?account=iCloud",
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json() == {"status": "deleted", "name": "Work"}
        mock.assert_called_once_with(name="Work", account="iCloud")

    def test_list_accounts_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should list Notes accounts."""
        with patch("mag.routers.notes.notesapp.list_accounts", new_callable=AsyncMock) as mock:
            mock.return_value = [NoteAccount(name="iCloud")]
            response = client.get("/v1/notes/accounts", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == [{"name": "iCloud"}]

    def test_list_folders_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should list folders for a Notes account."""
        with patch("mag.routers.notes.notesapp.list_folders", new_callable=AsyncMock) as mock:
            mock.return_value = [NoteFolder(name="Notes")]
            response = client.get("/v1/notes/folders?account=iCloud", headers=auth_headers)

        assert response.status_code == 200
        mock.assert_called_once_with(account="iCloud")

    def test_notes_service_error_returns_502(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should convert Notes service failures to 502."""
        from mag.services.notesapp import NotesAppError

        with patch("mag.routers.notes.notesapp.list_notes", new_callable=AsyncMock) as mock:
            mock.side_effect = NotesAppError(
                "macnotesapp not found", hint="Install with: pip install macnotesapp"
            )
            response = client.get("/v1/notes", headers=auth_headers)

        assert response.status_code == 502
        assert response.json()["detail"]["hint"] == "Install with: pip install macnotesapp"


class TestNotesCapabilities:
    """Tests for Notes capability configuration."""

    def test_capabilities_include_notes(self, client: TestClient) -> None:
        """Should advertise Notes capabilities."""
        response = client.get("/v1/capabilities")

        assert response.status_code == 200
        assert response.json()["notes"] == {"read": True, "write": True}

    def test_disabled_notes_read_returns_403(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should block read endpoints when Notes read is disabled."""
        os.environ["MAG_NOTES_READ"] = "false"
        get_settings.cache_clear()
        try:
            response = client.get("/v1/notes", headers=auth_headers)
        finally:
            os.environ.pop("MAG_NOTES_READ", None)
            get_settings.cache_clear()

        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "Capability 'notes.read' is disabled"

    def test_disabled_notes_write_returns_403(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should block write endpoints when Notes write is disabled."""
        os.environ["MAG_NOTES_WRITE"] = "false"
        get_settings.cache_clear()
        try:
            response = client.patch(
                "/v1/notes/note-1",
                headers=auth_headers,
                json={"name": "New"},
            )
        finally:
            os.environ.pop("MAG_NOTES_WRITE", None)
            get_settings.cache_clear()

        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "Capability 'notes.write' is disabled"


class TestNotesAttachmentPolicy:
    """Tests for Notes attachment path restrictions."""

    def test_create_note_blocks_attachment_outside_allowed_dirs(
        self,
        client: TestClient,
        auth_headers: dict,
        tmp_path: Path,
    ) -> None:
        """Should not call the service when an attachment path is outside allowed dirs."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        blocked = tmp_path / "blocked.txt"
        blocked.write_text("blocked")
        os.environ["MAG_ATTACHMENT_ALLOWED_DIRS"] = str(allowed)
        get_settings.cache_clear()
        try:
            with patch("mag.routers.notes.notesapp.create_note", new_callable=AsyncMock) as mock:
                response = client.post(
                    "/v1/notes",
                    headers=auth_headers,
                    json={
                        "name": "Trip",
                        "body": "<p>Plan</p>",
                        "attachments": [str(blocked)],
                    },
                )
        finally:
            os.environ.pop("MAG_ATTACHMENT_ALLOWED_DIRS", None)
            get_settings.cache_clear()

        assert response.status_code == 403
        mock.assert_not_called()
