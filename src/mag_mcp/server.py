#!/usr/bin/env python3
"""mag-mcp: an MCP server over the Mac Agent Gateway REST API.

Why this exists
- Claude Code runs natively on the Mac and can curl MAG directly. Cowork runs Claude Code
  inside a Linux VM whose egress is allowlisted, so it cannot reach 127.0.0.1 on the host.
  A stdio MCP server runs on the host, keeps its TCC grants, and is bridged into the VM by
  Claude Desktop — so the same tools work on both surfaces.

Security model
- The agent never sees the MAG API key. It lives in this process's environment (MAG_API_KEY),
  and MAG itself stays bound to 127.0.0.1.
- MAG is the single policy point. Its capability flags (MAG_REMINDERS_WRITE, MAG_MESSAGES_READ,
  ...) and MAG_MESSAGES_SEND_ALLOWLIST already gate every operation, so this server deliberately
  does NOT reimplement a second policy layer on top.
- Sending IS exposed (messages_send / messages_reply) but is constrained by MAG's
  MAG_MESSAGES_SEND_ALLOWLIST, enforced inside MAG. With the allowlist set, a compromised or
  confused agent can only message the listed recipients. Clearing the allowlist re-opens
  sending to any recipient — do not do that casually now that these tools reach Cowork.
- Every call appends a metadata-only line to ~/.config/mag-mcp/audit.jsonl (no message bodies).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp 2.x renamed it
    from mcp.server.mcpserver import MCPServer as FastMCP

DEFAULT_URL = "http://127.0.0.1:8123"
CONFIG_DIR = Path(os.environ.get("MAG_MCP_HOME", "~/.config/mag-mcp")).expanduser()
AUDIT_PATH = CONFIG_DIR / "audit.jsonl"
ATTACHMENT_DIR = Path(os.environ.get("MAG_MCP_ATTACHMENT_DIR", "~/Downloads/mag-mcp")).expanduser()

# Searching scans messages in MAG, which can take a while on large scan_limits.
DEFAULT_TIMEOUT = float(os.environ.get("MAG_MCP_TIMEOUT", "60"))

mcp = FastMCP("mag-mcp")


# ----------------------------------------------------------------------------- transport


class MagError(RuntimeError):
    """A MAG call failed. Carries MAG's own error payload, which often includes a hint."""


def _base_url() -> str:
    return os.environ.get("MAG_URL", DEFAULT_URL).rstrip("/")


def _verify() -> str | bool:
    """TLS verification setting for httpx.

    Only relevant when MAG_URL is https, e.g. behind a local reverse proxy such as
    https://mag.local. Python does not read the macOS keychain, so a locally-trusted
    mkcert certificate that `curl` accepts will still fail here with
    CERTIFICATE_VERIFY_FAILED. Point MAG_MCP_CA_BUNDLE at the mkcert root to fix it:

        export MAG_MCP_CA_BUNDLE="$(mkcert -CAROOT)/rootCA.pem"

    The loopback default needs none of this, which is why it stays the default.
    """
    bundle = os.environ.get("MAG_MCP_CA_BUNDLE", "")
    return bundle if bundle else True


def _api_key() -> str:
    key = os.environ.get("MAG_API_KEY", "")
    if not key:
        raise MagError(
            "MAG_API_KEY is not set for this server. Add it to the MCP server's env "
            "(see README: Registering the MCP server)."
        )
    return key


