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
from tests.fakes import (
    HELP_DESK_CALL,
    FakeMailer,
    answers_with_text_only,
    calls_send_email,
    raises_error,
)

SENDER = "jan.nowak@example.com"
MESSAGE = "Nie działa mi komputer"


@pytest.fixture
def agent() -> Agent[RoutingDeps, str]:
    return build_agent(Settings(_env_file=None))


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
