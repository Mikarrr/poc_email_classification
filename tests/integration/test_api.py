import logging
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai import Agent

from email_classifier.agent import RoutingDeps
from email_classifier.api.app import create_app
from email_classifier.config import Settings
from tests.fakes import HELP_DESK_CALL, FakeMailer, calls_send_email, raises_error

SENDER = "jan.nowak@example.com"
MESSAGE = "Nie działa mi komputer"
PAYLOAD = {"email": SENDER, "message": MESSAGE}


@pytest.fixture
def app(fake_mailer: FakeMailer) -> FastAPI:
    return create_app(Settings(_env_file=None), mailer=fake_mailer)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def agent_of(app: FastAPI) -> Agent[RoutingDeps, str]:
    agent: Agent[RoutingDeps, str] = app.state.agent
    return agent


# ── Service endpoints ────────────────────────────────────────────


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_swagger_ui_is_served_under_api_v1(client: TestClient) -> None:
    response = client.get("/api/v1/docs")

    assert response.status_code == 200
    assert "swagger-ui" in response.text


def test_openapi_schema_lists_the_endpoints(client: TestClient) -> None:
    schema = client.get("/api/v1/openapi.json").json()

    assert {"/api/v1/messages", "/api/v1/health"} <= set(schema["paths"])


# ── Routing ──────────────────────────────────────────────────────


def test_routes_the_message_and_sends_the_email(
    app: FastAPI, client: TestClient, fake_mailer: FakeMailer
) -> None:
    with agent_of(app).override(model=calls_send_email(**HELP_DESK_CALL)):
        response = client.post("/api/v1/messages", json=PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert UUID(body["request_id"])
    assert body["department"] == "help_desk"
    assert body["routed_to"] == "help-desk@example.com"
    assert body["fallback_used"] is False
    assert [(email.to, email.reply_to) for email in fake_mailer.sent] == [
        ("help-desk@example.com", SENDER)
    ]


def test_model_failure_still_routes_to_other(
    app: FastAPI, client: TestClient, fake_mailer: FakeMailer
) -> None:
    with agent_of(app).override(model=raises_error()):
        response = client.post("/api/v1/messages", json=PAYLOAD)

    assert response.status_code == 200
    assert response.json()["routed_to"] == "other@example.com"
    assert response.json()["fallback_used"] is True
    assert [email.to for email in fake_mailer.sent] == ["other@example.com"]


def test_each_request_gets_its_own_id(app: FastAPI, client: TestClient) -> None:
    with agent_of(app).override(model=calls_send_email(**HELP_DESK_CALL)):
        first = client.post("/api/v1/messages", json=PAYLOAD).json()["request_id"]
        second = client.post("/api/v1/messages", json=PAYLOAD).json()["request_id"]

    assert first != second


# ── Errors ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "message": MESSAGE},
        {"email": SENDER, "message": "   "},
        {"email": SENDER},
    ],
    ids=["bad-email", "blank-message", "no-message"],
)
def test_invalid_input_returns_422_and_sends_nothing(
    client: TestClient, fake_mailer: FakeMailer, payload: dict[str, str]
) -> None:
    response = client.post("/api/v1/messages", json=payload)

    assert response.status_code == 422
    assert fake_mailer.sent == []


def test_mail_server_down_returns_503(
    app: FastAPI, client: TestClient, fake_mailer: FakeMailer
) -> None:
    fake_mailer.fail = True

    with agent_of(app).override(model=calls_send_email(**HELP_DESK_CALL)):
        response = client.post("/api/v1/messages", json=PAYLOAD)

    assert response.status_code == 503
    assert response.json() == {"detail": "The mail server is unavailable. Try again later."}


# ── Logging ──────────────────────────────────────────────────────


def test_logs_the_routing_but_not_the_message(
    app: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="email_classifier")

    with agent_of(app).override(model=calls_send_email(**HELP_DESK_CALL)):
        request_id = client.post("/api/v1/messages", json=PAYLOAD).json()["request_id"]

    assert f"request {request_id}: routed to help_desk" in caplog.text
    assert MESSAGE not in caplog.text
    assert SENDER not in caplog.text


def test_swagger_response_example_matches_the_request_example(client: TestClient) -> None:
    schemas = client.get("/api/v1/openapi.json").json()["components"]["schemas"]

    request_example = schemas["RouteMessageRequest"]["examples"][0]
    response_example = schemas["RouteMessageResponse"]["examples"][0]

    assert request_example["message"] == "Nie działa mi komputer"
    assert response_example["department"] == "help_desk"
    assert response_example["routed_to"] == "help-desk@example.com"
