"""Call-back leads: validation, consent, honeypot, one-per-session, and real SMTP delivery."""

import email
import email.policy
import socket
from collections.abc import Iterator

import pytest
from aiosmtpd.controller import Controller
from conftest import A_TENANT
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from test_widget import SITE, EchoResponder, approve, make_agent, start

from concierge.config import Settings
from concierge.db import SessionLocal
from concierge.mailer import MailError, SmtpMailer
from concierge.main import app
from concierge.outbox import MAX_ATTEMPTS, process_outbox
from concierge.responder import get_responder

TO = "info@futuretec.example"
GOOD = {
    "name": "Jane Visitor",
    "phone": "07700 900123",
    "email": "jane@example.com",
    "consent": True,
}


class Sink:
    def __init__(self) -> None:
        self.messages: list[email.message.EmailMessage] = []

    async def handle_DATA(self, server, session, envelope):  # type: ignore[no-untyped-def]  # noqa: N802, ANN001
        self.messages.append(
            email.message_from_bytes(envelope.content, policy=email.policy.default)
        )  # type: ignore[arg-type]
        return "250 OK"


@pytest.fixture
def smtp() -> Iterator[tuple[Controller, Sink]]:
    sink = Sink()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    controller = Controller(sink, hostname="127.0.0.1", port=port)
    controller.start()
    yield controller, sink
    controller.stop()


def mailer_for(controller: Controller) -> SmtpMailer:
    return SmtpMailer(
        Settings(
            SMTP_HOST="127.0.0.1", SMTP_PORT=controller.port,
            SMTP_STARTTLS=False, MAIL_FROM="Site Assistant <no-reply@futuretec.example>",
        )  # type: ignore[call-arg]
    )  # fmt: skip


@pytest.fixture(autouse=True)
def echo() -> Iterator[None]:
    app.dependency_overrides[get_responder] = lambda: EchoResponder()
    yield
    app.dependency_overrides.pop(get_responder, None)


