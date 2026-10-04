"""Service adapter for macnotesapp."""

from datetime import datetime
from typing import Any

from mag.models.notes import Note, NoteAccount, NoteAttachment, NoteFolder, NotesError


class NotesAppError(Exception):
    """Exception raised when Notes.app integration fails."""

    def __init__(
        self,
        message: str,
        code: int = -1,
        details: str = "",
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        """Convert to error response dict."""
        return NotesError(
            error=self.message,
            code=self.code,
            details=self.details,
            hint=self.hint,
        ).model_dump()


def _notes_app() -> Any:
    """Create a NotesApp instance, wrapping import and initialization errors."""
    try:
        from macnotesapp import NotesApp
    except ImportError as e:
        raise NotesAppError(
            message="macnotesapp not found",
            code=-1,
            details=str(e),
            hint="Install with: pip install macnotesapp",
        ) from e

    try:
        return NotesApp()
    except Exception as e:
        raise NotesAppError(
            message="Failed to initialize Notes.app",
            code=-1,
            details=str(e),
            hint="Grant automation permissions to the terminal running MAG.",
        ) from e


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read either a simple attribute or a zero-argument method."""
    value = getattr(obj, name, default)
    if callable(value):
        try:
            return value()
        except TypeError:
            return default
    return value


def _parse_datetime(value: Any) -> datetime | None:
    """Convert common macnotesapp date values to datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _parse_attachment(raw: Any) -> NoteAttachment:
    """Parse a macnotesapp Attachment-like object."""
    return NoteAttachment(
        id=_get_attr(raw, "id"),
        name=_get_attr(raw, "name"),
        content_identifier=_get_attr(raw, "content_identifier"),
        url=_get_attr(raw, "URL", _get_attr(raw, "url")),
        creation_date=_parse_datetime(_get_attr(raw, "creation_date")),
        modification_date=_parse_datetime(_get_attr(raw, "modification_date")),
    )


def _parse_note(raw: Any) -> Note:
    """Parse a macnotesapp Note-like object."""
    attachments = _get_attr(raw, "attachments", []) or []
    return Note(
        id=str(_get_attr(raw, "id", "")),
        name=str(_get_attr(raw, "name", "")),
        account=_get_attr(raw, "account"),
        folder=_get_attr(raw, "folder"),
        body=_get_attr(raw, "body"),
        plaintext=_get_attr(raw, "plaintext"),
        creation_date=_parse_datetime(_get_attr(raw, "creation_date")),
        modification_date=_parse_datetime(_get_attr(raw, "modification_date")),
        password_protected=bool(_get_attr(raw, "password_protected", False)),
        attachments=[_parse_attachment(attachment) for attachment in attachments],
    )


async def list_notes(
    accounts: list[str] | None = None,
    name: list[str] | None = None,
    body: list[str] | None = None,
    text: list[str] | None = None,
    password_protected: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Note]:
    """List notes with optional filters."""
    try:
        notes = _notes_app().notes(
            accounts=accounts,
            name=name,
            body=body,
            text=text,
            password_protected=password_protected,
        )
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to list notes", details=str(e)) from e
    return [_parse_note(note) for note in notes[offset : offset + limit]]


async def get_note(note_id: str) -> Note | None:
    """Get one note by id."""
    try:
        notes = _notes_app().notes(id=[note_id])
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to get note", details=str(e)) from e
    if not notes:
        return None
    return _parse_note(notes[0])


async def create_note(
    name: str,
    body: str,
    account: str | None = None,
    folder: str | None = None,
    attachments: list[str] | None = None,
) -> Note:
    """Create a note."""
    try:
        app = _notes_app()
        if account or folder:
            raw = app.account(account).make_note(
                name,
                body,
                folder=folder,
                attachments=attachments or None,
            )
        else:
            raw = app.make_note(name, body, attachments=attachments or None)
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to create note", details=str(e)) from e
    return _parse_note(raw)


async def update_note(
    note_id: str,
    name: str | None = None,
    body: str | None = None,
) -> Note | None:
    """Update a note's title and/or body."""
    try:
        notes = _notes_app().notes(id=[note_id])
        if not notes:
            return None
        note = notes[0]
        if name is not None:
            note.name = name
        if body is not None:
            note.body = body
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to update note", details=str(e)) from e
    return _parse_note(note)


async def move_note(note_id: str, folder: str, account: str | None = None) -> Note | None:
    """Move a note to a different top-level folder."""
    try:
        app = _notes_app()
        notes = app.notes(id=[note_id])
        if not notes:
            return None
        note = notes[0]
        if account is not None:
            app.account(account)
        note.move(folder)
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to move note", details=str(e)) from e
    return _parse_note(note)


async def delete_note(note_id: str) -> dict[str, str] | None:
    """Delete a note."""
    try:
        notes = _notes_app().notes(id=[note_id])
        if not notes:
            return None
        notes[0].delete()
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to delete note", details=str(e)) from e
    return {"status": "deleted", "id": note_id}


async def list_accounts() -> list[NoteAccount]:
    """List Notes accounts."""
    try:
        return [NoteAccount(name=str(account)) for account in _notes_app().accounts]
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to list accounts", details=str(e)) from e


async def list_folders(account: str | None = None) -> list[NoteFolder]:
    """List folders for an account."""
    try:
        folders = _notes_app().account(account).folders
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to list folders", details=str(e)) from e
    return [NoteFolder(name=str(folder)) for folder in folders]


async def create_folder(name: str, account: str | None = None) -> NoteFolder:
    """Create a top-level Notes folder."""
    try:
        folder = _notes_app().account(account).make_folder(name)
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to create folder", details=str(e)) from e
    return NoteFolder(name=str(_get_attr(folder, "name", name)))


async def delete_folder(name: str, account: str | None = None) -> dict[str, str]:
    """Delete a top-level Notes folder."""
    try:
        _notes_app().account(account).delete_folder(name)
    except NotesAppError:
        raise
    except Exception as e:
        raise NotesAppError("Failed to delete folder", details=str(e)) from e
    return {"status": "deleted", "name": name}
