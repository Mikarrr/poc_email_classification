import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
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

RoutingAgent = Agent[RoutingDeps, Department]


@pytest.fixture
def agent() -> RoutingAgent:
    return build_agent(Settings(_env_file=None))


def scripted(*responses: ModelResponse) -> tuple[FunctionModel, list[int]]:
    """A model that returns the given responses in order and counts how often it was asked."""
    calls: list[int] = []

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        return responses[len(calls) - 1]

    return FunctionModel(model), calls


def send_email_call(department: str) -> ModelResponse:
    args = {"department": department, "subject": "s", "reason": "r"}
    return ModelResponse(parts=[ToolCallPart("send_email", args)])


# ── Routing ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_sends_to_the_department_chosen_by_the_model(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    with agent.override(model=calls_send_email(**HELP_DESK_CALL)):
        result = await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert result.department is Department.HELP_DESK
    assert result.fallback_used is False
    assert [email.to for email in fake_mailer.sent] == ["help-desk@example.com"]


@pytest.mark.anyio
async def test_email_has_sender_as_reply_to_and_keeps_the_message(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    with agent.override(model=calls_send_email(**HELP_DESK_CALL)):
        await route_message(agent, fake_mailer, SENDER, MESSAGE)

    email = fake_mailer.sent[0]
    assert email.reply_to == SENDER
    assert email.subject == "Komputer nie działa"
    assert MESSAGE in email.body
    assert "Device." in email.body


@pytest.mark.anyio
async def test_one_model_call_is_enough(agent: RoutingAgent, fake_mailer: FakeMailer) -> None:
    model, calls = scripted(send_email_call("it"))

    with agent.override(model=model):
        result = await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert result.department is Department.IT
    assert len(calls) == 1


# ── What the model sees ──────────────────────────────────────────


@pytest.mark.anyio
async def test_model_sees_the_prompt_and_the_message_in_tags(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    seen: dict[str, str] = {}

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        request = messages[0]
        assert isinstance(request, ModelRequest)
        seen["instructions"] = info.instructions or ""
        seen["prompt"] = str(
            next(part for part in request.parts if isinstance(part, UserPromptPart)).content
        )
        return send_email_call("help_desk")

    with agent.override(model=FunctionModel(model)):
        await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert "help_desk" in seen["instructions"]
    assert seen["prompt"] == f"<message>\n{MESSAGE}\n</message>"


@pytest.mark.anyio
async def test_send_email_has_no_address_parameters(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    seen: dict[str, object] = {}

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        seen["name"] = tool.name
        seen["params"] = set(tool.parameters_json_schema["properties"])
        seen["text_allowed"] = info.allow_text_output
        return send_email_call("help_desk")

    with agent.override(model=FunctionModel(model)):
        await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert seen == {
        "name": "send_email",
        "params": {"department", "subject", "reason"},
        "text_allowed": False,
    }


# ── Model mistakes that are corrected ────────────────────────────


@pytest.mark.anyio
async def test_unknown_department_is_rejected_and_retried(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    model, calls = scripted(send_email_call("finance"), send_email_call("it"))

    with agent.override(model=model):
        result = await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert len(calls) == 2
    assert result.department is Department.IT
    assert [email.to for email in fake_mailer.sent] == ["it@example.com"]


@pytest.mark.anyio
async def test_text_answer_is_retried_before_falling_back(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    model, calls = scripted(
        ModelResponse(parts=[TextPart("This is for help desk.")]), send_email_call("help_desk")
    )

    with agent.override(model=model):
        result = await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert len(calls) == 2
    assert result.department is Department.HELP_DESK
    assert result.fallback_used is False


@pytest.mark.anyio
async def test_two_calls_in_one_answer_send_only_one_email(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    both = ModelResponse(parts=[*send_email_call("help_desk").parts, *send_email_call("it").parts])
    model, _ = scripted(both)

    with agent.override(model=model):
        result = await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert result.department is Department.HELP_DESK
    assert [email.to for email in fake_mailer.sent] == ["help-desk@example.com"]


# ── Fallback and errors ──────────────────────────────────────────


@pytest.mark.anyio
async def test_no_send_email_call_falls_back_to_other(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    with agent.override(model=answers_with_text_only()):
        result = await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert result.department is Department.OTHER
    assert result.fallback_used is True
    assert [email.to for email in fake_mailer.sent] == ["other@example.com"]
    assert fake_mailer.sent[0].reply_to == SENDER
    assert MESSAGE in fake_mailer.sent[0].body


@pytest.mark.anyio
async def test_model_error_falls_back_to_other(
    agent: RoutingAgent, fake_mailer: FakeMailer
) -> None:
    with agent.override(model=raises_error()):
        result = await route_message(agent, fake_mailer, SENDER, MESSAGE)

    assert result.department is Department.OTHER
    assert result.fallback_used is True
    assert [email.to for email in fake_mailer.sent] == ["other@example.com"]


@pytest.mark.anyio
async def test_mail_delivery_error_is_not_hidden(agent: RoutingAgent) -> None:
    mailer = FakeMailer(fail=True)

    with agent.override(model=calls_send_email(**HELP_DESK_CALL)), pytest.raises(MailDeliveryError):
        await route_message(agent, mailer, SENDER, MESSAGE)
