"""End-to-end check against the running compose stack: API → Ollama → Mailpit (`make e2e`)."""

import json
import os
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

API_URL = os.environ.get("E2E_API_URL", "http://localhost:8000")
MAILPIT_URL = os.environ.get("E2E_MAILPIT_URL", "http://localhost:8025")
SPLIT = os.environ.get("E2E_SPLIT", "all")
MIN_ACCURACY = float(os.environ.get("E2E_MIN_ACCURACY", "0.9"))
CASES_FILE = Path(__file__).parents[1] / "fixtures" / "routing_cases.jsonl"


# ── Data ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Case:
    id: str
    message: str
    expected: str
    split: str

    @property
    def sender(self) -> str:
        return f"{self.id}@example.com"


@dataclass(frozen=True)
class Outcome:
    case: Case
    department: str
    routed_to: str
    fallback_used: bool
    mail_to: list[str]
    mail_reply_to: list[str]
    seconds: float

    @property
    def correct(self) -> bool:
        return self.department == self.case.expected


def load_cases() -> list[Case]:
    lines = CASES_FILE.read_text(encoding="utf-8").splitlines()
    cases = [Case(**json.loads(line)) for line in lines if line.strip()]
    return [case for case in cases if SPLIT in ("all", case.split)]


# ── Running the cases ────────────────────────────────────────────


def addresses(people: list[dict[str, str]]) -> list[str]:
    return [person["Address"] for person in people]


def route(client: httpx.Client, case: Case) -> Outcome:
    started = time.perf_counter()
    response = client.post(
        f"{API_URL}/api/v1/messages", json={"email": case.sender, "message": case.message}
    )
    response.raise_for_status()
    seconds = time.perf_counter() - started
    body = response.json()
    mail = client.get(f"{MAILPIT_URL}/api/v1/message/latest").raise_for_status().json()
    return Outcome(
        case=case,
        department=body["department"],
        routed_to=body["routed_to"],
        fallback_used=body["fallback_used"],
        mail_to=addresses(mail["To"]),
        mail_reply_to=addresses(mail["ReplyTo"]),
        seconds=seconds,
    )


def accuracy(outcomes: Iterable[Outcome]) -> tuple[int, int]:
    results = [outcome.correct for outcome in outcomes]
    return sum(results), len(results)


def report(outcomes: list[Outcome]) -> str:
    lines = ["", "── routing report ──"]
    groups: dict[str, list[Outcome]] = defaultdict(list)
    for outcome in outcomes:
        groups[f"split {outcome.case.split}"].append(outcome)
        groups[f"expected {outcome.case.expected}"].append(outcome)
    for name in sorted(groups):
        good, total = accuracy(groups[name])
        lines.append(f"{name:26} {good:3}/{total:<3} {good / total:6.1%}")
    good, total = accuracy(outcomes)
    seconds = [outcome.seconds for outcome in outcomes]
    lines.append(f"{'all':26} {good:3}/{total:<3} {good / total:6.1%}")
    lines.append(
        f"time per request: avg {sum(seconds) / len(seconds):.1f}s, max {max(seconds):.1f}s"
    )
    lines.append("misses:")
    for outcome in outcomes:
        if not outcome.correct:
            fallback = " (fallback)" if outcome.fallback_used else ""
            lines.append(
                f"  [{outcome.case.split}] {outcome.case.id}: expected {outcome.case.expected}, "
                f"got {outcome.department}{fallback} | {outcome.case.message}"
            )
    return "\n".join(lines)


@pytest.fixture(scope="module")
def outcomes() -> list[Outcome]:
    try:
        httpx.get(f"{API_URL}/api/v1/health", timeout=3).raise_for_status()
        httpx.get(f"{MAILPIT_URL}/api/v1/info", timeout=3).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(f"the compose stack is not running ({exc}); start it with `make up`")

    with httpx.Client(timeout=300) as client:
        client.delete(f"{MAILPIT_URL}/api/v1/messages").raise_for_status()
        results = [route(client, case) for case in load_cases()]
    print(report(results))
    return results


# ── Checks ───────────────────────────────────────────────────────


def test_every_request_sends_one_email_with_the_sender_as_reply_to(
    outcomes: list[Outcome],
) -> None:
    total = httpx.get(f"{MAILPIT_URL}/api/v1/messages").raise_for_status().json()["total"]

    assert total == len(outcomes)
    for outcome in outcomes:
        assert outcome.mail_to == [outcome.routed_to], outcome.case.id
        assert outcome.mail_reply_to == [outcome.case.sender], outcome.case.id


def test_routing_accuracy(outcomes: list[Outcome]) -> None:
    good, total = accuracy(outcomes)

    assert good / total >= MIN_ACCURACY, f"{good}/{total} routed correctly"
