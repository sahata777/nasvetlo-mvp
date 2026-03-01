"""Provider-agnostic LLM interface."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from nasvetlo.logging_utils import get_logger

log = get_logger("llm")

PROMPTS_DIR = Path(__file__).parent / "prompts"


class LLMResponse(BaseModel):
    text: str
    usage: dict[str, int] = {}


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 4096) -> LLMResponse:
        ...


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929"):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 4096) -> LLMResponse:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        return LLMResponse(text=text, usage=usage)


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        import openai
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 4096) -> LLMResponse:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        usage = {}
        if resp.usage:
            usage = {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens}
        return LLMResponse(text=text, usage=usage)


class MockLLMProvider(LLMProvider):
    """Mock provider for testing. Returns canned responses."""

    def __init__(self, responses: dict[str, str] | None = None):
        self._responses = responses or {}
        self._calls: list[dict[str, str]] = []

    def complete(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 4096) -> LLMResponse:
        self._calls.append({"system": system, "user": user})
        # Try to match by keyword in system prompt
        for key, response in self._responses.items():
            if key.lower() in system.lower():
                return LLMResponse(text=response)
        # Default response
        return LLMResponse(text='{"error": "no mock configured"}')


_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        from nasvetlo.settings import get_settings
        from nasvetlo.config import get_config
        settings = get_settings()
        config = get_config()
        provider_name = config.llm.provider or settings.llm_provider
        if provider_name == "anthropic":
            _provider = AnthropicProvider(api_key=settings.anthropic_api_key, model=config.llm.model)
        elif provider_name == "openai":
            _provider = OpenAIProvider(api_key=settings.openai_api_key, model=config.llm.model)
        else:
            raise ValueError(f"Unknown LLM provider: {provider_name}")
    return _provider


def set_llm_provider(provider: LLMProvider) -> None:
    global _provider
    _provider = provider


def load_prompt(name: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    path = PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def call_llm_json(system: str, user: str, retries: int = 2, **kwargs: Any) -> dict:
    """Call LLM expecting strict JSON. Retry on parse failure."""
    provider = get_llm_provider()
    last_error = None
    for attempt in range(retries + 1):
        resp = provider.complete(system=system, user=user, **kwargs)
        text = resp.text.strip()
        # Try to extract JSON from markdown code block
        if text.startswith("```"):
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last_error = e
            log.warning("LLM JSON parse error (attempt %d/%d): %s", attempt + 1, retries + 1, e)
    raise ValueError(f"LLM returned invalid JSON after {retries + 1} attempts: {last_error}")