def _audit(tool: str, ok: bool, detail: str = "") -> None:
    """Append a metadata-only audit line. Never raises into a tool call."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "ok": ok,
        }
        if detail:
            line["detail"] = detail[:200]
        with open(AUDIT_PATH, "a") as handle:
            handle.write(json.dumps(line) + "\n")
    except OSError:
        pass


def _request(
    method: str,
    path: str,
    *,
    tool: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> Any:
    """Call MAG and return decoded JSON, or raise MagError with MAG's own detail."""
    # Drop unset optionals so MAG applies its documented defaults rather than receiving nulls.
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    body = {k: v for k, v in (json_body or {}).items() if v is not None} if json_body else None

    started = time.monotonic()
    try:
        response = httpx.request(
            method,
            f"{_base_url()}{path}",
            params=clean or None,
            json=body,
            headers={"X-API-Key": _api_key()},
            timeout=timeout or DEFAULT_TIMEOUT,
            verify=_verify(),
        )
    except httpx.ConnectError as exc:
        _audit(tool, False, "connect")
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            raise MagError(
                f"TLS verification failed for {_base_url()}. Python does not use the macOS "
                "keychain, so a locally-trusted cert that curl accepts still fails here. "
                'Set MAG_MCP_CA_BUNDLE="$(mkcert -CAROOT)/rootCA.pem", or point MAG_URL at '
                f"{DEFAULT_URL} instead."
            ) from exc
        raise MagError(
            f"Cannot reach MAG at {_base_url()}. Is the service running? "
            "Check with: launchctl list | grep com.ericblue.mag"
        ) from exc
    except httpx.TimeoutException as exc:
        _audit(tool, False, "timeout")
        raise MagError(
            f"MAG timed out after {timeout or DEFAULT_TIMEOUT}s. For searches, lower scan_limit."
        ) from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        _audit(tool, False, f"{response.status_code}")
        # MAG's 403s are capability flags; its 502s usually mean a TCC permission gap.
        raise MagError(f"MAG returned {response.status_code}: {json.dumps(detail, default=str)}")

    _audit(tool, True, f"{int((time.monotonic() - started) * 1000)}ms")
    if response.status_code == 204 or not response.content:
        return {"ok": True}
    return response.json()


# ----------------------------------------------------------------------------- discovery


@mcp.tool()
def mag_status() -> dict:
    """MAG's health and which capabilities are currently enabled.

    Call this first when a reminders or messages tool fails: capabilities reflect MAG's own
    flags, so a disabled capability is a config choice, not a bug. `send_allowlist_active`
    means outgoing messages are restricted to specific recipients.
    """
    health = httpx.get(f"{_base_url()}/health", timeout=10, verify=_verify()).json()
    caps = _request("GET", "/v1/capabilities", tool="mag_status")
    return {"health": health, "capabilities": caps, "url": _base_url()}


# ----------------------------------------------------------------------------- reminders


@mcp.tool()
def reminders_list(
    filter: str | None = None,
    date: str | None = None,
    list: str | None = None,
) -> Any:
    """Apple Reminders, optionally filtered.

    filter: today | tomorrow | week | overdue | upcoming | completed | all. Note that the
    date-based filters omit undated reminders; pass 'all' to include them.
    date: YYYY-MM-DD for a specific day. list: restrict to one list by name.
    """
    return _request(
        "GET",
        "/v1/reminders",
        tool="reminders_list",
        params={"filter": filter, "date": date, "list": list},
    )


@mcp.tool()
def reminders_lists() -> Any:
    """Every Reminders list with its open-item count."""
    return _request("GET", "/v1/reminders/lists", tool="reminders_lists")


@mcp.tool()
def reminders_create(
    title: str,
    list: str | None = None,
    due: str | None = None,
    notes: str | None = None,
    priority: int | None = None,
) -> Any:
    """Create a reminder.

    due accepts an ISO 8601 datetime (2026-09-08T09:00:00) or a date (2026-09-08).
    priority is 0 (none) to 9 (low..high per Apple's scale). Omit `list` for the default list.
    """
    return _request(
        "POST",
        "/v1/reminders",
        tool="reminders_create",
        json_body={
            "title": title,
            "list": list,
            "due": due,
            "notes": notes,
            "priority": priority,
        },
    )


@mcp.tool()
def reminders_update(
    reminder_id: str,
    title: str | None = None,
    list: str | None = None,
    due: str | None = None,
    clear_due: bool | None = None,
    notes: str | None = None,
    priority: int | None = None,
    completed: bool | None = None,
) -> Any:
    """Update a reminder in place. Only the fields you pass are changed.

    Use clear_due=True to remove a due date entirely; passing due=None leaves it untouched.
    """
    return _request(
        "PATCH",
        f"/v1/reminders/{reminder_id}",
        tool="reminders_update",
        json_body={
            "title": title,
            "list": list,
            "due": due,
            "clear_due": clear_due,
            "notes": notes,
            "priority": priority,
            "completed": completed,
        },
    )


@mcp.tool()
def reminders_complete(reminder_ids: list[str]) -> Any:
    """Mark one or more reminders complete. Accepts a single id or many."""
    if len(reminder_ids) == 1:
        return _request(
            "POST",
            f"/v1/reminders/{reminder_ids[0]}/complete",
            tool="reminders_complete",
        )
    return _request(
        "POST",
        "/v1/reminders/bulk/complete",
        tool="reminders_complete",
        json_body={"ids": reminder_ids},
    )


