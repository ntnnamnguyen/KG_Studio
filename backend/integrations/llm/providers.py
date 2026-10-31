"""Danh mục nhà cung cấp LLM: tên hiển thị, kiểu API, model/base URL mặc định (đọc từ config/default.toml)."""
from __future__ import annotations

from dataclasses import dataclass

from shared.config_loader import CONFIG

PROVIDER_OPENAI = "OpenAI / API tương thích"
PROVIDER_ANTHROPIC = "Claude (Anthropic)"
PROVIDER_QWEN = "Qwen (Alibaba DashScope)"
PROVIDER_DEEPSEEK = "DeepSeek"
PROVIDER_OLLAMA = "Ollama (Local)"

API_STYLE_OPENAI = "openai"
API_STYLE_ANTHROPIC = "anthropic"


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key: str  # Khóa cấu hình trong [llm.providers.<key>]
    api_style: str
    default_model: str = ""
    default_base_url: str = ""
    env_key: str = ""
    env_base_url: str = ""
    allow_custom_base_url: bool = True
    supports_json_mode: bool = True
    hint: str = ""
    requires_api_key: bool = True
    disable_reasoning: bool = False  # Ollama: tắt thinking khi cần JSON


def _provider_cfg(key: str) -> dict:
    return CONFIG.get("llm", {}).get("providers", {}).get(key, {})


def _spec(name: str, key: str, api_style: str, env_prefix: str, hint: str, **extra) -> ProviderSpec:
    cfg = _provider_cfg(key)
    return ProviderSpec(
        name=name,
        key=key,
        api_style=api_style,
        default_model=str(cfg.get("model", "")),
        default_base_url=str(cfg.get("base_url", "")),
        env_key=f"{env_prefix}_API_KEY",
        env_base_url=f"{env_prefix}_BASE_URL",
        hint=hint,
        **extra,
    )


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    PROVIDER_OPENAI: _spec(
        PROVIDER_OPENAI, "openai", API_STYLE_OPENAI, "OPENAI",
        "Dùng cho OpenAI hoặc dịch vụ tương thích OpenAI.",
    ),
    PROVIDER_ANTHROPIC: _spec(
        PROVIDER_ANTHROPIC, "anthropic", API_STYLE_ANTHROPIC, "ANTHROPIC",
        "Claude Sonnet / Haiku của Anthropic.",
    ),
    PROVIDER_QWEN: _spec(
        PROVIDER_QWEN, "qwen", API_STYLE_OPENAI, "DASHSCOPE",
        "Alibaba Cloud DashScope compatible-mode.",
    ),
    PROVIDER_DEEPSEEK: _spec(
        PROVIDER_DEEPSEEK, "deepseek", API_STYLE_OPENAI, "DEEPSEEK",
        "DeepSeek API (tự động tắt thinking mode khi trích xuất JSON để tối đa hóa token đầu ra).",
        disable_reasoning=True,
    ),
    PROVIDER_OLLAMA: _spec(
        PROVIDER_OLLAMA, "ollama", API_STYLE_OPENAI, "OLLAMA",
        "Ollama local không cần API key; tự động tắt thinking khi trích xuất JSON.",
        requires_api_key=False,
        disable_reasoning=True,
    ),
}

PROVIDERS: list[str] = list(PROVIDER_SPECS)
_BY_KEY: dict[str, str] = {spec.key: name for name, spec in PROVIDER_SPECS.items()}

DEFAULT_PROVIDER: str = _BY_KEY.get(str(CONFIG.get("llm", {}).get("default_provider", "ollama")), PROVIDER_OLLAMA)
DEFAULT_MODELS: dict[str, str] = {name: spec.default_model for name, spec in PROVIDER_SPECS.items()}


def provider_spec(provider: str) -> ProviderSpec:
    """Trả về đặc tả nhà cung cấp; chấp nhận cả tên hiển thị hoặc key rút gọn."""
    if provider in PROVIDER_SPECS:
        return PROVIDER_SPECS[provider]
    if provider in _BY_KEY:
        return PROVIDER_SPECS[_BY_KEY[provider]]
    low = str(provider or "").strip().lower()
    if low in _BY_KEY:
        return PROVIDER_SPECS[_BY_KEY[low]]
    return PROVIDER_SPECS[PROVIDER_OPENAI]


def provider_key(provider: str) -> str:
    """Tên hiển thị hoặc key -> khóa cấu hình (`openai`, `deepseek`, ...)."""
    if provider in _BY_KEY:
        return provider
    spec = PROVIDER_SPECS.get(provider)
    if spec:
        return spec.key
    low = str(provider or "").strip().lower()
    if low in _BY_KEY:
        return low
    return "deepseek"


def resolve_base_url(provider: str, base_url: str = "") -> str:
    cleaned = (base_url or "").strip()
    url = cleaned or provider_spec(provider).default_base_url
    # Chuẩn hóa nếu người dùng nhập trực tiếp cả endpoint /chat/completions
    if url.endswith("/chat/completions"):
        url = url[:-len("/chat/completions")].rstrip("/")
    elif url.endswith("/chat/completions/"):
        url = url[:-len("/chat/completions/")].rstrip("/")
    return url

