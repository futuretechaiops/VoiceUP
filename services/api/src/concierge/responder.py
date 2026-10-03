"""Conversation responder boundary.

The real engine (retrieval, model, tool policy) arrives in WP4 behind this interface. Until then
a clearly labelled placeholder lets the embed, consent, CORS and session flow be tested end to end.
"""

from typing import Protocol


class Responder(Protocol):
    def reply(self, *, agent_name: str, visitor_text: str) -> str: ...


class PlaceholderResponder:
    def reply(self, *, agent_name: str, visitor_text: str) -> str:
        return (
            f"[Test reply from {agent_name}] I received: “{visitor_text[:200]}”. "
            "This is a placeholder: real answers from your website content arrive once the "
            "knowledge and AI engine are connected."
        )


def get_responder() -> Responder:
    return PlaceholderResponder()
