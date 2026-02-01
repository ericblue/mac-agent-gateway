"""Messages API router for Mac Agent Gateway."""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from mag.auth import verify_api_key
from mag.config import get_settings

# Rate limiter for sensitive endpoints
limiter = Limiter(key_func=get_remote_address)
from mag.models.messages import (
    Contact,
    ContactResolveResult,
    ContactUpsert,
    ExtractedLink,
    Message,
    MessageReply,
    MessageSend,
    MessageSendResponse,
    Thread,
)
from mag.services import imsg
from mag.services.contacts import get_contact_cache
from mag.services.imsg import ImsgError

logger = logging.getLogger(__name__)


def _validate_attachment_paths(files: list[str]) -> None:
    """Validate that attachment paths are allowed.
    
    Security: Prevents path traversal attacks by restricting attachments
    to configured directories only.
    
    Raises HTTPException 403 if a path is not allowed.
    """
    if not files:
        return
    
    settings = get_settings()
    allowed_dirs = settings.get_attachment_allowed_dirs()
    
    # If no allowed directories configured, all paths are allowed (less secure)
    if not allowed_dirs:
        return
    
    for file_path in files:
        try:
            resolved = Path(file_path).expanduser().resolve()
        except (OSError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail={"error": f"Invalid file path: {file_path}", "hint": str(e)},
            )
        
        # Check if the file is within any allowed directory
        is_allowed = any(
            resolved == allowed_dir or allowed_dir in resolved.parents
            for allowed_dir in allowed_dirs
        )
        
        if not is_allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": f"File path not in allowed directories: {file_path}",
                    "hint": "Configure MAG_ATTACHMENT_ALLOWED_DIRS to specify allowed directories",
                    "allowed_directories": [str(d) for d in sorted(allowed_dirs)],
                },
            )

router = APIRouter(prefix="/messages", dependencies=[Depends(verify_api_key)])


def _handle_cli_error(e: ImsgError) -> HTTPException:
    """Convert ImsgError to HTTPException with helpful details."""
    return HTTPException(status_code=502, detail=e.to_dict())


def _require_capability(capability: str) -> None:
    """Check if a capability is enabled, raise 403 if not."""
    settings = get_settings()
    capability_map = {
        "read": settings.messages_read,
        "search": settings.messages_search,
        "send": settings.messages_send,
        "watch": settings.messages_watch,
        "contacts": settings.messages_contacts,
        "attachments": settings.messages_attachments,
    }
    if not capability_map.get(capability, False):
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"Capability 'messages.{capability}' is disabled",
                "hint": f"Set MAG_MESSAGES_{capability.upper()}=true to enable",
            },
        )


# =============================================================================
# Threads
# =============================================================================


@router.get("/threads", response_model=list[Thread])
async def list_threads(
    limit: int = Query(default=20, ge=1, le=100, description="Maximum threads to return"),
) -> list[Thread]:
    """List recent message threads.

    Returns threads sorted by most recent activity.
    """
    _require_capability("read")
    try:
        return await imsg.list_threads(limit=limit)
    except ImsgError as e:
        raise _handle_cli_error(e)


@router.get("/threads/lookup", response_model=Thread)
async def get_thread_by_recipient(
    recipient: str = Query(..., description="Recipient identifier (phone, email, or handle)"),
) -> Thread:
    """Find the thread for a specific recipient.

    Returns the most recent thread containing this participant.
    Accepts phone numbers, email addresses, or iMessage handles.
    """
    _require_capability("read")
    try:
        thread_id = await imsg.find_thread_by_recipient(recipient)
        if not thread_id:
            raise HTTPException(
                status_code=404, detail=f"No thread found for recipient {recipient}"
            )
        thread = await imsg.get_thread(thread_id)
        if not thread:
            raise HTTPException(
                status_code=404, detail=f"Thread {thread_id} not found"
            )
        return thread
    except ImsgError as e:
        raise _handle_cli_error(e)


