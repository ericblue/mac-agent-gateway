"""Pydantic models for Apple Messages."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# =============================================================================
# Attachment Model
# =============================================================================


class Attachment(BaseModel):
    """Attachment in a message."""

    filename: str | None = Field(None, description="Attachment filename")
    transfer_name: str | None = Field(None, description="Transfer name")
    uti: str | None = Field(None, description="Uniform Type Identifier")
    mime_type: str | None = Field(None, description="MIME type")
    total_bytes: int | None = Field(None, description="File size in bytes")
    is_sticker: bool = Field(default=False, description="Whether attachment is a sticker")
    original_path: str | None = Field(None, description="Original file path")
    missing: bool = Field(default=False, description="Whether attachment file is missing")


# =============================================================================
# Participant Model
# =============================================================================


class Participant(BaseModel):
    """Participant in a thread."""

    handle: str = Field(..., description="Phone number or email")
    display_name: str | None = Field(None, description="Display name if available")


# =============================================================================
# Thread Model
# =============================================================================


class Thread(BaseModel):
    """A message thread (conversation/chat)."""

    id: int = Field(..., description="Thread ID (imsg chat id)")
    name: str | None = Field(None, description="Display name if available")
    identifier: str | None = Field(None, description="Thread identifier string")
    service: str | None = Field(None, description="Service type: imessage, sms, or auto")
    last_message_at: datetime | None = Field(None, description="When the last message was sent")
    participants: list[Participant] = Field(default_factory=list, description="Thread participants")


# =============================================================================
# Message Model
# =============================================================================


class Message(BaseModel):
    """A single message."""

    id: int | None = Field(None, description="Message ID (rowid)")
    chat_id: int = Field(..., description="Thread/chat ID")
    guid: str = Field(..., description="Message GUID")
    reply_to_guid: str | None = Field(None, description="GUID of message being replied to")
    sender: str | None = Field(None, description="Sender handle (phone/email)")
    is_from_me: bool = Field(..., description="Whether message is from the local user")
    text: str | None = Field(None, description="Message text content")
    created_at: datetime = Field(..., description="When the message was created")
    attachments: list[Attachment] = Field(default_factory=list, description="Message attachments")
    reactions: Any = Field(None, description="Reactions metadata (passthrough)")


# =============================================================================
# Contact Model
# =============================================================================


class Contact(BaseModel):
    """A contact in the cache."""

    id: str = Field(default_factory=lambda: str(uuid4()), description="Contact UUID")
    name: str | None = Field(None, description="Contact display name")
    phones: list[str] = Field(default_factory=list, description="Phone numbers (E.164 preferred)")
    emails: list[str] = Field(default_factory=list, description="Email addresses")
    aliases: list[str] = Field(default_factory=list, description="Nicknames/aliases")
    updated_at: datetime = Field(default_factory=datetime.now, description="Last updated timestamp")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")


class ContactUpsert(BaseModel):
    """Request model for upserting a contact."""

    name: str | None = Field(None, description="Contact display name")
    phones: list[str] = Field(default_factory=list, description="Phone numbers")
    emails: list[str] = Field(default_factory=list, description="Email addresses")
    aliases: list[str] = Field(default_factory=list, description="Nicknames/aliases")


class ContactResolveResult(BaseModel):
    """Result of contact resolution."""

    status: str = Field(..., description="Resolution status: ok, ambiguous, not_found")
    contact: Contact | None = Field(None, description="Resolved contact if unique match")
    candidates: list[Contact] = Field(
        default_factory=list, description="Multiple matches if ambiguous"
    )


# =============================================================================
# Request/Response Models
# =============================================================================


class MessageSend(BaseModel):
    """Request model for sending a message."""

    to: str = Field(..., min_length=1, description="Recipient phone number or email")
    text: str | None = Field(None, description="Message text")
    files: list[str] = Field(default_factory=list, description="Absolute paths to files to attach")
    service: str = Field(default="auto", description="Service: imessage, sms, or auto")
    region: str | None = Field(None, description="Region code for phone number normalization")


class MessageReply(BaseModel):
    """Request model for replying to a thread or recipient."""

    thread_id: int | None = Field(None, description="Thread ID to reply to")
    recipient: str | None = Field(
        None, description="Recipient identifier (phone, email, or handle)"
    )
    text: str = Field(..., min_length=1, description="Reply message text")


class MessageSendResponse(BaseModel):
    """Response model for a sent message."""

    ok: bool = Field(..., description="Whether send succeeded")
    to: str | None = Field(None, description="Recipient")
    command: str | None = Field(None, description="Command that was/would be executed (dryRun)")
    error: str | None = Field(None, description="Error message if failed")


class MessageSearchResult(BaseModel):
    """A message search result with context."""

    message: Message = Field(..., description="The matching message")
    snippet: str | None = Field(None, description="Context snippet around match")


class ExtractedLink(BaseModel):
    """A link extracted from a message."""

    url: str = Field(..., description="The extracted URL")
    message_id: int | None = Field(None, description="ID of the message containing the link")
    sender: str | None = Field(None, description="Sender of the message")
    sent_at: datetime = Field(..., description="When the message was sent")
    context: str | None = Field(None, description="Text surrounding the link")


# =============================================================================
# Legacy compatibility (deprecated - use Thread instead)
# =============================================================================


class Conversation(BaseModel):
    """Response model for a conversation (deprecated - use Thread)."""

    id: str = Field(..., description="Conversation identifier")
    participants: list[str] = Field(default_factory=list, description="Participant IDs")
    display_name: str | None = Field(None, description="Display name for group chats")
    last_message: str | None = Field(None, description="Last message preview")
    last_message_date: datetime | None = Field(None, description="When the last message was sent")
    unread_count: int = Field(default=0, description="Number of unread messages")


class MessageResponse(BaseModel):
    """Response model for a sent message (deprecated - use MessageSendResponse)."""

    status: str = Field(..., description="Send status (sent, failed)")
    to: str = Field(..., description="Recipient")
    timestamp: datetime | None = Field(None, description="When the message was sent")
