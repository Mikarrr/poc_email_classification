from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from email_classifier.departments import Department
from email_classifier.schemas import (
    MAX_MESSAGE_LENGTH,
    RouteMessageRequest,
    RouteMessageResponse,
)


def test_accepts_example_from_the_brief() -> None:
    request = RouteMessageRequest(email="jan.nowak@example.com", message="Nie działa mi komputer")

    assert request.email == "jan.nowak@example.com"
    assert request.message == "Nie działa mi komputer"


def test_strips_surrounding_whitespace() -> None:
    request = RouteMessageRequest(email="jan.nowak@example.com", message="  urlop na jutro \n")

    assert request.message == "urlop na jutro"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "jan.nowak@example.com", "message": ""},
        {"email": "jan.nowak@example.com", "message": "   \n\t "},
        {"email": "jan.nowak@example.com", "message": "x" * (MAX_MESSAGE_LENGTH + 1)},
        {"email": "not-an-email", "message": "Nie działa mi komputer"},
        {"email": "jan.nowak@example.com"},
        {"message": "Nie działa mi komputer"},
    ],
    ids=["empty", "whitespace-only", "too-long", "bad-email", "no-message", "no-email"],
)
def test_rejects_invalid_requests(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RouteMessageRequest.model_validate(payload)


def test_accepts_message_at_max_length() -> None:
    request = RouteMessageRequest(email="jan.nowak@example.com", message="x" * MAX_MESSAGE_LENGTH)

    assert len(request.message) == MAX_MESSAGE_LENGTH


def test_response_address_follows_department() -> None:
    request_id = uuid4()

    response = RouteMessageResponse.for_department(
        request_id, Department.HELP_DESK, fallback_used=False
    )

    assert response.request_id == request_id
    assert response.department is Department.HELP_DESK
    assert response.routed_to == "help-desk@example.com"
    assert response.fallback_used is False


def test_response_serialises_department_as_string() -> None:
    response = RouteMessageResponse.for_department(uuid4(), Department.OTHER, fallback_used=True)

    data = response.model_dump(mode="json")

    assert data["department"] == "other"
    assert data["routed_to"] == "other@example.com"
    assert data["fallback_used"] is True