@router.get("/threads/{thread_id}", response_model=Thread)
async def get_thread(thread_id: int) -> Thread:
    """Get a specific thread by ID."""
    _require_capability("read")
    try:
        thread = await imsg.get_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")
        return thread
    except ImsgError as e:
        raise _handle_cli_error(e)


@router.get("/threads/{thread_id}/messages", response_model=list[Message])
async def get_messages(
    thread_id: int,
    limit: int = Query(default=50, ge=1, le=500, description="Maximum messages to return"),
    start: datetime | None = Query(default=None, description="Start of time range (ISO format)"),
    end: datetime | None = Query(default=None, description="End of time range (ISO format)"),
    participants: str | None = Query(
        default=None, description="Comma-separated participant phones/emails"
    ),
    attachments: bool = Query(default=False, description="Include attachment metadata"),
) -> list[Message]:
    """Get message history for a thread.

    Returns messages sorted oldest to newest.
    """
    _require_capability("read")
    try:
        participant_list = participants.split(",") if participants else None
        return await imsg.get_messages(
            thread_id=thread_id,
            limit=limit,
            start=start,
            end=end,
            participants=participant_list,
            include_attachments=attachments,
        )
    except ImsgError as e:
        raise _handle_cli_error(e)


@router.get("/history", response_model=list[Message])
async def get_messages_by_recipient(
    recipient: str = Query(
        ..., description="Recipient identifier (phone, email, or handle)"
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum messages to return"),
    start: datetime | None = Query(
        default=None, description="Start of time range (ISO format)"
    ),
    end: datetime | None = Query(default=None, description="End of time range (ISO format)"),
    attachments: bool = Query(default=False, description="Include attachment metadata"),
    days_back: int = Query(
        default=365, ge=1, le=3650, description="Days back to fetch (if no start date)"
    ),
) -> list[Message]:
    """Get message history with a specific recipient.

    Finds the thread containing this recipient and returns messages.
    Accepts phone numbers, email addresses, or iMessage handles.
    Returns an empty list if no thread is found with this participant.

    Use `days_back` to control how far back to fetch when no `start` date is given.
    """
    _require_capability("read")
    # Default to fetching recent messages if no start date provided
    effective_start = start
    if effective_start is None:
        effective_start = datetime.now() - timedelta(days=days_back)

    try:
        return await imsg.get_messages_by_recipient(
            recipient=recipient,
            limit=limit,
            start=effective_start,
            end=end,
            include_attachments=attachments,
        )
    except ImsgError as e:
        raise _handle_cli_error(e)


@router.get("/threads/{thread_id}/watch")
async def watch_thread(
    thread_id: int,
    since_rowid: int | None = Query(
        default=None, description="Only return messages after this rowid"
    ),
    debounce_ms: int = Query(default=250, ge=50, le=5000, description="Debounce interval in ms"),
    attachments: bool = Query(default=False, description="Include attachment metadata"),
) -> StreamingResponse:
    """Watch for new messages in a thread (Server-Sent Events).

    Returns a stream of SSE events as new messages arrive.
    Connect with EventSource or any SSE client.
    """
    _require_capability("watch")

    async def event_generator():
        try:
            async for message in imsg.watch_messages(
                thread_id=thread_id,
                since_rowid=since_rowid,
                debounce_ms=debounce_ms,
                include_attachments=attachments,
            ):
                # Format as SSE event
                data = message.model_dump_json()
                yield f"event: message\ndata: {data}\n\n"
        except ImsgError as e:
            # Sanitize error data - only include safe fields
            error_data = {"error": "Stream error", "code": e.code}
            if "permission" in e.stderr.lower() or "access" in e.stderr.lower():
                error_data["hint"] = "Check system permissions for imsg"
            yield f"event: error\ndata: {error_data}\n\n"
        except asyncio.CancelledError:
            logger.debug("Watch stream cancelled for thread %d", thread_id)
        except Exception as e:
            # Security: Don't expose internal exception details to clients
            logger.exception("Watch stream error for thread %d", thread_id)
            yield f'event: error\ndata: {{"error": "Stream error"}}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# Messages
# =============================================================================


@router.post("/send", response_model=MessageSendResponse, status_code=201)
@limiter.limit("10/minute")  # Security: Rate limit message sending
async def send_message(
    request: Request,  # Required for rate limiter
    data: MessageSend,
    dry_run: bool = Query(default=False, description="Return command without executing"),
) -> MessageSendResponse:
    """Send a message.

    The recipient can be a phone number or email address.
    Optionally attach files by providing absolute paths.

    Use dry_run=true to see the exact imsg command without executing.
    
    Note: File attachments are restricted to configured directories (MAG_ATTACHMENT_ALLOWED_DIRS).
    Rate limited to 10 requests per minute.
    """
    _require_capability("send")
    settings = get_settings()

    # Security: Validate attachment paths before proceeding
    _validate_attachment_paths(data.files)

    # Check send allowlist if configured
    allowlist = settings.get_send_allowlist()
    if allowlist and data.to not in allowlist:
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"Recipient '{data.to}' is not in the send allowlist",
                "hint": "Add recipient to MAG_MESSAGES_SEND_ALLOWLIST or clear the allowlist",
            },
        )

    # Check recipient in contacts if required
    if not settings.allow_unknown_recipients:
        cache = get_contact_cache()
        result = cache.resolve(phone=data.to, email=data.to)
        if result.status == "not_found":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "Unknown recipient",
                    "hint": "Add recipient to contacts first, "
                    "or set MAG_ALLOW_UNKNOWN_RECIPIENTS=true",
                },
            )

    try:
        return await imsg.send_message_v2(data, dry_run=dry_run)
    except ImsgError as e:
        raise _handle_cli_error(e)


