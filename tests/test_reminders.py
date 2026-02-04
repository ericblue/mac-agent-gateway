"""Tests for reminders API endpoints."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from mag.models.reminders import Reminder, ReminderList
from mag.services.remindctl import RemindctlError


@pytest.fixture
def mock_reminder() -> Reminder:
    """Create a mock reminder for testing."""
    return Reminder(
        id="ABC123",
        title="Test reminder",
        list="Personal",
        due=None,
        completed=False,
        notes=None,
        priority=0,
    )


@pytest.fixture
def mock_reminder_list() -> ReminderList:
    """Create a mock reminder list for testing."""
    return ReminderList(name="Personal", count=5)


class TestListReminders:
    """Tests for GET /v1/reminders."""

    def test_list_reminders_success(
        self, client: TestClient, auth_headers: dict, mock_reminder: Reminder
    ) -> None:
        """Should return list of reminders."""
        with patch("mag.routers.reminders.remindctl.list_reminders", new_callable=AsyncMock) as mock:
            mock.return_value = [mock_reminder]
            response = client.get("/v1/reminders", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test reminder"

    def test_list_reminders_with_filter(
        self, client: TestClient, auth_headers: dict, mock_reminder: Reminder
    ) -> None:
        """Should pass filter to service."""
        with patch("mag.routers.reminders.remindctl.list_reminders", new_callable=AsyncMock) as mock:
            mock.return_value = [mock_reminder]
            response = client.get("/v1/reminders?filter=today", headers=auth_headers)

        assert response.status_code == 200
        mock.assert_called_once()
        call_args = mock.call_args
        assert call_args.kwargs["filter_type"].value == "today"

    def test_list_reminders_cli_error(self, client: TestClient, auth_headers: dict) -> None:
        """Should return 500 on CLI error."""
        with patch("mag.routers.reminders.remindctl.list_reminders", new_callable=AsyncMock) as mock:
            mock.side_effect = RemindctlError("CLI failed", code=1, stderr="error output")
            response = client.get("/v1/reminders", headers=auth_headers)

        assert response.status_code == 500
        data = response.json()["detail"]
        assert data["error"] == "CLI failed"
        assert data["code"] == 1
        assert data["stderr"] == "error output"

    def test_list_reminders_all_passes_all_to_remindctl(
        self, client: TestClient, auth_headers: dict, mock_reminder: Reminder
    ) -> None:
        """filter=all must pass 'all' to remindctl (default omits undated reminders)."""
        from mag.models.reminders import ReminderFilter

        with patch("mag.services.remindctl._run_remindctl") as mock_run:
            mock_run.return_value = [
                {
                    "id": mock_reminder.id,
                    "title": mock_reminder.title,
                    "list": mock_reminder.list,
                    "isCompleted": False,
                }
            ]
            import asyncio

            from mag.services import remindctl

            asyncio.run(remindctl.list_reminders(filter_type=ReminderFilter.ALL))
            mock_run.assert_called_once()
            args = mock_run.call_args[0]
            assert "all" in args, "remindctl must receive 'all' to include undated reminders"


class TestListReminderLists:
    """Tests for GET /v1/reminders/lists."""

    def test_list_lists_success(
        self, client: TestClient, auth_headers: dict, mock_reminder_list: ReminderList
    ) -> None:
        """Should return list of reminder lists."""
        with patch("mag.routers.reminders.remindctl.list_lists", new_callable=AsyncMock) as mock:
            mock.return_value = [mock_reminder_list]
            response = client.get("/v1/reminders/lists", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Personal"


class TestCreateReminder:
    """Tests for POST /v1/reminders."""

    def test_create_reminder_success(
        self, client: TestClient, auth_headers: dict, mock_reminder: Reminder
    ) -> None:
        """Should create and return a reminder."""
        with patch("mag.routers.reminders.remindctl.create_reminder", new_callable=AsyncMock) as mock:
            mock.return_value = mock_reminder
            response = client.post(
                "/v1/reminders",
                headers=auth_headers,
                json={"title": "Test reminder"},
            )

        assert response.status_code == 201
        assert response.json()["title"] == "Test reminder"

    def test_create_reminder_with_all_fields(
        self, client: TestClient, auth_headers: dict, mock_reminder: Reminder
    ) -> None:
        """Should pass all fields to service."""
        with patch("mag.routers.reminders.remindctl.create_reminder", new_callable=AsyncMock) as mock:
            mock.return_value = mock_reminder
            response = client.post(
                "/v1/reminders",
                headers=auth_headers,
                json={
                    "title": "Test",
                    "list": "Work",
                    "due": "tomorrow",
                    "notes": "Some notes",
                    "priority": 1,
                },
            )

        assert response.status_code == 201
        call_args = mock.call_args[0][0]
        assert call_args.title == "Test"
        assert call_args.list == "Work"
        assert call_args.due == "tomorrow"

    def test_create_reminder_empty_title(self, client: TestClient, auth_headers: dict) -> None:
        """Should reject empty title."""
        response = client.post(
            "/v1/reminders",
            headers=auth_headers,
            json={"title": ""},
        )
        assert response.status_code == 422


class TestUpdateReminder:
    """Tests for PATCH /v1/reminders/{id}."""

    def test_update_reminder_success(
        self, client: TestClient, auth_headers: dict, mock_reminder: Reminder
    ) -> None:
        """Should update and return reminder."""
        with patch("mag.routers.reminders.remindctl.update_reminder", new_callable=AsyncMock) as mock:
            mock.return_value = mock_reminder
            response = client.patch(
                "/v1/reminders/ABC123",
                headers=auth_headers,
                json={"title": "Updated title"},
            )

        assert response.status_code == 200
        mock.assert_called_once()


class TestCompleteReminder:
    """Tests for POST /v1/reminders/{id}/complete."""

    def test_complete_reminder_success(
        self, client: TestClient, auth_headers: dict, mock_reminder: Reminder
    ) -> None:
        """Should mark reminder as complete."""
        mock_reminder.completed = True
        with patch("mag.routers.reminders.remindctl.complete_reminder", new_callable=AsyncMock) as mock:
            mock.return_value = mock_reminder
            response = client.post("/v1/reminders/ABC123/complete", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["completed"] is True


class TestDeleteReminder:
    """Tests for DELETE /v1/reminders/{id}."""

    def test_delete_reminder_success(self, client: TestClient, auth_headers: dict) -> None:
        """Should delete reminder."""
        with patch("mag.routers.reminders.remindctl.delete_reminder", new_callable=AsyncMock) as mock:
            mock.return_value = {"status": "deleted", "id": "ABC123"}
            response = client.delete("/v1/reminders/ABC123", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["status"] == "deleted"