@pytest.fixture(autouse=True)
def no_background_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoint kicks off delivery in the background; tests drive the outbox explicitly."""
    monkeypatch.setattr("concierge.widget_api.process_outbox", lambda *a, **k: 0)


@pytest.fixture
def session(client: TestClient, seeded: Engine) -> dict[str, str]:
    with seeded.begin() as conn:
        conn.execute(
            text("UPDATE tenants SET notify_email = :e WHERE id = :t"), {"e": TO, "t": A_TENANT}
        )
    public_id = make_agent(client)
    approve(client)
    body = start(client, public_id).json()
    client.post(
        f"/api/v1/public/widget/session/{body['session_id']}/events",
        json={"type": "message", "text": "I need a quote for repairs"},
        headers={"Authorization": f"Bearer {body['token']}", "Origin": SITE},
    )
    return body


def post_lead(client: TestClient, s: dict[str, str], payload: dict[str, object]):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/public/widget/session/{s['session_id']}/lead",
        json=payload,
        headers={"Authorization": f"Bearer {s['token']}", "Origin": SITE},
    )


def test_session_response_carries_consent_text(session: dict[str, str]) -> None:
    assert "contact me" in session["consent_text"]


def test_lead_is_stored_queued_and_emailed_with_reply_to(
    client: TestClient, session: dict[str, str], seeded: Engine, smtp: tuple[Controller, Sink]
) -> None:
    controller, sink = smtp
    response = post_lead(client, session, GOOD)
    assert response.status_code == 201 and response.json()["status"] == "received"
    with seeded.connect() as conn:
        lead = conn.execute(text("SELECT name, phone, email, consent_text FROM leads")).one()
        assert (lead.name, lead.phone, lead.email) == (
            "Jane Visitor", "+447700900123", "jane@example.com",
        )  # fmt: skip
        assert lead.consent_text
        queued = conn.execute(text("SELECT status, to_address FROM email_outbox")).one()
        assert queued.to_address == TO
    # deliver through a real SMTP server (the background worker is disabled in tests)
    assert process_outbox(SessionLocal, mailer_for(controller)) == 1
    assert len(sink.messages) == 1
    message = sink.messages[0]
    assert message["To"] == TO and message["Reply-To"] == "jane@example.com"
    body = message.get_content()
    assert "Jane Visitor" in body and "+447700900123" in body and "jane@example.com" in body
    assert "I need a quote for repairs" in body  # transcript context for the sales team
    assert process_outbox(SessionLocal, mailer_for(controller)) == 0  # sent once only
    with seeded.connect() as conn:
        assert conn.execute(text("SELECT status FROM email_outbox")).scalar() == "sent"


def test_second_submission_in_same_session_is_ignored(
    client: TestClient, session: dict[str, str], seeded: Engine
) -> None:
    assert post_lead(client, session, GOOD).status_code == 201
    again = post_lead(client, session, {**GOOD, "name": "Someone Else"})
    assert again.json()["status"] == "already_received"
    with seeded.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM leads")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM email_outbox")).scalar() == 1


@pytest.mark.parametrize(
    "change",
    [
        {"consent": False}, {"email": "not-an-email"}, {"phone": "abc"}, {"phone": "123"},
        {"name": "<script>"}, {"name": "J"},
    ],
)  # fmt: skip
def test_invalid_leads_are_rejected_and_nothing_is_stored(
    client: TestClient, session: dict[str, str], seeded: Engine, change: dict[str, object]
) -> None:
    assert post_lead(client, session, {**GOOD, **change}).status_code == 422
    with seeded.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM leads")).scalar() == 0


def test_honeypot_looks_successful_but_stores_and_sends_nothing(
    client: TestClient, session: dict[str, str], seeded: Engine
) -> None:
    response = post_lead(client, session, {**GOOD, "website": "http://spam.example"})
    assert response.status_code == 201
    with seeded.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM leads")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM email_outbox")).scalar() == 0


def test_lead_needs_a_valid_token_and_approved_origin(
    client: TestClient, session: dict[str, str]
) -> None:
    url = f"/api/v1/public/widget/session/{session['session_id']}/lead"
    assert client.post(url, json=GOOD, headers={"Origin": SITE}).status_code == 401
    bad_origin = client.post(
        url,
        json=GOOD,
        headers={"Authorization": f"Bearer {session['token']}", "Origin": "https://evil.example"},
    )
    assert bad_origin.status_code == 403


def test_header_injection_in_name_cannot_add_headers(
    client: TestClient, session: dict[str, str], seeded: Engine, smtp: tuple[Controller, Sink]
) -> None:
    controller, sink = smtp
    # the name validator collapses whitespace, so the newline never reaches a header
    r = post_lead(client, session, {**GOOD, "name": "Jane\r\nBcc: attacker@example.com"})
    assert r.status_code in (201, 422)
    process_outbox(SessionLocal, mailer_for(controller))
    for message in sink.messages:
        assert message["Bcc"] is None  # no injected header; the text stays inside the subject
        assert "\n" not in str(message["Subject"]) and message["To"] == TO


def test_smtp_failure_is_retried_with_backoff_then_goes_dead(
    client: TestClient, session: dict[str, str], seeded: Engine
) -> None:
    assert post_lead(client, session, GOOD).status_code == 201

    class Down:
        def send(self, **_: object) -> None:
            raise MailError("connection refused")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        assert process_outbox(SessionLocal, Down()) == 0
        with seeded.begin() as conn:
            row = conn.execute(text("SELECT status, attempts FROM email_outbox")).one()
            assert row.attempts == attempt
            if attempt < MAX_ATTEMPTS:
                assert row.status == "pending"
                conn.execute(  # skip the backoff wait
                    text("UPDATE email_outbox SET next_attempt_at = now() - interval '1 second'")
                )
    assert row.status == "dead"
    assert process_outbox(SessionLocal, Down()) == 0  # dead mail is not retried


def test_backed_off_mail_is_not_retried_early(
    client: TestClient, session: dict[str, str], seeded: Engine, smtp: tuple[Controller, Sink]
) -> None:
    controller, sink = smtp
    assert post_lead(client, session, GOOD).status_code == 201

    class Down:
        def send(self, **_: object) -> None:
            raise MailError("down")

    process_outbox(SessionLocal, Down())
    assert process_outbox(SessionLocal, mailer_for(controller)) == 0  # still backing off
    assert sink.messages == []


def test_no_notify_email_means_lead_is_stored_without_mail(
    client: TestClient, session: dict[str, str], seeded: Engine
) -> None:
    with seeded.begin() as conn:
        conn.execute(text("UPDATE tenants SET notify_email = NULL"))
    assert post_lead(client, session, GOOD).status_code == 201
    with seeded.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM leads")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM email_outbox")).scalar() == 0


def test_lead_rate_limit_per_client(client: TestClient, seeded: Engine) -> None:
    public_id = make_agent(client)
    approve(client)
    hits = []
    for _ in range(7):
        s = start(client, public_id).json()
        hits.append(post_lead(client, s, {**GOOD, "email": "x@example.com"}).status_code)
    assert hits[:5] == [201] * 5 and 429 in hits[5:]


def test_endpoint_triggers_background_delivery(
    client: TestClient,
    session: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    smtp: tuple[Controller, Sink],
) -> None:
    controller, sink = smtp
    import concierge.outbox as outbox

    monkeypatch.setattr("concierge.widget_api.process_outbox", outbox.process_outbox)
    monkeypatch.setattr("concierge.widget_api.get_mailer", lambda _settings: mailer_for(controller))
    assert post_lead(client, session, GOOD).status_code == 201
    assert len(sink.messages) == 1 and sink.messages[0]["To"] == TO


def test_production_demo_mode_needs_no_identity_provider_but_needs_strong_secrets() -> None:
    base = {
        "APP_ENV": "production", "DEV_AUTH_ENABLED": False, "ADMIN_API_ENABLED": False,
        "ALLOW_MANUAL_DOMAIN_VERIFICATION": False, "WIDGET_SIGNING_KEY": "x" * 40,
    }  # fmt: skip
    Settings(**base)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Settings(**{**base, "WIDGET_SIGNING_KEY": "short"})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Settings(**{**base, "DEV_AUTH_ENABLED": True})  # type: ignore[arg-type]
    with pytest.raises(ValueError):  # the full admin API does need an IdP
        Settings(**{**base, "ADMIN_API_ENABLED": True})  # type: ignore[arg-type]