@router.post("/reply", response_model=MessageSendResponse, status_code=201)
@limiter.limit("10/minute")  # Security: Rate limit message sending
async def reply_to_thread(request: Request, data: MessageReply) -> MessageSendResponse:
    """Reply to a thread or recipient.

    Provide either `thread_id` or `recipient`:
    - If `recipient` is provided, sends directly to that address (phone/email/handle).
    - If `thread_id` is provided, determines recipient from thread history.

    If neither is provided, returns an error.
    Rate limited to 10 requests per minute.
    """
    _require_capability("send")
    if not data.thread_id and not data.recipient:
        raise HTTPException(
            status_code=400,
            detail="Either thread_id or recipient must be provided",
        )

    # Check send allowlist if configured and recipient is provided
    settings = get_settings()
    allowlist = settings.get_send_allowlist()
    if allowlist and data.recipient and data.recipient not in allowlist:
        raise HTTPException(
            status_code=403,
            detail={
                "error": f"Recipient '{data.recipient}' is not in the send allowlist",
                "hint": "Add recipient to MAG_MESSAGES_SEND_ALLOWLIST or clear the allowlist",
            },
        )

    try:
        return await imsg.reply_to_thread(
            text=data.text,
            thread_id=data.thread_id,
            recipient=data.recipient,
        )
    except ImsgError as e:
        raise _handle_cli_error(e)


@router.get("/search", response_model=list[Message])
async def search_messages(
    q: str = Query(..., min_length=1, description="Search query text"),
    thread_id: int | None = Query(default=None, description="Thread ID to search within"),
    recipient: str | None = Query(
        default=None, description="Recipient identifier (phone, email, or handle)"
    ),
    limit: int = Query(default=100, ge=1, le=1000, description="Max matching results to return"),
    scan_limit: int = Query(
        default=5000, ge=100, le=50000, description="Max messages to scan for matches"
    ),
    start: datetime | None = Query(default=None, description="Start of time range"),
    end: datetime | None = Query(default=None, description="End of time range"),
    days_back: int = Query(
        default=365, ge=1, le=3650, description="Days back to search (if no start date)"
    ),
) -> list[Message]:
    """Search messages by text content.

    This performs an in-memory search within fetched messages.
    Either thread_id or recipient must be provided to scope the search.

    - `scan_limit` controls how many messages to fetch and search through
    - `limit` controls the maximum number of matching results returned
    - Use `days_back` to control how far back to search when no `start` date is given
    """
    _require_capability("search")
    if not thread_id and not recipient:
        raise HTTPException(
            status_code=400,
            detail="Either thread_id or recipient must be provided to scope the search",
        )

    # Default to searching recent messages if no start date provided
    effective_start = start
    if effective_start is None:
        effective_start = datetime.now() - timedelta(days=days_back)

    try:
        return await imsg.search_messages(
            query=q,
            thread_id=thread_id,
            recipient=recipient,
            scan_limit=scan_limit,
            result_limit=limit,
            start=effective_start,
            end=end,
        )
    except ImsgError as e:
        raise _handle_cli_error(e)


