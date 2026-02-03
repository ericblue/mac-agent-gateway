"""Service adapter for imsg CLI."""

import asyncio
import json
import logging
import re
import shlex
from datetime import datetime
from typing import Any, AsyncIterator

from mag.config import get_settings
from mag.models.messages import (
    Attachment,
    ExtractedLink,
    Message,
    MessageSend,
    MessageSendResponse,
    Participant,
    Thread,
)
from mag.services.pii import filter_pii

logger = logging.getLogger(__name__)


class ImsgError(Exception):
    """Exception raised when imsg CLI fails."""

    def __init__(self, message: str, code: int, stderr: str, command: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.stderr = stderr
        self.command = command

    def to_dict(self) -> dict[str, Any]:
        """Convert to error response dict."""
        result: dict[str, Any] = {"error": self.message, "code": self.code}
        if self.stderr:
            result["stderr"] = self.stderr[:500]  # Truncate long errors

        # Add hints for common permission issues
        stderr_lower = self.stderr.lower()
        if "full disk access" in stderr_lower or "permission" in stderr_lower:
            result["hint"] = (
                "imsg requires Full Disk Access. Go to System Settings > "
                "Privacy & Security > Full Disk Access and enable your terminal."
            )
        elif "automation" in stderr_lower:
            result["hint"] = (
                "imsg requires Automation permission to control Messages.app. "
                "Grant permission when prompted or check System Settings."
            )

        return result


def _get_imsg_path() -> str:
    """Get the path to the imsg binary."""
    return get_settings().imsg_path


async def _run_imsg(*args: str, timeout: float = 30.0) -> list[dict[str, Any]]:
    """Execute imsg with arguments and return parsed NDJSON output.

    Returns a list of parsed JSON objects (NDJSON format).
    """
    cmd = [_get_imsg_path(), *args]
    cmd_str = shlex.join(cmd)
    logger.debug("Executing: %s", cmd_str)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError:
        raise ImsgError(
            message="imsg not found. Install with: brew install steipete/tap/imsg",
            code=-1,
            stderr="",
            command=cmd_str,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ImsgError(
            message=f"imsg timed out after {timeout} seconds",
            code=-1,
            stderr="",
            command=cmd_str,
        )

    stdout_str = stdout.decode("utf-8", errors="replace")
    stderr_str = stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        raise ImsgError(
            message=f"imsg failed with exit code {proc.returncode}",
            code=proc.returncode or -1,
            stderr=stderr_str.strip(),
            command=cmd_str,
        )

    # Parse NDJSON (newline-delimited JSON)
    results: list[dict[str, Any]] = []
    for line_num, line in enumerate(stdout_str.strip().split("\n"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                results.append(obj)
            elif isinstance(obj, list):
                # Some commands return a JSON array on a single line
                results.extend(obj)
        except json.JSONDecodeError as e:
            logger.warning("NDJSON parse error at line %d: %s (line: %s)", line_num, e, line[:100])

    return results


async def _run_imsg_raw(*args: str, timeout: float = 30.0) -> str:
    """Execute imsg and return raw stdout."""
    cmd = [_get_imsg_path(), *args]
    cmd_str = shlex.join(cmd)
    logger.debug("Executing (raw): %s", cmd_str)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError:
        raise ImsgError(
            message="imsg not found. Install with: brew install steipete/tap/imsg",
            code=-1,
            stderr="",
            command=cmd_str,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ImsgError(
            message=f"imsg timed out after {timeout} seconds",
            code=-1,
            stderr="",
            command=cmd_str,
        )

    stdout_str = stdout.decode("utf-8", errors="replace")
    stderr_str = stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        # imsg outputs errors to stdout (not stderr), so include both in error
        error_output = stderr_str.strip() or stdout_str.strip()
        raise ImsgError(
            message=f"imsg failed with exit code {proc.returncode}",
            code=proc.returncode or -1,
            stderr=error_output,
            command=cmd_str,
        )

    return stdout_str


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime string."""
    if not value:
        return None
    try:
        # Handle Z suffix
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _format_datetime_for_imsg(dt: datetime) -> str:
    """Format a datetime for imsg CLI (ISO8601 with Z suffix, no microseconds)."""
    # Remove microseconds and add Z suffix for UTC
    return dt.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_attachment(data: dict[str, Any]) -> Attachment:
    """Parse an attachment from imsg output."""
    return Attachment(
        filename=data.get("filename"),
        transfer_name=data.get("transferName") or data.get("transfer_name"),
        uti=data.get("uti"),
        mime_type=data.get("mimeType") or data.get("mime_type"),
        total_bytes=data.get("totalBytes") or data.get("total_bytes"),
        is_sticker=data.get("isSticker", False) or data.get("is_sticker", False),
        original_path=data.get("originalPath") or data.get("original_path"),
        missing=data.get("missing", False),
    )


def _parse_participant(data: dict[str, Any] | str) -> Participant:
    """Parse a participant from imsg output."""
    if isinstance(data, str):
        return Participant(handle=data)
    return Participant(
        handle=data.get("handle") or data.get("id", ""),
        display_name=data.get("displayName") or data.get("display_name"),
    )


def _parse_thread(data: dict[str, Any]) -> Thread:
    """Parse a thread from imsg chats output."""
    participants = []
    if raw_participants := data.get("participants"):
        if isinstance(raw_participants, list):
            participants = [_parse_participant(p) for p in raw_participants]

    return Thread(
        id=int(data.get("id", 0)),
        name=data.get("displayName") or data.get("name"),
        identifier=data.get("identifier"),
        service=data.get("service"),
        last_message_at=_parse_datetime(data.get("lastMessageDate") or data.get("last_message_at")),
        participants=participants,
    )


def _parse_message(data: dict[str, Any]) -> Message:
    """Parse a message from imsg output."""
    attachments = []
    if raw_attachments := data.get("attachments"):
        if isinstance(raw_attachments, list):
            attachments = [_parse_attachment(a) for a in raw_attachments]

    # Clean binary/invisible chars, then apply PII filtering
    raw_text = data.get("text")
    text = filter_pii(_clean_text(raw_text)) if raw_text else filter_pii(raw_text)

    return Message(
        id=data.get("id") or data.get("rowid"),
        chat_id=int(data.get("chatId") or data.get("chat_id", 0)),
        guid=data.get("guid", ""),
        reply_to_guid=data.get("replyToGuid") or data.get("reply_to_guid"),
        sender=data.get("sender") or data.get("handle"),
        is_from_me=data.get("isFromMe", False) or data.get("is_from_me", False),
        text=text,
        created_at=_parse_datetime(data.get("date") or data.get("created_at")) or datetime.now(),
        attachments=attachments,
        reactions=data.get("reactions"),
    )


# =============================================================================
# Public API - Threads
# =============================================================================


async def list_threads(limit: int = 20) -> list[Thread]:
    """List recent message threads.

    Args:
        limit: Maximum number of threads to return.

    Returns:
        List of Thread objects, most recent first.
    """
    results = await _run_imsg("chats", "--limit", str(limit), "--json")
    return [_parse_thread(r) for r in results]


async def get_thread(thread_id: int) -> Thread | None:
    """Get a specific thread by ID.

    Args:
        thread_id: The thread ID.

    Returns:
        Thread if found, None otherwise.
    """
    # imsg doesn't have a get-by-id, so we list and filter
    results = await _run_imsg("chats", "--json")
    for r in results:
        if int(r.get("id", 0)) == thread_id:
            return _parse_thread(r)
    return None


# =============================================================================
# Public API - Messages
# =============================================================================


async def get_messages(
    thread_id: int,
    limit: int = 50,
    start: datetime | None = None,
    end: datetime | None = None,
    participants: list[str] | None = None,
    include_attachments: bool = False,
) -> list[Message]:
    """Get message history for a thread.

    Args:
        thread_id: The thread ID.
        limit: Maximum number of messages to return.
        start: Start of time range (ISO format).
        end: End of time range (ISO format).
        participants: Filter by participant phone/email.
        include_attachments: Whether to include attachment info.

    Returns:
        List of Message objects, oldest first.
    """
    args = ["history", "--chat-id", str(thread_id), "--limit", str(limit), "--json"]

    if start:
        args.extend(["--start", _format_datetime_for_imsg(start)])
    if end:
        args.extend(["--end", _format_datetime_for_imsg(end)])
    if participants:
        args.extend(["--participants", ",".join(participants)])
    if include_attachments:
        args.append("--attachments")

    # Scale timeout based on limit: ~8s per 100 messages observed, add buffer
    timeout = max(30.0, (limit / 100) * 10 + 30)

    results = await _run_imsg(*args, timeout=timeout)
    return [_parse_message(r) for r in results]


async def watch_messages(
    thread_id: int,
    since_rowid: int | None = None,
    debounce_ms: int = 250,
    include_attachments: bool = False,
) -> AsyncIterator[Message]:
    """Watch for new messages in a thread (streaming).

    Args:
        thread_id: The thread ID to watch.
        since_rowid: Only return messages after this rowid.
        debounce_ms: Debounce interval in milliseconds.
        include_attachments: Whether to include attachment info.

    Yields:
        Message objects as they arrive.
    """
    args = [
        _get_imsg_path(),
        "watch",
        "--chat-id",
        str(thread_id),
        "--debounce",
        f"{debounce_ms}ms",
        "--json",
    ]

    if since_rowid is not None:
        args.extend(["--since-rowid", str(since_rowid)])
    if include_attachments:
        args.append("--attachments")

    cmd_str = shlex.join(args)
    logger.debug("Starting watch: %s", cmd_str)

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        while True:
            if proc.stdout is None:
                break

            line = await proc.stdout.readline()
            if not line:
                break

            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue

            try:
                data = json.loads(line_str)
                yield _parse_message(data)
            except json.JSONDecodeError as e:
                logger.warning("Watch NDJSON parse error: %s (line: %s)", e, line_str[:100])

    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


# =============================================================================
# Public API - Send
# =============================================================================


def build_send_command(data: MessageSend, region: str | None = None) -> list[str]:
    """Build the imsg send command (for dryRun support).

    Args:
        data: The MessageSend request.
        region: Default region for phone normalization.

    Returns:
        List of command arguments.
    """
    settings = get_settings()
    args = [_get_imsg_path(), "send", "--to", data.to]

    if data.text:
        args.extend(["--text", data.text])

    for file_path in data.files:
        args.extend(["--file", file_path])

    if data.service and data.service != "auto":
        args.extend(["--service", data.service])

    effective_region = data.region or region or settings.default_region
    args.extend(["--region", effective_region])

    return args


async def send_message_v2(
    data: MessageSend,
    dry_run: bool = False,
) -> MessageSendResponse:
    """Send a message.

    Args:
        data: The MessageSend request.
        dry_run: If True, return the command without executing.

    Returns:
        MessageSendResponse with status.
    """
    args = build_send_command(data)
    cmd_str = shlex.join(args)

    if dry_run:
        return MessageSendResponse(ok=True, to=data.to, command=cmd_str)

    try:
        # Execute the send (skip the imsg binary from args)
        await _run_imsg_raw(*args[1:])
        return MessageSendResponse(ok=True, to=data.to)
    except ImsgError as e:
        # Include the actual error output from imsg (in e.stderr) for better debugging
        error_msg = e.message
        if e.stderr:
            error_msg = f"{e.message}: {e.stderr}"
        return MessageSendResponse(ok=False, to=data.to, error=error_msg)


async def reply_to_thread(
    text: str,
    thread_id: int | None = None,
    recipient: str | None = None,
) -> MessageSendResponse:
    """Reply to a thread or recipient.

    Args:
        text: The message text.
        thread_id: The thread ID to reply to (optional).
        recipient: The recipient identifier - phone, email, or handle (optional).

    Returns:
        MessageSendResponse with status.
    """
    # If recipient is provided, just send directly to that address
    if recipient:
        data = MessageSend(to=recipient, text=text)
        return await send_message_v2(data)

    if not thread_id:
        return MessageSendResponse(
            ok=False,
            error="Either thread_id or recipient must be provided.",
        )

    # Get recent messages to find the recipient
    messages = await get_messages(thread_id, limit=10)

    # Find the last inbound message sender
    recipient = None
    for msg in reversed(messages):
        if not msg.is_from_me and msg.sender:
            recipient = msg.sender
            break

    if not recipient:
        # Fall back to thread participants
        thread = await get_thread(thread_id)
        if thread and thread.participants:
            recipient = thread.participants[0].handle

    if not recipient:
        return MessageSendResponse(
            ok=False,
            error=f"Could not determine recipient for thread {thread_id}. "
            "Use /messages/send with explicit 'to'.",
        )

    data = MessageSend(to=recipient, text=text)
    return await send_message_v2(data)


async def get_messages_by_recipient(
    recipient: str,
    limit: int = 50,
    start: datetime | None = None,
    end: datetime | None = None,
    include_attachments: bool = False,
) -> list[Message]:
    """Get message history with a specific recipient.

    Finds the thread with this participant and returns messages.

    Args:
        recipient: Recipient identifier (phone, email, or handle).
        limit: Maximum messages to return.
        start: Start of time range.
        end: End of time range.
        include_attachments: Whether to include attachment info.

    Returns:
        List of Message objects, or empty list if no thread found.
    """
    thread_id = await find_thread_by_recipient(recipient)
    if not thread_id:
        return []

    return await get_messages(
        thread_id=thread_id,
        limit=limit,
        start=start,
        end=end,
        include_attachments=include_attachments,
    )


# =============================================================================
# Public API - Search (fast text-based)
# =============================================================================

# Regex to parse imsg text output format:
# 2026-01-31T12:25:21.879Z [recv] +13106999664: message text
#   (2 attachments)
_TEXT_LINE_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+\[(sent|recv)\]\s+([^:]+):\s*(.*)$"
)


def _parse_text_message(
    line: str, chat_id: int, line_idx: int
) -> Message | None:
    """Parse a single text-format message line into a Message object."""
    match = _TEXT_LINE_PATTERN.match(line)
    if not match:
        return None

    date_str, direction, sender, text = match.groups()
    is_from_me = direction == "sent"

    # Parse the date
    try:
        created_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        created_at = datetime.now()

    # Clean text and apply PII filtering
    cleaned_text = filter_pii(_clean_text(text))

    return Message(
        id=line_idx,  # Use line index as pseudo-ID
        chat_id=chat_id,
        guid=f"search-{chat_id}-{line_idx}",
        sender=sender.strip(),
        text=cleaned_text,
        created_at=created_at,
        is_from_me=is_from_me,
        attachments=[],
    )


async def search_messages_fast(
    query: str,
    thread_id: int,
    scan_limit: int = 10000,
    result_limit: int = 100,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Message]:
    """Fast text-based search using imsg text output (150x faster than JSON).

    Args:
        query: Text to search for (case-insensitive substring).
        thread_id: Thread ID to search within.
        scan_limit: Maximum messages to scan.
        result_limit: Maximum matching results to return.
        start: Start of time range.
        end: End of time range.

    Returns:
        List of matching Message objects (up to result_limit).
    """
    # Build command without --json for speed
    args = ["history", "--chat-id", str(thread_id), "--limit", str(scan_limit)]

    if start:
        args.extend(["--start", _format_datetime_for_imsg(start)])
    if end:
        args.extend(["--end", _format_datetime_for_imsg(end)])

    # Run without JSON (much faster)
    output = await _run_imsg_raw(*args, timeout=30.0)

    # Parse and filter
    query_lower = query.lower()
    matches = []
    line_idx = 0

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("("):  # Skip attachment lines
            continue

        # Quick pre-filter before parsing
        if query_lower not in line.lower():
            line_idx += 1
            continue

        msg = _parse_text_message(line, thread_id, line_idx)
        if msg and msg.text and query_lower in msg.text.lower():
            matches.append(msg)
            if len(matches) >= result_limit:
                break

        line_idx += 1

    return matches


async def search_messages(
    query: str,
    thread_id: int | None = None,
    recipient: str | None = None,
    scan_limit: int = 10000,
    result_limit: int = 100,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Message]:
    """Search messages by text content (fast text-based search).

    Args:
        query: Text to search for (case-insensitive substring).
        thread_id: Optional thread ID to search within.
        recipient: Optional recipient identifier (phone/email/handle) to find thread.
        scan_limit: Maximum messages to scan.
        result_limit: Maximum matching results to return.
        start: Start of time range.
        end: End of time range.

    Returns:
        List of matching Message objects (up to result_limit).
    """
    # Determine target thread
    target_thread_id = thread_id

    if target_thread_id is None and recipient:
        # Find thread by participant
        target_thread_id = await find_thread_by_recipient(recipient)

    if target_thread_id is None:
        return []

    return await search_messages_fast(
        query=query,
        thread_id=target_thread_id,
        scan_limit=scan_limit,
        result_limit=result_limit,
        start=start,
        end=end,
    )


async def find_thread_by_recipient(recipient: str, max_threads: int = 50) -> int | None:
    """Find the thread ID for a recipient.

    Args:
        recipient: Recipient identifier (phone, email, or handle).
        max_threads: Maximum threads to probe.

    Returns:
        Thread ID if found, None otherwise.
    """
    threads = await list_threads(limit=max_threads)

    for thread in threads:
        # Try to get a message with this participant
        try:
            messages = await get_messages(thread.id, limit=1, participants=[recipient])
            if messages:
                return thread.id
        except ImsgError:
            continue

    return None


# =============================================================================
# Public API - Link Extraction
# =============================================================================

# Regex pattern for matching URLs
_URL_PATTERN = re.compile(
    r"https?://"  # http:// or https://
    r"(?:[\w-]+\.)+[\w-]+"  # domain
    r"(?:/[^\s<>\"'\)\]]*)?",  # optional path
    re.IGNORECASE,
)


# Characters to strip from message text (Apple's object replacement chars, null bytes, etc.)
_STRIP_CHARS = "\x00\ufffc\ufffd\u200b\u200c\u200d\ufeff"


def _clean_text(text: str) -> str:
    """Remove Apple's invisible/replacement characters from text."""
    if not text:
        return ""
    # Remove object replacement characters and other invisibles
    return text.translate(str.maketrans("", "", _STRIP_CHARS)).strip()


def _extract_urls(text: str) -> list[str]:
    """Extract all HTTP/HTTPS URLs from text."""
    if not text:
        return []
    # Clean text before extracting URLs
    cleaned = _clean_text(text)
    return _URL_PATTERN.findall(cleaned)


def _get_link_context(text: str, url: str, context_chars: int = 50) -> str:
    """Get text context around a URL."""
    if not text:
        return ""
    # Clean text for display
    cleaned = _clean_text(text)
    idx = cleaned.find(url)
    if idx == -1:
        return cleaned[:100] if len(cleaned) > 100 else cleaned

    start = max(0, idx - context_chars)
    end = min(len(cleaned), idx + len(url) + context_chars)

    context = cleaned[start:end]
    if start > 0:
        context = "..." + context
    if end < len(cleaned):
        context = context + "..."
    return context


async def extract_links(
    recipient: str | None = None,
    thread_id: int | None = None,
    limit: int = 20,
    message_limit: int = 200,
    from_me: bool | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[ExtractedLink]:
    """Extract HTTP/HTTPS links from messages.

    Args:
        recipient: Recipient identifier (phone/email/handle) to find thread.
        thread_id: Thread ID to search (alternative to recipient).
        limit: Maximum number of links to return.
        message_limit: Maximum messages to scan for links.
        from_me: If True, only links from messages I sent.
                 If False, only links from messages others sent.
                 If None, all messages.
        start: Start of date range.
        end: End of date range.

    Returns:
        List of ExtractedLink objects, most recent first.
    """
    # Determine target thread
    target_thread_id = thread_id
    if target_thread_id is None and recipient:
        target_thread_id = await find_thread_by_recipient(recipient)

    if target_thread_id is None:
        return []

    # Fetch messages from time window
    messages = await get_messages(
        thread_id=target_thread_id, limit=message_limit, start=start, end=end
    )

    # Extract links from messages
    links: list[ExtractedLink] = []

    for msg in reversed(messages):  # Most recent first
        if len(links) >= limit:
            break

        # Filter by sender if specified
        if from_me is True and not msg.is_from_me:
            continue
        if from_me is False and msg.is_from_me:
            continue

        if not msg.text:
            continue

        urls = _extract_urls(msg.text)
        for url in urls:
            if len(links) >= limit:
                break

            links.append(
                ExtractedLink(
                    url=url,
                    message_id=msg.id,
                    sender=msg.sender if not msg.is_from_me else "me",
                    sent_at=msg.created_at,
                    context=_get_link_context(msg.text, url),
                )
            )

    return links
