"""Adapter gọi chat cho 2 kiểu API (OpenAI-compatible và Anthropic) với cùng một giao diện `chat()`."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.config_loader import CONFIG

from .errors import LLMError, classify_error, is_response_format_unsupported
from .providers import API_STYLE_ANTHROPIC, ProviderSpec


@dataclass
class ChatResponse:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def _default_timeouts() -> tuple[float, int]:
    llm_cfg = CONFIG.get("llm", {})
    return float(llm_cfg.get("timeout_seconds", 90.0)), int(llm_cfg.get("max_retries", 1))


class ChatAdapter:
    """Giao diện chung; mỗi kiểu API cài đặt `_create_client()` và `_call()`."""

    def __init__(
        self,
        spec: ProviderSpec,
        api_key: str,
        base_url: str,
        *,
        client: Any = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.spec = spec
        self.api_key = api_key
        self.base_url = base_url
        default_timeout, default_retries = _default_timeouts()
        self.timeout = default_timeout if timeout is None else timeout
        self.max_retries = default_retries if max_retries is None else max_retries
        self.client = client if client is not None else self._create_client()

    def _client_kwargs(self, api_key: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": self.timeout, "max_retries": self.max_retries}
        if self.base_url:
            url = self.base_url.strip()
            if url.endswith("/chat/completions"):
                url = url[:-len("/chat/completions")].rstrip("/")
            elif url.endswith("/chat/completions/"):
                url = url[:-len("/chat/completions/")].rstrip("/")
            kwargs["base_url"] = url
        return kwargs

    def _create_client(self) -> Any:  # pragma: no cover - cần SDK thật
        raise NotImplementedError

    def _call(self, **kwargs: Any) -> ChatResponse:
        raise NotImplementedError

    def chat(
        self,
        *,
        model: str,
        user: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict | None = None,
    ) -> ChatResponse:
        """Gọi chat một lượt; mọi lỗi SDK được chuẩn hóa thành `LLMError`."""
        try:
            return self._call(
                model=model.strip(),
                user=user,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise classify_error(exc) from exc


class OpenAICompatibleAdapter(ChatAdapter):
    """OpenAI, DeepSeek, Qwen DashScope, Ollama (`/v1`)."""

    def _create_client(self) -> Any:
        from openai import OpenAI

        return OpenAI(**self._client_kwargs(self.api_key.strip() or "ollama"))

    def _call(self, *, model, user, system, temperature, max_tokens, response_format) -> ChatResponse:
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        options: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.spec.disable_reasoning:
            options["reasoning_effort"] = "none"
            if self.spec.key == "deepseek" or "deepseek" in model.lower():
                options["extra_body"] = {"thinking": {"type": "disabled"}}

        warnings: list[str] = []
        if response_format is None:
            answer = self.client.chat.completions.create(**options)
        else:
            try:
                answer = self.client.chat.completions.create(**options, response_format=response_format)
            except Exception as exc:
                if not is_response_format_unsupported(exc):
                    raise
                warnings.append("Nhà cung cấp không hỗ trợ response_format yêu cầu; đã dùng fallback và kiểm tra chặt JSON.")
                answer = self.client.chat.completions.create(**options)

        usage = getattr(answer, "usage", None)
        choice = answer.choices[0]
        return ChatResponse(
            content=getattr(choice.message, "content", "") or "",
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            finish_reason=getattr(choice, "finish_reason", None),
            warnings=warnings,
        )


class AnthropicAdapter(ChatAdapter):
    """Claude Messages API (không dùng response_format; JSON được kiểm tra sau)."""

    def _create_client(self) -> Any:
        from anthropic import Anthropic

        return Anthropic(**self._client_kwargs(self.api_key))

    def _call(self, *, model, user, system, temperature, max_tokens, response_format) -> ChatResponse:
        options: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            options["system"] = system
        answer = self.client.messages.create(**options)
        blocks = getattr(answer, "content", []) or []
        usage = getattr(answer, "usage", None)
        return ChatResponse(
            content="\n".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text"),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            finish_reason=getattr(answer, "stop_reason", None),
        )


def make_adapter(spec: ProviderSpec, api_key: str, base_url: str, **kwargs: Any) -> ChatAdapter:
    cls = AnthropicAdapter if spec.api_style == API_STYLE_ANTHROPIC else OpenAICompatibleAdapter
    return cls(spec, api_key, base_url, **kwargs)
