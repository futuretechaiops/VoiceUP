"""Transactional email outbox: enqueue in the same transaction as the lead, deliver with retries."""

import logging
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from .db import bind_context
from .mailer import Mailer, MailError
from .models import EmailOutbox, utcnow

log = logging.getLogger("concierge.outbox")
MAX_ATTEMPTS = 8


def enqueue_email(
    db: Session, *, tenant_id: str, to: str, subject: str, body: str, key: str, reply_to: str | None
) -> EmailOutbox:
    item = EmailOutbox(
        tenant_id=tenant_id, to_address=to, subject=subject[:300], body=body,
        idempotency_key=key, reply_to=reply_to,
    )  # fmt: skip
    db.add(item)
    return item


def deliver(item: EmailOutbox, mailer: Mailer) -> bool:
    try:
        mailer.send(
            to=item.to_address, subject=item.subject, body=item.body, reply_to=item.reply_to
        )
    except MailError as exc:
        item.attempts += 1
        item.last_error = str(exc)
        if item.attempts >= MAX_ATTEMPTS:
            item.status = "dead"  # surfaced for an operator; never retried silently forever
            log.error("email %s moved to dead after %s attempts", item.id, item.attempts)
        else:
            item.next_attempt_at = utcnow() + timedelta(seconds=min(30 * 2**item.attempts, 3600))
        return False
    item.status = "sent"
    item.sent_at = utcnow()
    item.attempts += 1
    item.last_error = None
    return True


def process_outbox(factory: sessionmaker[Session], mailer: Mailer, limit: int = 20) -> int:
    """Send due emails for every tenant that has some. Returns the number sent."""
    sent = 0
    with factory() as probe:
        tenant_ids = list(probe.scalars(text("SELECT outbox_due_tenants()")))
    for tenant_id in tenant_ids:
        with factory() as db:
            bind_context(db, tenant_id=tenant_id)
            due = db.scalars(
                select(EmailOutbox)
                .where(EmailOutbox.status == "pending", EmailOutbox.next_attempt_at <= utcnow())
                .order_by(EmailOutbox.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for item in due:
                sent += 1 if deliver(item, mailer) else 0
            db.commit()
    return sent
