"""FastAPI application: routes user messages to departments under `/api/v1`."""

import logging
import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from pydantic_ai import Agent

from email_classifier import __version__
from email_classifier.agent import MailSender, RoutingDeps, build_agent, route_message
from email_classifier.config import Settings, get_settings
from email_classifier.departments import Department
from email_classifier.mailer import MailDeliveryError, Mailer
from email_classifier.schemas import HealthResponse, RouteMessageRequest, RouteMessageResponse

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

DESCRIPTION = """
Send a user's message and their email address. An AI agent running on a local Ollama model
picks the department that should handle it and forwards the message there by email, with
`Reply-To` set to the sender. Unclear messages, and every case where the agent fails, go to
`other@example.com`.
"""


# ── Dependencies ─────────────────────────────────────────────────


def get_agent(request: Request) -> Agent[RoutingDeps, Department]:
    agent: Agent[RoutingDeps, Department] = request.app.state.agent
    return agent


def get_mailer(request: Request) -> MailSender:
    mailer: MailSender = request.app.state.mailer
    return mailer


AgentDep = Annotated[Agent[RoutingDeps, Department], Depends(get_agent)]
MailerDep = Annotated[MailSender, Depends(get_mailer)]


# ── Routes ───────────────────────────────────────────────────────


router = APIRouter(prefix=API_PREFIX)


@router.get("/health", tags=["health"], summary="Check that the API is running")
def health() -> HealthResponse:
    return HealthResponse()


@router.post(
    "/messages",
    tags=["messages"],
    summary="Route a message to the right department",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The mail server is down."}},
)
async def create_message(
    payload: RouteMessageRequest, agent: AgentDep, mailer: MailerDep
) -> RouteMessageResponse:
    request_id = uuid4()
    started = time.perf_counter()
    try:
        result = await route_message(agent, mailer, str(payload.email), payload.message)
    except MailDeliveryError:
        logger.exception("request %s: mail delivery failed", request_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The mail server is unavailable. Try again later.",
        ) from None
    logger.info(
        "request %s: routed to %s (fallback=%s) in %.2fs",
        request_id,
        result.department,
        result.fallback_used,
        time.perf_counter() - started,
    )
    return RouteMessageResponse.for_department(
        request_id, result.department, fallback_used=result.fallback_used
    )


# ── App factory ──────────────────────────────────────────────────


def create_app(settings: Settings | None = None, *, mailer: MailSender | None = None) -> FastAPI:
    """Build the app. Run it with `uvicorn email_classifier.api.app:create_app --factory`."""
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = FastAPI(
        title="AI Message Router",
        version=__version__,
        description=DESCRIPTION,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
    )
    app.state.agent = build_agent(settings)
    app.state.mailer = mailer or Mailer.from_settings(settings)
    app.include_router(router)
    return app
