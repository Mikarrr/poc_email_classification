"""Routing agent: the LLM picks a department by calling `send_email`, which forwards the message."""

import asyncio
import logging
from dataclasses import dataclass
from importlib.resources import files
from typing import Protocol

from pydantic_ai import Agent, RunContext, ToolOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from email_classifier.config import Settings
from email_classifier.departments import FALLBACK_DEPARTMENT, Department
from email_classifier.mailer import MailDeliveryError

logger = logging.getLogger(__name__)

FALLBACK_REASON = "Automatic routing failed, so the message went to the default department."


# ── Types ────────────────────────────────────────────────────────


class MailSender(Protocol):
    def send(self, *, to: str, reply_to: str, subject: str, body: str) -> str: ...


@dataclass
class RoutingDeps:
    sender_email: str
    message: str
    mailer: MailSender


@dataclass(frozen=True)
class RoutingResult:
    department: Department
    fallback_used: bool


# ── Helpers ──────────────────────────────────────────────────────


def load_system_prompt() -> str:
    return files("email_classifier").joinpath("prompts/system.md").read_text(encoding="utf-8")


def compose_body(message: str, reason: str) -> str:
    return f"{message}\n\n---\nRouting note: {reason}\n"


# ── Output function ──────────────────────────────────────────────


def send_email(
    ctx: RunContext[RoutingDeps], department: Department, subject: str, reason: str
) -> Department:
    """Forward the message to the chosen department.

    Args:
        department: the department that should handle the message.
        subject: a short summary of the request, at most 8 words.
        reason: one sentence on why this department fits.
    """
    deps = ctx.deps
    deps.mailer.send(
        to=department.address,
        reply_to=deps.sender_email,
        subject=subject,
        body=compose_body(deps.message, reason),
    )
    return department


# ── Agent ────────────────────────────────────────────────────────


def build_agent(settings: Settings) -> Agent[RoutingDeps, Department]:
    model = OpenAIChatModel(
        settings.ollama_model,
        provider=OllamaProvider(base_url=f"{settings.ollama_base_url}/v1"),
    )
    return Agent(
        model,
        deps_type=RoutingDeps,
        instructions=load_system_prompt(),
        output_type=ToolOutput(send_email, name="send_email"),
        model_settings=ModelSettings(
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
        ),
        retries=2,
    )


# ── Routing with fallback ────────────────────────────────────────


async def route_message(
    agent: Agent[RoutingDeps, Department], mailer: MailSender, sender_email: str, message: str
) -> RoutingResult:
    deps = RoutingDeps(sender_email=sender_email, message=message, mailer=mailer)
    try:
        result = await agent.run(
            f"<message>\n{message}\n</message>",
            deps=deps,
            usage_limits=UsageLimits(request_limit=4),
        )
    except MailDeliveryError:
        raise
    except Exception:
        logger.exception("agent run failed, using the fallback department")
    else:
        return RoutingResult(department=result.output, fallback_used=False)

    await asyncio.to_thread(
        mailer.send,
        to=FALLBACK_DEPARTMENT.address,
        reply_to=sender_email,
        subject=f"New message from {sender_email}",
        body=compose_body(message, FALLBACK_REASON),
    )
    return RoutingResult(department=FALLBACK_DEPARTMENT, fallback_used=True)
