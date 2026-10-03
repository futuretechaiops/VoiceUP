"""Outbound email behind an interface. SMTP in production, log-only when SMTP is not configured."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from .config import Settings, get_settings

log = logging.getLogger("concierge.mailer")


class MailError(Exception):
    pass


class Mailer(Protocol):
    def send(self, *, to: str, subject: str, body: str, reply_to: str | None = None) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        assert settings.smtp_host  # noqa: S101 - guarded by get_mailer
        self._s = settings

    def send(self, *, to: str, subject: str, body: str, reply_to: str | None = None) -> None:
        message = EmailMessage()  # rejects CR/LF in headers, so a visitor cannot inject headers
        message["From"] = self._s.mail_from
        message["To"] = to
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid()
        if reply_to:
            message["Reply-To"] = reply_to
        message.set_content(body)
        host = self._s.smtp_host
        assert host is not None  # noqa: S101
        try:
            if self._s.smtp_use_ssl:
                client: smtplib.SMTP = smtplib.SMTP_SSL(
                    host, self._s.smtp_port, timeout=20,
                    context=ssl.create_default_context(),
                )  # fmt: skip
            else:
                client = smtplib.SMTP(host, self._s.smtp_port, timeout=20)
                if self._s.smtp_starttls:
                    client.starttls(context=ssl.create_default_context())
            with client:
                if self._s.smtp_user and self._s.smtp_password:
                    client.login(self._s.smtp_user, self._s.smtp_password)
                client.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"{type(exc).__name__}: {exc}"[:300]) from exc


class LogMailer:
    """Development fallback: never prints the body, which contains personal details."""

    def send(self, *, to: str, subject: str, body: str, reply_to: str | None = None) -> None:
        log.warning("SMTP not configured; would send email to %s: %s", to, subject)


def get_mailer(settings: Settings | None = None) -> Mailer:
    settings = settings or get_settings()
    return SmtpMailer(settings) if settings.smtp_host else LogMailer()