@mcp.tool()
def reminders_delete(reminder_ids: list[str]) -> Any:
    """Delete one or more reminders permanently. Prefer reminders_complete unless the user
    explicitly wants the reminder gone."""
    if len(reminder_ids) == 1:
        return _request(
            "DELETE",
            f"/v1/reminders/{reminder_ids[0]}",
            tool="reminders_delete",
        )
    return _request(
        "POST",
        "/v1/reminders/bulk/delete",
        tool="reminders_delete",
        json_body={"ids": reminder_ids},
    )


@mcp.tool()
def reminders_manage_list(action: str, name: str, new_name: str | None = None) -> Any:
    """Create, rename or delete a Reminders list. action: create | rename | delete.

    Deleting a list removes the reminders in it. `new_name` is required for rename.
    """
    if action == "create":
        return _request(
            "POST", "/v1/reminders/lists", tool="reminders_manage_list", json_body={"name": name}
        )
    if action == "rename":
        if not new_name:
            raise MagError("rename requires new_name")
        return _request(
            "PATCH",
            f"/v1/reminders/lists/{name}",
            tool="reminders_manage_list",
            json_body={"new_name": new_name},
        )
    if action == "delete":
        return _request("DELETE", f"/v1/reminders/lists/{name}", tool="reminders_manage_list")
    raise MagError(f"unknown action {action!r}; expected create, rename or delete")


# ----------------------------------------------------------------------------- messages (read)


@mcp.tool()
def messages_threads(limit: int | None = None) -> Any:
    """Recent iMessage/SMS conversations, most recently active first."""
    return _request("GET", "/v1/messages/threads", tool="messages_threads", params={"limit": limit})


@mcp.tool()
def messages_thread_lookup(recipient: str) -> Any:
    """Find a thread by recipient (phone number, email, or handle).

    Phone numbers should be E.164 where possible (+15551234567).
    """
    return _request(
        "GET",
        "/v1/messages/threads/lookup",
        tool="messages_thread_lookup",
        params={"recipient": recipient},
    )


@mcp.tool()
def messages_thread(
    thread_id: int,
    limit: int | None = None,
    start: str | None = None,
    end: str | None = None,
    participants: bool | None = None,
    attachments: bool | None = None,
) -> Any:
    """Messages in one thread. start/end are ISO 8601 datetimes.

    Set attachments=True to include attachment metadata (paths you can pass to
    messages_attachment).
    """
    return _request(
        "GET",
        f"/v1/messages/threads/{thread_id}/messages",
        tool="messages_thread",
        params={
            "limit": limit,
            "start": start,
            "end": end,
            "participants": participants,
            "attachments": attachments,
        },
    )


@mcp.tool()
def messages_history(
    recipient: str,
    limit: int | None = None,
    start: str | None = None,
    end: str | None = None,
    attachments: bool | None = None,
    days_back: int | None = None,
) -> Any:
    """Message history with one recipient, without needing to resolve a thread id first."""
    return _request(
        "GET",
        "/v1/messages/history",
        tool="messages_history",
        params={
            "recipient": recipient,
            "limit": limit,
            "start": start,
            "end": end,
            "attachments": attachments,
            "days_back": days_back,
        },
    )


@mcp.tool()
def messages_search(
    q: str,
    thread_id: int | None = None,
    recipient: str | None = None,
    limit: int | None = None,
    scan_limit: int | None = None,
    start: str | None = None,
    end: str | None = None,
    days_back: int | None = None,
) -> Any:
    """Search message text. Requires thread_id OR recipient to scope the search — MAG rejects
    an unscoped search with a 400.

    The search is in-memory over the messages MAG fetches, so scan_limit bounds how many are
    examined (higher = slower but more thorough).
    """
    if thread_id is None and recipient is None:
        raise MagError("messages_search needs thread_id or recipient to scope the search")
    return _request(
        "GET",
        "/v1/messages/search",
        tool="messages_search",
        params={
            "q": q,
            "thread_id": thread_id,
            "recipient": recipient,
            "limit": limit,
            "scan_limit": scan_limit,
            "start": start,
            "end": end,
            "days_back": days_back,
        },
    )


@mcp.tool()
def messages_links(
    recipient: str | None = None,
    thread_id: int | None = None,
    limit: int | None = None,
    message_limit: int | None = None,
    from_me: bool | None = None,
    start: str | None = None,
    end: str | None = None,
    days_back: int | None = None,
) -> Any:
    """Extract URLs shared in a conversation, newest first.

    from_me=False returns only links the other party sent. Good for "find the listing/restaurant
    link they sent me" without reading the whole thread.
    """
    return _request(
        "GET",
        "/v1/messages/links",
        tool="messages_links",
        params={
            "recipient": recipient,
            "thread_id": thread_id,
            "limit": limit,
            "message_limit": message_limit,
            "from_me": from_me,
            "start": start,
            "end": end,
            "days_back": days_back,
        },
    )


