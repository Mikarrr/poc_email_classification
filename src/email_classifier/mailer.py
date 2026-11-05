"""Outgoing mail: builds a plain-text UTF-8 email and hands it to an SMTP server."""

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from email_classifier.config import Settings


class MailDeliveryError(Exception):
    """The SMTP server could not be reached or refused the message."""


@dataclass(frozen=True)
class Mailer:
    """Sends one email per call over plain SMTP (Mailpit in this project)."""

    host: str
    port: int
    sender: str
    timeout: float = 10.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "Mailer":
        return cls(
            host=settings.smtp_host,
            port=settings.smtp_port,
            sender=str(settings.mail_from),
            timeout=settings.smtp_timeout_seconds,
        )

    def build_message(self, *, to: str, reply_to: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Reply-To"] = reply_to
        message["Subject"] = " ".join(subject.split())
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=self.sender.rpartition("@")[2] or None)
        message.set_content(body, charset="utf-8")
        return message

    def send(self, *, to: str, reply_to: str, subject: str, body: str) -> str:
        """Send the email and return its Message-ID.

        Raises:
            MailDeliveryError: the server is unreachable, timed out or rejected the message.
        """
        message = self.build_message(to=to, reply_to=reply_to, subject=subject, body=body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                smtp.send_message(message, from_addr=self.sender, to_addrs=[to])
        except (smtplib.SMTPException, OSError) as exc:
            raise MailDeliveryError(
                f"could not send mail via {self.host}:{self.port}: {exc}"
            ) from exc
        return str(message["Message-ID"])
