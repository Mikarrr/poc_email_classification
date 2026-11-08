"""Test doubles shared by the unit and integration tests: a fake mailer and scripted LLMs."""

from dataclasses import dataclass, field

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from email_classifier.mailer import MailDeliveryError

HELP_DESK_CALL = {"department": "help_desk", "subject": "Komputer nie działa", "reason": "Device."}


# ── Mailer ───────────────────────────────────────────────────────


@dataclass
class SentEmail:
    to: str
    reply_to: str
    subject: str
    body: str


@dataclass
class FakeMailer:
    sent: list[SentEmail] = field(default_factory=list)
    fail: bool = False

    def send(self, *, to: str, reply_to: str, subject: str, body: str) -> str:
        if self.fail:
            raise MailDeliveryError("smtp is down")
        self.sent.append(SentEmail(to=to, reply_to=reply_to, subject=subject, body=body))
        return "<id@example.com>"


# ── Scripted models ──────────────────────────────────────────────


def calls_send_email(**args: str) -> FunctionModel:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("send_email", args)])

    return FunctionModel(model)


def answers_with_text_only() -> FunctionModel:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("I think this is for help desk.")])

    return FunctionModel(model)


def raises_error() -> FunctionModel:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise TimeoutError("model did not answer")

    return FunctionModel(model)