@mcp.tool()
def messages_attachment(path: str, download: bool = False) -> Any:
    """Inspect an attachment, or copy it somewhere readable.

    Paths come from messages with attachments=True. With download=False you get metadata only.
    With download=True the file is copied to ~/Downloads/mag-mcp/ and the local path returned —
    the bytes are never streamed through the conversation.
    """
    info = _request(
        "GET", "/v1/messages/attachments/info", tool="messages_attachment", params={"path": path}
    )
    if not download:
        return info

    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    dest = ATTACHMENT_DIR / Path(path).name
    with httpx.stream(
        "GET",
        f"{_base_url()}/v1/messages/attachments/download",
        params={"path": path},
        headers={"X-API-Key": _api_key()},
        timeout=DEFAULT_TIMEOUT,
        verify=_verify(),
    ) as response:
        if response.status_code >= 400:
            response.read()
            raise MagError(f"MAG returned {response.status_code} downloading {path}")
        with open(dest, "wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    return {**info, "saved_to": str(dest)}


@mcp.tool()
def messages_contacts(
    action: str = "list",
    q: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    name: str | None = None,
    limit: int | None = None,
) -> Any:
    """Read MAG's contacts cache, which maps phone numbers and emails to names.

    action: list | search (needs q) | resolve (needs phone, email or name). Use resolve to turn
    a bare number from a thread into a name before reporting it back to the user.
    """
    if action == "list":
        return _request("GET", "/v1/messages/contacts", tool="messages_contacts")
    if action == "search":
        if not q:
            raise MagError("search requires q")
        return _request(
            "GET",
            "/v1/messages/contacts/search",
            tool="messages_contacts",
            params={"q": q, "limit": limit},
        )
    if action == "resolve":
        if not (phone or email or name):
            raise MagError("resolve requires phone, email or name")
        return _request(
            "GET",
            "/v1/messages/contacts/resolve",
            tool="messages_contacts",
            params={"phone": phone, "email": email, "name": name},
        )
    raise MagError(f"unknown action {action!r}; expected list, search or resolve")


# ----------------------------------------------------------------------------- messages (send)
#
# Sending is outward-facing and cannot be recalled, and these tools are reachable from Cowork.
# The guard is MAG's own MAG_MESSAGES_SEND_ALLOWLIST, enforced server-side in MAG rather than
# here: a check in this file would only be as good as the process holding the API key, and MAG
# already gates every other capability the same way.


@mcp.tool()
def messages_send(
    to: str,
    text: str | None = None,
    files: list[str] | None = None,
    service: str | None = None,
    region: str | None = None,
    dry_run: bool = False,
) -> Any:
    """Send an iMessage/SMS. THIS CANNOT BE UNDONE once sent.

    Recipients are restricted by MAG's send allowlist; anything off-list is refused with a 403
    naming the recipient. Do not attempt to work around a refusal.

    to: phone number (E.164 preferred) or email. service: imessage | sms | auto.
    files: absolute paths to attach. Set dry_run=True to see the exact command MAG would run
    without sending — use it whenever the recipient or wording is at all uncertain.
    """
    return _request(
        "POST",
        "/v1/messages/send",
        tool="messages_send",
        params={"dry_run": True} if dry_run else None,
        json_body={
            "to": to,
            "text": text,
            "files": files,
            "service": service,
            "region": region,
        },
    )


@mcp.tool()
def messages_reply(
    text: str,
    thread_id: int | None = None,
    recipient: str | None = None,
) -> Any:
    """Reply in an existing thread. THIS CANNOT BE UNDONE once sent.

    Pass thread_id or recipient (not both is required, but one must be given). Subject to the
    same send allowlist as messages_send. Prefer this over messages_send when continuing a
    conversation, so the reply lands in the right thread.
    """
    if thread_id is None and recipient is None:
        raise MagError("messages_reply needs thread_id or recipient")
    return _request(
        "POST",
        "/v1/messages/reply",
        tool="messages_reply",
        json_body={"thread_id": thread_id, "recipient": recipient, "text": text},
    )


def main() -> None:
    try:
        mcp.run()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
