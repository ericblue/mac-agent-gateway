"""Configuration settings for Mac Agent Gateway."""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="MAG_", env_file=".env", env_file_encoding="utf-8")

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8123
    api_key: str
    log_level: str = "INFO"

    # Logging settings
    log_dir: Path | None = None  # Directory for log files (None = stdout only)
    log_max_bytes: int = 10 * 1024 * 1024  # 10 MB max per log file
    log_backup_count: int = 5  # Keep 5 rotated log files
    log_access: bool = True  # Log API access requests

    # imsg CLI settings
    imsg_path: str = "imsg"
    default_region: str = "US"

    # Contacts cache settings
    contacts_path: Path = Path("./data/contacts.json")

    # Safety settings
    allow_unknown_recipients: bool = True

    # PII filtering mode: "regex" (pattern-based), "" (disabled)
    pii_filter: str = "regex"

    # Send allowlist (comma-separated phone numbers/emails)
    # If set, only these recipients can receive messages
    # If empty, all recipients are allowed (subject to other settings)
    messages_send_allowlist: str = ""

    # File attachment allowed directories (comma-separated absolute paths)
    # If set, only files in these directories can be attached
    # If empty, all readable files are allowed (less secure)
    # Example: ~/Downloads,~/Pictures,~/Documents
    attachment_allowed_dirs: str = ""

    def get_attachment_allowed_dirs(self) -> set[Path]:
        """Parse the attachment allowed directories into a set of resolved paths."""
        if not self.attachment_allowed_dirs.strip():
            return set()
        dirs = set()
        for d in self.attachment_allowed_dirs.split(","):
            d = d.strip()
            if d:
                # Expand ~ and resolve to absolute path
                dirs.add(Path(d).expanduser().resolve())
        return dirs

    # ==========================================================================
    # Capability Settings (what operations are allowed)
    # ==========================================================================

    # Messages capabilities
    messages_read: bool = True  # GET /threads, /history, /threads/{id}/messages
    messages_search: bool = True  # GET /search, /links
    messages_send: bool = True  # POST /send, /reply
    messages_watch: bool = True  # GET /threads/{id}/watch (SSE)
    messages_contacts: bool = True  # Contacts cache CRUD
    messages_attachments: bool = True  # GET /attachments (download files)

    def get_send_allowlist(self) -> set[str]:
        """Parse the send allowlist into a set of normalized recipients."""
        if not self.messages_send_allowlist.strip():
            return set()
        # Split by comma and normalize (strip whitespace, lowercase for emails)
        recipients = set()
        for r in self.messages_send_allowlist.split(","):
            r = r.strip()
            if r:
                recipients.add(r)
        return recipients

    # Reminders capabilities
    reminders_read: bool = True  # GET /reminders, /reminders/lists
    reminders_write: bool = True  # POST/PATCH/DELETE reminders and lists


class Capabilities(BaseModel):
    """Structured capabilities response."""

    class MessagesCapabilities(BaseModel):
        read: bool
        search: bool
        send: bool
        send_allowlist: list[str] | None = None  # None = unrestricted, list = only these recipients
        send_allowlist_active: bool = False  # True if allowlist is configured (for redacted responses)
        watch: bool
        contacts: bool
        attachments: bool  # Download message attachments

    class RemindersCapabilities(BaseModel):
        read: bool
        write: bool

    messages: MessagesCapabilities
    reminders: RemindersCapabilities


@lru_cache
def get_settings() -> Settings:
    """Get application settings (cached)."""
    return Settings()


def get_capabilities() -> Capabilities:
    """Get current capabilities based on settings."""
    settings = get_settings()
    allowlist = settings.get_send_allowlist()
    return Capabilities(
        messages=Capabilities.MessagesCapabilities(
            read=settings.messages_read,
            search=settings.messages_search,
            send=settings.messages_send,
            send_allowlist=sorted(allowlist) if allowlist else None,
            send_allowlist_active=bool(allowlist),
            watch=settings.messages_watch,
            contacts=settings.messages_contacts,
            attachments=settings.messages_attachments,
        ),
        reminders=Capabilities.RemindersCapabilities(
            read=settings.reminders_read,
            write=settings.reminders_write,
        ),
    )