@router.get("/links", response_model=list[ExtractedLink])
async def extract_links(
    recipient: str | None = Query(
        default=None, description="Recipient identifier (phone, email, or handle)"
    ),
    thread_id: int | None = Query(default=None, description="Thread ID to search"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum links to return"),
    message_limit: int = Query(
        default=500, ge=1, le=5000, description="Maximum messages to scan"
    ),
    from_me: bool | None = Query(
        default=None, description="Filter: True=my links, False=their links, None=all"
    ),
    start: datetime | None = Query(
        default=None, description="Start of date range (ISO format, e.g. 2025-01-01)"
    ),
    end: datetime | None = Query(
        default=None, description="End of date range (ISO format, e.g. 2025-01-31)"
    ),
    days_back: int = Query(
        default=365, ge=1, le=3650, description="Days back to search (if no start date)"
    ),
) -> list[ExtractedLink]:
    """Extract HTTP/HTTPS links from messages.

    Finds all URLs in message history and returns them with context.
    Provide either `recipient` or `thread_id` to scope the search.

    Use `from_me=false` to get only links sent by the other person.
    Use `start` and `end` for explicit date range, or `days_back` for relative.

    Examples:
    - GET /messages/links?recipient=+15551234567&from_me=false&limit=10
    - GET /messages/links?recipient=+15551234567&start=2025-01-01&end=2025-01-31
    """
    _require_capability("search")
    if not thread_id and not recipient:
        raise HTTPException(
            status_code=400,
            detail="Either thread_id or recipient must be provided",
        )

    # Calculate effective start date
    effective_start = start
    if effective_start is None:
        effective_start = datetime.now() - timedelta(days=days_back)

    try:
        return await imsg.extract_links(
            recipient=recipient,
            thread_id=thread_id,
            limit=limit,
            message_limit=message_limit,
            from_me=from_me,
            start=effective_start,
            end=end,
        )
    except ImsgError as e:
        raise _handle_cli_error(e)


# =============================================================================
# Attachments
# =============================================================================

# Security: Allowed base directories for attachment downloads
# Only files within these directories can be served
_ATTACHMENT_ALLOWED_BASES = [
    Path.home() / "Library" / "Messages" / "Attachments",
    Path("/var/folders"),  # Temporary files location on macOS
]


def _validate_attachment_download_path(file_path: str) -> Path:
    """Validate that an attachment path is safe to serve.
    
    Security: Only allows files within the Messages Attachments directory
    to prevent arbitrary file access.
    
    Returns the resolved Path if valid, raises HTTPException if not.
    """
    try:
        resolved = Path(file_path).expanduser().resolve()
    except (OSError, ValueError) as e:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid file path", "hint": str(e)},
        )
    
    # Check if the file is within any allowed base directory
    is_allowed = any(
        resolved == base or base in resolved.parents
        for base in _ATTACHMENT_ALLOWED_BASES
    )
    
    if not is_allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Access denied: file is not a message attachment",
                "hint": "Only files in ~/Library/Messages/Attachments/ can be downloaded",
            },
        )
    
    if not resolved.exists():
        raise HTTPException(
            status_code=404,
            detail={"error": "Attachment file not found", "path": str(resolved)},
        )
    
    if not resolved.is_file():
        raise HTTPException(
            status_code=400,
            detail={"error": "Path is not a file"},
        )
    
    return resolved


