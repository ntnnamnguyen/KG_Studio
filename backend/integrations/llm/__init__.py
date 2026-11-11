"""Gói tích hợp LLM.

Cấu trúc:
- ``providers.py``    : danh mục nhà cung cấp, model/base URL mặc định.
- ``errors.py``       : ``LLMError`` và phân loại lỗi SDK.
- ``token_budget.py`` : gợi ý giới hạn token theo mô hình, cắt đoạn đầu vào, kẹp token đầu ra.
- ``parsing.py``      : dựng user message, parse JSON trích xuất, đọc chữ cái lựa chọn.
- ``clients.py``      : adapter chat cho OpenAI-compatible và Anthropic.
- ``gateway.py``      : facade ``LLMGateway`` (API công khai).
"""
from __future__ import annotations

from .clients import ChatAdapter, ChatResponse, make_adapter
from .errors import LLMError, classify_error
from .gateway import ExtractionResult, LLMGateway
from .parsing import build_user_message, clean_llm_json
from .providers import (
    API_STYLE_ANTHROPIC,
    API_STYLE_OPENAI,
    DEFAULT_MODELS,
    DEFAULT_PROVIDER,
    PROVIDER_ANTHROPIC,
    PROVIDER_DEEPSEEK,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_QWEN,
    PROVIDER_SPECS,
    PROVIDERS,
    ProviderSpec,
)
from .token_budget import recommend_token_limits

__all__ = [
    "API_STYLE_ANTHROPIC",
    "API_STYLE_OPENAI",
    "DEFAULT_MODELS",
    "DEFAULT_PROVIDER",
    "ExtractionResult",
    "LLMError",
    "LLMGateway",
    "PROVIDERS",
    "PROVIDER_ANTHROPIC",
    "PROVIDER_DEEPSEEK",
    "PROVIDER_OLLAMA",
    "PROVIDER_OPENAI",
    "PROVIDER_QWEN",
    "PROVIDER_SPECS",
    "ProviderSpec",
    "build_user_message",
    "classify_error",
    "clean_llm_json",
    "recommend_token_limits",
]

