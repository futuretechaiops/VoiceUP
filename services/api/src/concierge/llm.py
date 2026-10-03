"""Language-model boundary. Provider code stays behind this interface (spec section 6)."""

from typing import Protocol

import anthropic


class LlmError(Exception):
    pass


class LlmClient(Protocol):
    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int) -> str: ...


class AnthropicLlm:
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._model = model
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=20.0, max_retries=1, base_url=base_url
        )

    def complete(self, *, system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
            )
        except anthropic.AnthropicError as exc:
            raise LlmError(type(exc).__name__) from exc
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise LlmError("empty response")
        return text
