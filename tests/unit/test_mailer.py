import socket
from collections.abc import Iterator
from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

import pytest
from aiosmtpd.controller import Controller

from email_classifier.config import Settings
from email_classifier.mailer import MailDeliveryError, Mailer

SENDER = "router@example.com"


class RecordingHandler:
    """aiosmtpd handler that keeps every received message for assertions."""

    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        self.envelopes.append(envelope)
        return "250 Message accepted for delivery"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest.fixture
def smtp_server() -> Iterator[tuple[RecordingHandler, int]]:
    handler = RecordingHandler()
    port = free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield handler, port
    finally:
        controller.stop()


def received(handler: RecordingHandler) -> EmailMessage:
    assert len(handler.envelopes) == 1
    raw: bytes = handler.envelopes[0].original_content
    message = message_from_bytes(raw, policy=policy.default)
    assert isinstance(message, EmailMessage)
    return message


def test_send_sets_all_headers_and_body(smtp_server: tuple[RecordingHandler, int]) -> None:
    handler, port = smtp_server
    mailer = Mailer(host="127.0.0.1", port=port, sender=SENDER)

    mailer.send(
        to="help-desk@example.com",
        reply_to="jan.nowak@example.com",
        subject="Computer does not start",
        body="Nie działa mi komputer.",
    )

    message = received(handler)
    assert message["From"] == SENDER
    assert message["To"] == "help-desk@example.com"
    assert message["Reply-To"] == "jan.nowak@example.com"
    assert message["Subject"] == "Computer does not start"
    assert message["Message-ID"]
    assert message["Date"]
    body = message.get_body(preferencelist=("plain",))
    assert body is not None
    assert body.get_content().strip() == "Nie działa mi komputer."


def test_envelope_goes_only_to_the_department(smtp_server: tuple[RecordingHandler, int]) -> None:
    handler, port = smtp_server
    mailer = Mailer(host="127.0.0.1", port=port, sender=SENDER)

    mailer.send(to="it@example.com", reply_to="a@example.com", subject="s", body="b")

    envelope = handler.envelopes[0]
    assert envelope.mail_from == SENDER
    assert envelope.rcpt_tos == ["it@example.com"]


def test_polish_characters_survive_in_subject_and_body(
    smtp_server: tuple[RecordingHandler, int],
) -> None:
    handler, port = smtp_server
    mailer = Mailer(host="127.0.0.1", port=port, sender=SENDER)

    mailer.send(
        to="kadry@example.com",
        reply_to="a@example.com",
        subject="Wniosek o urlop: żółć",
        body="Zażółć gęślą jaźń.",
    )

    message = received(handler)
    assert message["Subject"] == "Wniosek o urlop: żółć"
    body = message.get_body(preferencelist=("plain",))
    assert body is not None
    assert body.get_content().strip() == "Zażółć gęślą jaźń."


def test_newlines_in_subject_cannot_inject_headers(
    smtp_server: tuple[RecordingHandler, int],
) -> None:
    handler, port = smtp_server
    mailer = Mailer(host="127.0.0.1", port=port, sender=SENDER)

    mailer.send(
        to="it@example.com",
        reply_to="jan@example.com",
        subject="Hello\r\nBcc: attacker@evil.test\nReply-To: attacker@evil.test",
        body="b",
    )

    message = received(handler)
    assert message["Bcc"] is None
    assert message.get_all("Reply-To") == ["jan@example.com"]
    assert "\n" not in message["Subject"]
    assert handler.envelopes[0].rcpt_tos == ["it@example.com"]


def test_send_returns_the_message_id(smtp_server: tuple[RecordingHandler, int]) -> None:
    handler, port = smtp_server
    mailer = Mailer(host="127.0.0.1", port=port, sender=SENDER)

    message_id = mailer.send(to="it@example.com", reply_to="a@example.com", subject="s", body="b")

    assert message_id == received(handler)["Message-ID"]


def test_unreachable_server_raises_mail_delivery_error() -> None:
    mailer = Mailer(host="127.0.0.1", port=free_port(), sender=SENDER, timeout=1.0)

    with pytest.raises(MailDeliveryError):
        mailer.send(to="it@example.com", reply_to="a@example.com", subject="s", body="b")


def test_from_settings_uses_smtp_config() -> None:
    settings = Settings(
        _env_file=None,
        smtp_host="mailpit",
        smtp_port=2525,
        smtp_timeout_seconds=3.5,
        mail_from="bot@example.com",
    )

    mailer = Mailer.from_settings(settings)

    assert mailer.host == "mailpit"
    assert mailer.port == 2525
    assert mailer.timeout == 3.5
    assert mailer.sender == "bot@example.com"
