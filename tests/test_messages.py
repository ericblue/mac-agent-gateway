"""Tests for messages API endpoints."""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from mag.models.messages import (
    Contact,
    Message,
    MessageSendResponse,
    Participant,
    Thread,
)
from mag.services.contacts import ContactCache
from mag.services.imsg import ImsgError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_send_response() -> MessageSendResponse:
    """Create a mock send response for testing."""
    return MessageSendResponse(ok=True, to="+15551234567")


@pytest.fixture
def mock_thread() -> Thread:
    """Create a mock thread for testing."""
    return Thread(
        id=123,
        name="Test Chat",
        identifier="chat123",
        service="imessage",
        last_message_at=datetime.now(),
        participants=[Participant(handle="+15551234567", display_name="Test User")],
    )


@pytest.fixture
def mock_message() -> Message:
    """Create a mock message for testing."""
    return Message(
        id=1,
        chat_id=123,
        guid="msg-guid-123",
        sender="+15551234567",
        is_from_me=False,
        text="Hello, world!",
        created_at=datetime.now(),
    )


@pytest.fixture
def contact_cache(tmp_path: Path) -> ContactCache:
    """Create a temporary contact cache for testing."""
    return ContactCache(file_path=tmp_path / "contacts.json")


# =============================================================================
# Thread Tests
# =============================================================================