@router.get("/attachments/download")
async def download_attachment(
    path: str = Query(..., description="Full path to the attachment file"),
) -> FileResponse:
    """Download an attachment file.
    
    Security: Only files within ~/Library/Messages/Attachments/ can be downloaded.
    Use the `original_path` field from message attachments.
    
    Example:
        GET /messages/attachments/download?path=/Users/you/Library/Messages/Attachments/...
    """
    _require_capability("attachments")
    
    # Validate and resolve the path
    resolved_path = _validate_attachment_download_path(path)
    
    # Determine media type
    import mimetypes
    media_type, _ = mimetypes.guess_type(str(resolved_path))
    if not media_type:
        media_type = "application/octet-stream"
    
    return FileResponse(
        path=resolved_path,
        media_type=media_type,
        filename=resolved_path.name,
    )


@router.get("/attachments/info")
async def get_attachment_info(
    path: str = Query(..., description="Full path to the attachment file"),
) -> dict:
    """Get information about an attachment file without downloading.
    
    Returns file metadata including size, type, and whether it exists.
    
    Security: Only files within ~/Library/Messages/Attachments/ can be queried.
    """
    _require_capability("attachments")
    
    try:
        resolved_path = _validate_attachment_download_path(path)
    except HTTPException as e:
        if e.status_code == 404:
            return {
                "exists": False,
                "path": path,
            }
        raise
    
    import mimetypes
    media_type, _ = mimetypes.guess_type(str(resolved_path))
    
    stat = resolved_path.stat()
    
    return {
        "exists": True,
        "path": str(resolved_path),
        "filename": resolved_path.name,
        "size_bytes": stat.st_size,
        "mime_type": media_type or "application/octet-stream",
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


# =============================================================================
# Contacts
# =============================================================================


@router.post("/contacts/upsert", response_model=Contact, status_code=201)
async def upsert_contact(data: ContactUpsert) -> Contact:
    """Create or update a contact.

    If a contact with matching phone or email exists, it will be updated
    by merging the provided data. Otherwise, a new contact is created.
    """
    _require_capability("contacts")
    cache = get_contact_cache()
    return cache.upsert(data)


@router.get("/contacts/resolve", response_model=ContactResolveResult)
async def resolve_contact(
    phone: str | None = Query(default=None, description="Phone number to match"),
    email: str | None = Query(default=None, description="Email address to match"),
    name: str | None = Query(default=None, description="Name or alias to match"),
) -> ContactResolveResult:
    """Resolve a contact by phone, email, or name.

    Resolution order:
    1. Direct phone match
    2. Email match
    3. Exact name match (case-insensitive)
    4. Substring name/alias match if unambiguous

    Returns status: "ok", "ambiguous", or "not_found".
    """
    _require_capability("contacts")
    if not phone and not email and not name:
        raise HTTPException(
            status_code=400,
            detail="At least one of phone, email, or name must be provided",
        )

    cache = get_contact_cache()
    return cache.resolve(phone=phone, email=email, name=name)


@router.get("/contacts/search", response_model=list[Contact])
async def search_contacts(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum results"),
) -> list[Contact]:
    """Search contacts by substring match.

    Searches across name, aliases, phones, and emails.
    """
    _require_capability("contacts")
    cache = get_contact_cache()
    return cache.search(q, limit=limit)


@router.get("/contacts", response_model=list[Contact])
async def list_contacts() -> list[Contact]:
    """List all contacts in the cache."""
    _require_capability("contacts")
    cache = get_contact_cache()
    return cache.list_all()


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: str) -> None:
    """Delete a contact by ID."""
    _require_capability("contacts")
    cache = get_contact_cache()
    if not cache.delete(contact_id):
        raise HTTPException(status_code=404, detail=f"Contact {contact_id} not found")
