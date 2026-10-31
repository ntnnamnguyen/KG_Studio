"""Kiểu lỗi LLM thống nhất và hàm phân loại lỗi từ SDK của các nhà cung cấp."""
from __future__ import annotations


class LLMError(RuntimeError):
    """Lỗi gọi LLM, kèm loại lỗi (`kind`) và số token đã tiêu tốn (nếu có) để ghi log."""

    def __init__(
        self,
        message: str,
        kind: str = "api",
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        raw: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.raw = raw


_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("auth", "API key không hợp lệ", ("invalid api key", "authentication", "401", "unauthorized")),
    ("rate_limit", "Bị giới hạn tần suất (429)", ("429", "rate limit", "quota")),
    ("timeout", "Hết thời gian chờ API", ("timeout", "timed out")),
)


def classify_error(exc: Exception) -> LLMError:
    """Chuyển exception của SDK (openai/anthropic/httpx) thành `LLMError` có `kind` rõ ràng."""
    text = str(exc)
    low = text.lower()
    if "model" in low and any(t in low for t in ("not found", "does not exist", "404")):
        return LLMError(f"Không tìm thấy mã mô hình: {text}", "model")
    for kind, label, tokens in _RULES:
        if any(t in low for t in tokens):
            return LLMError(f"{label}: {text}", kind)
    return LLMError(f"Lỗi API: {text}", "api")


def is_response_format_unsupported(exc: Exception) -> bool:
    """Nhà cung cấp từ chối tham số `response_format` (json_object/json_schema)."""
    low = str(exc).lower()
    return any(t in low for t in ("response_format", "json_object", "json_schema", "unsupported", "not supported"))