class TestListThreads:
    """Tests for GET /v1/messages/threads."""

    def test_list_threads_success(
        self, client: TestClient, auth_headers: dict, mock_thread: Thread
    ) -> None:
        """Should return list of threads."""
        with patch("mag.routers.messages.imsg.list_threads", new_callable=AsyncMock) as mock:
            mock.return_value = [mock_thread]
            response = client.get("/v1/messages/threads", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == 123
        assert data[0]["name"] == "Test Chat"

    def test_list_threads_with_limit(self, client: TestClient, auth_headers: dict) -> None:
        """Should pass limit parameter to service."""
        with patch("mag.routers.messages.imsg.list_threads", new_callable=AsyncMock) as mock:
            mock.return_value = []
            response = client.get("/v1/messages/threads?limit=5", headers=auth_headers)

        assert response.status_code == 200
        mock.assert_called_once_with(limit=5)

    def test_list_threads_cli_error(self, client: TestClient, auth_headers: dict) -> None:
        """Should return 502 on CLI error."""
        with patch("mag.routers.messages.imsg.list_threads", new_callable=AsyncMock) as mock:
            mock.side_effect = ImsgError("CLI failed", code=1, stderr="error output")
            response = client.get("/v1/messages/threads", headers=auth_headers)

        assert response.status_code == 502


class TestGetThread:
    """Tests for GET /v1/messages/threads/{thread_id}."""

    def test_get_thread_success(
        self, client: TestClient, auth_headers: dict, mock_thread: Thread
    ) -> None:
        """Should return thread by ID."""
        with patch("mag.routers.messages.imsg.get_thread", new_callable=AsyncMock) as mock:
            mock.return_value = mock_thread
            response = client.get("/v1/messages/threads/123", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["id"] == 123

    def test_get_thread_not_found(self, client: TestClient, auth_headers: dict) -> None:
        """Should return 404 if thread not found."""
        with patch("mag.routers.messages.imsg.get_thread", new_callable=AsyncMock) as mock:
            mock.return_value = None
            response = client.get("/v1/messages/threads/999", headers=auth_headers)

        assert response.status_code == 404


# =============================================================================
# Message Tests
# =============================================================================


class TestGetMessages:
    """Tests for GET /v1/messages/threads/{thread_id}/messages."""

    def test_get_messages_success(
        self, client: TestClient, auth_headers: dict, mock_message: Message
    ) -> None:
        """Should return messages for thread."""
        with patch("mag.routers.messages.imsg.get_messages", new_callable=AsyncMock) as mock:
            mock.return_value = [mock_message]
            response = client.get("/v1/messages/threads/123/messages", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["text"] == "Hello, world!"

    def test_get_messages_with_params(self, client: TestClient, auth_headers: dict) -> None:
        """Should pass query parameters to service."""
        with patch("mag.routers.messages.imsg.get_messages", new_callable=AsyncMock) as mock:
            mock.return_value = []
            response = client.get(
                "/v1/messages/threads/123/messages?limit=10&attachments=true",
                headers=auth_headers,
            )

        assert response.status_code == 200
        mock.assert_called_once()
        call_kwargs = mock.call_args.kwargs
        assert call_kwargs["limit"] == 10
        assert call_kwargs["include_attachments"] is True


class TestSendMessage:
    """Tests for POST /v1/messages/send."""

    def test_send_message_success(
        self, client: TestClient, auth_headers: dict, mock_send_response: MessageSendResponse
    ) -> None:
        """Should send message and return response."""
        with patch("mag.routers.messages.imsg.send_message_v2", new_callable=AsyncMock) as mock:
            mock.return_value = mock_send_response
            response = client.post(
                "/v1/messages/send",
                headers=auth_headers,
                json={"to": "+15551234567", "text": "Hello!"},
            )

        assert response.status_code == 201
        assert response.json()["ok"] is True
        assert response.json()["to"] == "+15551234567"

    def test_send_message_dry_run(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should return command without executing on dry run."""
        dry_run_response = MessageSendResponse(
            ok=True, to="+15551234567", command="imsg send --to +15551234567 --text Hello"
        )
        with patch("mag.routers.messages.imsg.send_message_v2", new_callable=AsyncMock) as mock:
            mock.return_value = dry_run_response
            response = client.post(
                "/v1/messages/send?dry_run=true",
                headers=auth_headers,
                json={"to": "+15551234567", "text": "Hello!"},
            )

        assert response.status_code == 201
        assert response.json()["command"] is not None
        mock.assert_called_once()
        assert mock.call_args.kwargs["dry_run"] is True

    def test_send_message_cli_error(self, client: TestClient, auth_headers: dict) -> None:
        """Should return 502 on CLI error."""
        with patch("mag.routers.messages.imsg.send_message_v2", new_callable=AsyncMock) as mock:
            mock.side_effect = ImsgError("CLI failed", code=1, stderr="error output")
            response = client.post(
                "/v1/messages/send",
                headers=auth_headers,
                json={"to": "+15551234567", "text": "Hello!"},
            )

        assert response.status_code == 502

    def test_send_message_missing_to(self, client: TestClient, auth_headers: dict) -> None:
        """Should reject missing recipient."""
        response = client.post(
            "/v1/messages/send",
            headers=auth_headers,
            json={"text": "Hello!"},
        )
        assert response.status_code == 422


class TestReplyToThread:
    """Tests for POST /v1/messages/reply."""

    def test_reply_by_thread_id_success(
        self, client: TestClient, auth_headers: dict, mock_send_response: MessageSendResponse
    ) -> None:
        """Should reply to thread by ID."""
        with patch("mag.routers.messages.imsg.reply_to_thread", new_callable=AsyncMock) as mock:
            mock.return_value = mock_send_response
            response = client.post(
                "/v1/messages/reply",
                headers=auth_headers,
                json={"thread_id": 123, "text": "Reply!"},
            )

        assert response.status_code == 201
        assert response.json()["ok"] is True
        mock.assert_called_once_with(text="Reply!", thread_id=123, recipient=None)

    def test_reply_by_recipient_success(
        self, client: TestClient, auth_headers: dict, mock_send_response: MessageSendResponse
    ) -> None:
        """Should reply to recipient (phone/email/handle)."""
        with patch("mag.routers.messages.imsg.reply_to_thread", new_callable=AsyncMock) as mock:
            mock.return_value = mock_send_response
            response = client.post(
                "/v1/messages/reply",
                headers=auth_headers,
                json={"recipient": "+15551234567", "text": "Reply!"},
            )

        assert response.status_code == 201
        assert response.json()["ok"] is True
        mock.assert_called_once_with(text="Reply!", thread_id=None, recipient="+15551234567")

    def test_reply_requires_thread_or_recipient(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should require either thread_id or recipient."""
        response = client.post(
            "/v1/messages/reply",
            headers=auth_headers,
            json={"text": "Reply!"},
        )

        assert response.status_code == 400
        assert "thread_id or recipient" in response.json()["detail"]


class TestGetMessagesByRecipient:
    """Tests for GET /v1/messages/history."""

    def test_get_messages_by_recipient_success(
        self, client: TestClient, auth_headers: dict, mock_message: Message
    ) -> None:
        """Should return messages for recipient."""
        with patch(
            "mag.routers.messages.imsg.get_messages_by_recipient", new_callable=AsyncMock
        ) as mock:
            mock.return_value = [mock_message]
            response = client.get(
                "/v1/messages/history?recipient=+15551234567", headers=auth_headers
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["text"] == "Hello, world!"

    def test_get_messages_by_recipient_not_found(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should return empty list if no thread found."""
        with patch(
            "mag.routers.messages.imsg.get_messages_by_recipient", new_callable=AsyncMock
        ) as mock:
            mock.return_value = []
            response = client.get(
                "/v1/messages/history?recipient=+19999999999", headers=auth_headers
            )

        assert response.status_code == 200
        assert response.json() == []


class TestGetThreadByRecipient:
    """Tests for GET /v1/messages/threads/lookup."""

    def test_get_thread_by_recipient_success(
        self, client: TestClient, auth_headers: dict, mock_thread: Thread
    ) -> None:
        """Should return thread for recipient."""
        with patch(
            "mag.routers.messages.imsg.find_thread_by_recipient", new_callable=AsyncMock
        ) as mock_find:
            with patch(
                "mag.routers.messages.imsg.get_thread", new_callable=AsyncMock
            ) as mock_get:
                mock_find.return_value = 123
                mock_get.return_value = mock_thread
                response = client.get(
                    "/v1/messages/threads/lookup?recipient=+15551234567",
                    headers=auth_headers,
                )

        assert response.status_code == 200
        assert response.json()["id"] == 123

    def test_get_thread_by_recipient_not_found(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should return 404 if no thread found."""
        with patch(
            "mag.routers.messages.imsg.find_thread_by_recipient", new_callable=AsyncMock
        ) as mock:
            mock.return_value = None
            response = client.get(
                "/v1/messages/threads/lookup?recipient=+19999999999",
                headers=auth_headers,
            )

        assert response.status_code == 404


class TestSearchMessages:
    """Tests for GET /v1/messages/search."""

    def test_search_success(
        self, client: TestClient, auth_headers: dict, mock_message: Message
    ) -> None:
        """Should return matching messages."""
        with patch("mag.routers.messages.imsg.search_messages", new_callable=AsyncMock) as mock:
            mock.return_value = [mock_message]
            response = client.get(
                "/v1/messages/search?q=hello&thread_id=123",
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_search_requires_scope(self, client: TestClient, auth_headers: dict) -> None:
        """Should require thread_id or recipient."""
        response = client.get(
            "/v1/messages/search?q=hello",
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestExtractLinks:
    """Tests for GET /v1/messages/links."""

    def test_extract_links_success(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should return extracted links."""
        from mag.models.messages import ExtractedLink

        mock_link = ExtractedLink(
            url="https://example.com/page",
            message_id=1,
            sender="+15551234567",
            sent_at=datetime.now(),
            context="Check out https://example.com/page for details",
        )
        with patch(
            "mag.routers.messages.imsg.extract_links", new_callable=AsyncMock
        ) as mock:
            mock.return_value = [mock_link]
            response = client.get(
                "/v1/messages/links?recipient=+15551234567&limit=10",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["url"] == "https://example.com/page"

    def test_extract_links_with_from_me_filter(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should pass from_me filter to service."""
        with patch(
            "mag.routers.messages.imsg.extract_links", new_callable=AsyncMock
        ) as mock:
            mock.return_value = []
            response = client.get(
                "/v1/messages/links?recipient=+15551234567&from_me=false",
                headers=auth_headers,
            )

        assert response.status_code == 200
        mock.assert_called_once()
        assert mock.call_args.kwargs["from_me"] is False

    def test_extract_links_requires_scope(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """Should require thread_id or recipient."""
        response = client.get(
            "/v1/messages/links?limit=10",
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestMessageTextCleaning:
    """Tests for stripping binary/invisible chars from message text."""

    def test_strips_null_bytes_from_message_text(self) -> None:
        """Message text with leading null bytes should be cleaned."""
        os.environ["MAG_PII_FILTER"] = "regex"
        from mag.config import get_settings

        get_settings.cache_clear()

        from mag.services.imsg import _parse_message

        raw = {
            "id": 1,
            "chatId": 123,
            "text": "\x00https://example.com/link",
            "date": "2026-02-02T12:00:00Z",
            "isFromMe": True,
        }
        msg = _parse_message(raw)
        assert msg.text == "https://example.com/link"
        assert "\x00" not in (msg.text or "")

        os.environ["MAG_PII_FILTER"] = ""
        get_settings.cache_clear()

    def test_strips_replacement_chars_from_links_context(self) -> None:
        """Extracted link context should not contain replacement chars."""
        from mag.services.imsg import _clean_text, _extract_urls, _get_link_context

        text = "\ufffd\ufffc\x00https://linkedin.com/posts/activity-123"
        cleaned = _clean_text(text)
        assert "\x00" not in cleaned
        assert "\ufffd" not in cleaned
        assert "\ufffc" not in cleaned
        urls = _extract_urls(text)
        assert urls == ["https://linkedin.com/posts/activity-123"]


# =============================================================================
# Contact Tests
# =============================================================================


class TestContactUpsert:
    """Tests for POST /v1/messages/contacts/upsert."""

    def test_upsert_create(self, client: TestClient, auth_headers: dict) -> None:
        """Should create new contact."""
        with patch("mag.routers.messages.get_contact_cache") as mock_get_cache:
            mock_cache = mock_get_cache.return_value
            mock_cache.upsert.return_value = Contact(
                name="John Doe",
                phones=["+15551234567"],
            )
            response = client.post(
                "/v1/messages/contacts/upsert",
                headers=auth_headers,
                json={"name": "John Doe", "phones": ["+15551234567"]},
            )

        assert response.status_code == 201
        assert response.json()["name"] == "John Doe"


class TestContactResolve:
    """Tests for GET /v1/messages/contacts/resolve."""

    def test_resolve_by_phone(self, client: TestClient, auth_headers: dict) -> None:
        """Should resolve contact by phone."""
        from mag.models.messages import ContactResolveResult

        with patch("mag.routers.messages.get_contact_cache") as mock_get_cache:
            mock_cache = mock_get_cache.return_value
            contact = Contact(name="John Doe", phones=["+15551234567"])
            mock_cache.resolve.return_value = ContactResolveResult(
                status="ok", contact=contact
            )
            response = client.get(
                "/v1/messages/contacts/resolve?phone=+15551234567",
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_resolve_requires_param(self, client: TestClient, auth_headers: dict) -> None:
        """Should require at least one parameter."""
        response = client.get(
            "/v1/messages/contacts/resolve",
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestContactSearch:
    """Tests for GET /v1/messages/contacts/search."""

    def test_search_contacts(self, client: TestClient, auth_headers: dict) -> None:
        """Should search contacts."""
        with patch("mag.routers.messages.get_contact_cache") as mock_get_cache:
            mock_cache = mock_get_cache.return_value
            mock_cache.search.return_value = [
                Contact(name="John Doe", phones=["+15551234567"])
            ]
            response = client.get(
                "/v1/messages/contacts/search?q=john",
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert len(response.json()) == 1


# =============================================================================
# Contact Cache Unit Tests
# =============================================================================


class TestContactCache:
    """Unit tests for ContactCache."""

    def test_upsert_new_contact(self, tmp_path: Path) -> None:
        """Should create new contact."""
        cache = ContactCache(file_path=tmp_path / "contacts.json")
        from mag.models.messages import ContactUpsert

        data = ContactUpsert(name="John Doe", phones=["+15551234567"])
        contact = cache.upsert(data)

        assert contact.name == "John Doe"
        assert "+15551234567" in contact.phones

    def test_upsert_updates_existing(self, tmp_path: Path) -> None:
        """Should update existing contact by phone match."""
        cache = ContactCache(file_path=tmp_path / "contacts.json")
        from mag.models.messages import ContactUpsert

        # Create initial contact
        data1 = ContactUpsert(name="John Doe", phones=["+15551234567"])
        contact1 = cache.upsert(data1)

        # Update with same phone
        data2 = ContactUpsert(name="John D.", phones=["+15551234567"], emails=["john@example.com"])
        contact2 = cache.upsert(data2)

        assert contact1.id == contact2.id
        assert contact2.name == "John D."
        assert "john@example.com" in contact2.emails

    def test_resolve_by_phone(self, tmp_path: Path) -> None:
        """Should resolve by phone number."""
        cache = ContactCache(file_path=tmp_path / "contacts.json")
        from mag.models.messages import ContactUpsert

        data = ContactUpsert(name="John Doe", phones=["+15551234567"])
        cache.upsert(data)

        result = cache.resolve(phone="+15551234567")
        assert result.status == "ok"
        assert result.contact is not None
        assert result.contact.name == "John Doe"

    def test_resolve_by_name_exact(self, tmp_path: Path) -> None:
        """Should resolve by exact name match."""
        cache = ContactCache(file_path=tmp_path / "contacts.json")
        from mag.models.messages import ContactUpsert

        data = ContactUpsert(name="John Doe", phones=["+15551234567"])
        cache.upsert(data)

        result = cache.resolve(name="john doe")
        assert result.status == "ok"

    def test_resolve_ambiguous(self, tmp_path: Path) -> None:
        """Should return ambiguous if multiple matches."""
        cache = ContactCache(file_path=tmp_path / "contacts.json")
        from mag.models.messages import ContactUpsert

        cache.upsert(ContactUpsert(name="John Doe", phones=["+15551234567"]))
        cache.upsert(ContactUpsert(name="John Smith", phones=["+15559999999"]))

        result = cache.resolve(name="John")
        assert result.status == "ambiguous"
        assert len(result.candidates) == 2

    def test_resolve_not_found(self, tmp_path: Path) -> None:
        """Should return not_found if no match."""
        cache = ContactCache(file_path=tmp_path / "contacts.json")

        result = cache.resolve(name="Nobody")
        assert result.status == "not_found"

    def test_search(self, tmp_path: Path) -> None:
        """Should search across all fields."""
        cache = ContactCache(file_path=tmp_path / "contacts.json")
        from mag.models.messages import ContactUpsert

        cache.upsert(ContactUpsert(name="John Doe", phones=["+15551234567"]))
        cache.upsert(ContactUpsert(name="Jane Smith", emails=["jane@example.com"]))

        results = cache.search("john")
        assert len(results) == 1
        assert results[0].name == "John Doe"

    def test_persistence(self, tmp_path: Path) -> None:
        """Should persist and reload contacts."""
        file_path = tmp_path / "contacts.json"
        from mag.models.messages import ContactUpsert

        # Create and save
        cache1 = ContactCache(file_path=file_path)
        cache1.upsert(ContactUpsert(name="John Doe", phones=["+15551234567"]))

        # Reload
        cache2 = ContactCache(file_path=file_path)
        assert len(cache2.list_all()) == 1
        assert cache2.list_all()[0].name == "John Doe"
