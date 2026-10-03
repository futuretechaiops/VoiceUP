from sqlalchemy.orm import Session

from .auth import Principal
from .models import AuditEvent


def record_audit(
    db: Session,
    principal: Principal,
    action: str,
    target_type: str,
    target_id: str,
    outcome: str = "success",
) -> None:
    db.add(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor_user_id=principal.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
        )
    )
