"""Structured JSON logs. Never log credentials, tokens or transcript content."""

import json
import logging
import sys
from datetime import UTC, datetime

_SENSITIVE = ("authorization", "secret", "token", "password", "cookie")
_EXTRA_FIELDS = ("request_id", "method", "path", "status", "duration_ms", "tenant_id")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), default=str)


def redact(payload: dict[str, object]) -> dict[str, object]:
    return {
        k: "[redacted]" if any(s in k.lower() for s in _SENSITIVE) else v
        for k, v in payload.items()
    }


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
