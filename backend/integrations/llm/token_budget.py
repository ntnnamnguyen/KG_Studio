"""Ngân sách token: gợi ý giới hạn theo mô hình, cắt đoạn theo token đầu vào, kẹp token đầu ra theo trần API."""
from __future__ import annotations

from dataclasses import dataclass

from shared.config_loader import CONFIG

from .providers import provider_key

# Ước lượng thô cho tiếng Việt: ~3.2 ký tự / token
CHARS_PER_TOKEN = 3.2
PROMPT_OVERHEAD_TOKENS = 150
MIN_CHUNK_TOKENS = 256
MIN_OUTPUT_TOKENS = 256


@dataclass(frozen=True)
class TokenProfile:
    max_input_tokens: int
    max_output_tokens: int
    recommended_chunk_size: int
    api_max_output_cap: int


# Hồ sơ theo họ mô hình. Thứ tự quan trọng: mục đầu tiên khớp sẽ được dùng.
_DEEPSEEK_FLASH = TokenProfile(64000, 16384, 4800, 65536)  # DeepSeek V4.1/Flash: Context 1M, output mở rộng lên tới 64K+
_DEEPSEEK_REASONER = TokenProfile(16000, 8192, 4800, 16384)
_DEEPSEEK_CHAT = TokenProfile(12000, 8192, 2400, 16384)  # DeepSeek V3: API hỗ trợ output 8K-16K
_OPENAI = TokenProfile(16000, 8192, 4800, 16384)
_ANTHROPIC = TokenProfile(16000, 8192, 4800, 8192)
_QWEN = TokenProfile(12000, 8192, 4200, 8192)
_OLLAMA = TokenProfile(4096, 4096, 3200, 8192)


def _match_profile(pkey: str, model_low: str) -> TokenProfile | None:
    if pkey == "deepseek" or "deepseek" in model_low:
        if "flash" in model_low:
            return _DEEPSEEK_FLASH
        if "reasoner" in model_low or "r1" in model_low:
            return _DEEPSEEK_REASONER
        return _DEEPSEEK_CHAT
    if pkey == "openai" or any(t in model_low for t in ("gpt-4", "o1", "o3")):
        return _OPENAI
    if pkey == "anthropic" or "claude" in model_low:
        return _ANTHROPIC
    if pkey == "qwen" or ("qwen" in model_low and pkey != "ollama"):
        return _QWEN
    if pkey == "ollama":
        return _OLLAMA
    return None


def _config_profile(pkey: str) -> TokenProfile:
    """Hồ sơ dự phòng lấy từ config/default.toml khi không nhận diện được mô hình."""
    llm_cfg = CONFIG.get("llm", {})
    prov_cfg = llm_cfg.get("providers", {}).get(pkey, {})
    return TokenProfile(
        max_input_tokens=int(prov_cfg.get("max_input_tokens") or llm_cfg.get("max_input_tokens", 12000)),
        max_output_tokens=int(prov_cfg.get("max_tokens") or llm_cfg.get("max_tokens", 8192)),
        recommended_chunk_size=int(
            prov_cfg.get("recommended_chunk_size") or CONFIG.get("extraction", {}).get("chunk_size", 4800)
        ),
        api_max_output_cap=65536,
    )


def recommend_token_limits(provider: str, model: str = "") -> dict[str, int]:
    """Gợi ý token đầu vào, đầu ra và kích thước đoạn tối ưu theo Provider & Model ID."""
    pkey = provider_key(provider)
    profile = _match_profile(pkey, (model or "").strip().lower()) or _config_profile(pkey)
    return {
        "max_input_tokens": profile.max_input_tokens,
        "max_output_tokens": min(profile.max_output_tokens, profile.api_max_output_cap),
        "recommended_chunk_size": profile.recommended_chunk_size,
        "api_max_output_cap": profile.api_max_output_cap,
    }


def fit_chunk_to_input_budget(chunk: str, system_prompt: str, max_input_tokens: int) -> tuple[str, str | None]:
    """Cắt đoạn văn để (prompt + đoạn) nằm trong `max_input_tokens`. Trả về (đoạn, cảnh báo | None)."""
    if not max_input_tokens or int(max_input_tokens) <= 0:
        return chunk, None
    overhead = int(len(system_prompt or "") / CHARS_PER_TOKEN) + PROMPT_OVERHEAD_TOKENS
    available = max(MIN_CHUNK_TOKENS, int(max_input_tokens) - overhead)
    max_chars = int(available * CHARS_PER_TOKEN)
    if len(chunk) <= max_chars:
        return chunk, None
    return chunk[:max_chars], (
        f"Đoạn văn bản vượt ngân sách token đầu vào ({max_input_tokens} tokens); đã giới hạn ở {max_chars} ký tự."
    )


def clamp_output_tokens(provider: str, model: str, max_tokens: int) -> tuple[int, str | None]:
    """Kẹp `max_tokens` về trần API của mô hình (vd. deepseek-chat = 8192). Trả về (giá trị, cảnh báo | None)."""
    limits = recommend_token_limits(provider, model)
    cap = limits["api_max_output_cap"]
    value = max(MIN_OUTPUT_TOKENS, int(max_tokens or limits["max_output_tokens"]))
    if value <= cap:
        return value, None
    return cap, f"Đã tự động giới hạn token đầu ra từ {value} về mức trần {cap} của mô hình '{model.strip()}'."

