from dataclasses import dataclass, field

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from email_classifier.agent import RoutingDeps, build_agent, route_message
from email_classifier.config import Settings
from email_classifier.departments import Department
from email_classifier.mailer import MailDeliveryError

SENDER = "jan.nowak@example.com"
MESSAGE = "Nie działa mi komputer"


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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def agent() -> Agent[RoutingDeps, str]:
    return build_agent(Settings(_env_file=None))


def tool_already_answered(messages: list[ModelMessage]) -> bool:
    last = messages[-1]
    return isinstance(last, ModelRequest) and any(
        isinstance(part, ToolReturnPart) for part in last.parts
    )


def calls_send_email(**args: str) -> FunctionModel:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if tool_already_answered(messages):
            return ModelResponse(parts=[TextPart("Done.")])
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


HELP_DESK_CALL = {"department": "help_desk", "subject": "Komputer nie działa", "reason": "Device."}


@pytest.mark.anyio
async def test_sends_to_the_department_chosen_by_the_model(agent: Agent[RoutingDeps, str]) -> None:
    mailer = FakeMailer()

    with agent.override(model=calls_send_email(**HELP_DESK_CALL)):
        result = await route_message(agent, mailer, SENDER, MESSAGE)

    assert result.department is Department.HELP_DESK
    assert result.fallback_used is False
    assert [email.to for email in mailer.sent] == ["help-desk@example.com"]


@pytest.mark.anyio
async def test_email_has_sender_as_reply_to_and_keeps_the_message(
    agent: Agent[RoutingDeps, str],
) -> None:
    mailer = FakeMailer()

    with agent.override(model=calls_send_email(**HELP_DESK_CALL)):
        await route_message(agent, mailer, SENDER, MESSAGE)

    email = mailer.sent[0]
    assert email.reply_to == SENDER
    assert email.subject == "Komputer nie działa"
    assert MESSAGE in email.body
    assert "Device." in email.body


@pytest.mark.anyio
async def test_model_sees_the_prompt_and_the_message_in_tags(
    agent: Agent[RoutingDeps, str],
) -> None:
    seen: dict[str, str] = {}

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        request = messages[0]
        assert isinstance(request, ModelRequest)
        seen["instructions"] = info.instructions or ""
        seen["prompt"] = str(
            next(part for part in request.parts if isinstance(part, UserPromptPart)).content
        )
        return ModelResponse(parts=[TextPart("ok")])

    with agent.override(model=FunctionModel(model)):
        await route_message(agent, FakeMailer(), SENDER, MESSAGE)

    assert "help_desk" in seen["instructions"]
    assert seen["prompt"] == f"<message>\n{MESSAGE}\n</message>"


@pytest.mark.anyio
async def test_tool_has_no_address_parameters(agent: Agent[RoutingDeps, str]) -> None:
    seen: dict[str, object] = {}

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.function_tools[0]
        seen["name"] = tool.name
        seen["params"] = set(tool.parameters_json_schema["properties"])
        return ModelResponse(parts=[TextPart("ok")])

    with agent.override(model=FunctionModel(model)):
        await route_message(agent, FakeMailer(), SENDER, MESSAGE)

    assert seen == {"name": "send_email", "params": {"department", "subject", "reason"}}


@pytest.mark.anyio
async def test_unknown_department_is_rejected_and_retried(agent: Agent[RoutingDeps, str]) -> None:
    calls: list[str] = []

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(calls) == 2:
            return ModelResponse(parts=[TextPart("Done.")])
        department = "finance" if not calls else "it"
        calls.append(department)
        args = {"department": department, "subject": "s", "reason": "r"}
        return ModelResponse(parts=[ToolCallPart("send_email", args)])

    mailer = FakeMailer()
    with agent.override(model=FunctionModel(model)):
        result = await route_message(agent, mailer, SENDER, MESSAGE)

    assert calls == ["finance", "it"]
    assert result.department is Department.IT
    assert [email.to for email in mailer.sent] == ["it@example.com"]


@pytest.mark.anyio
async def test_second_tool_call_does_not_send_again(agent: Agent[RoutingDeps, str]) -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        )
        if returns >= 2:
            return ModelResponse(parts=[TextPart("Done.")])
        department = "help_desk" if returns == 0 else "it"
        args = {"department": department, "subject": "s", "reason": "r"}
        return ModelResponse(parts=[ToolCallPart("send_email", args)])

    mailer = FakeMailer()
    with agent.override(model=FunctionModel(model)):
        result = await route_message(agent, mailer, SENDER, MESSAGE)

    assert result.department is Department.HELP_DESK
    assert [email.to for email in mailer.sent] == ["help-desk@example.com"]


@pytest.mark.anyio
async def test_no_tool_call_falls_back_to_other(agent: Agent[RoutingDeps, str]) -> None:
    mailer = FakeMailer()

    with agent.override(model=answers_with_text_only()):
        result = await route_message(agent, mailer, SENDER, MESSAGE)

    assert result.department is Department.OTHER
    assert result.fallback_used is True
    assert [email.to for email in mailer.sent] == ["other@example.com"]
    assert mailer.sent[0].reply_to == SENDER
    assert MESSAGE in mailer.sent[0].body


@pytest.mark.anyio
async def test_model_error_falls_back_to_other(agent: Agent[RoutingDeps, str]) -> None:
    mailer = FakeMailer()

    with agent.override(model=raises_error()):
        result = await route_message(agent, mailer, SENDER, MESSAGE)

    assert result.department is Department.OTHER
    assert result.fallback_used is True
    assert [email.to for email in mailer.sent] == ["other@example.com"]


@pytest.mark.anyio
async def test_mail_delivery_error_is_not_hidden(agent: Agent[RoutingDeps, str]) -> None:
    mailer = FakeMailer(fail=True)

    with agent.override(model=calls_send_email(**HELP_DESK_CALL)), pytest.raises(MailDeliveryError):
        await route_message(agent, mailer, SENDER, MESSAGE)
