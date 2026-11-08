"""Request and response models of the HTTP API."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from email_classifier.departments import Department

MAX_MESSAGE_LENGTH = 5000

MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_LENGTH),
]


class RouteMessageRequest(BaseModel):
    """A users message to be routed to the right department."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"email": "jan.nowak@example.com", "message": "Nie działa mi komputer"},
                {"email": "anna.nowak@example.com", "message": "Chciałbym zgłosić urlop na jutro"},
            ]
        }
    )

    email: EmailStr = Field(description="Sender's address; used as Reply-To of the routed email.")
    message: MessageText = Field(description="Free-text message from the user.")


class RouteMessageResponse(BaseModel):
    """Where the message was routed."""

    request_id: UUID
    department: Department
    routed_to: EmailStr
    fallback_used: bool = Field(
        description="True when the agent could not route the message and it went to the fallback."
    )

    @classmethod
    def for_department(
        cls, request_id: UUID, department: Department, *, fallback_used: bool
    ) -> Self:
        """Build a response whose address always matches the department."""
        return cls(
            request_id=request_id,
            department=department,
            routed_to=department.address,
            fallback_used=fallback_used,
        )


class HealthResponse(BaseModel):
    """Liveness of the API process."""

    status: Literal["ok"] = "ok"
