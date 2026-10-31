"""Quản lý lưu trữ và nạp API key an toàn cho KG Studio.

Thứ tự ưu tiên nạp API Key:
1. Biến môi trường hệ thống (System Environment Variables):
   - DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, DASHSCOPE_API_KEY, QWEN_API_KEY
   - KG_STUDIO_API_KEY, LLM_API_KEY (dùng chung cho mọi nhà cung cấp nếu chưa có key riêng)
2. File .secrets.toml nội bộ người dùng (config/.secrets.toml) - được bảo vệ bởi .gitignore:
   [llm_api_keys]
   deepseek = "sk-..."
   openai = "sk-..."
   anthropic = "sk-..."
   qwen = "sk-..."
3. File .env cục bộ (ở thư mục gốc KG_Studio) nếu có.
4. Streamlit Secrets (st.secrets) nếu có.
"""
from __future__ import annotations

import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from shared.catalog_utils import atomic_write

APP_ROOT = Path(__file__).resolve().parent.parent
SECRETS_SECTION = "llm_api_keys"


def normalize_provider_key(provider: str) -> str:
    """Chuẩn hóa tên hoặc key nhà cung cấp về khóa nhận diện (deepseek, openai, ...)."""
    p = str(provider or "").strip().lower()
    if "deepseek" in p:
        return "deepseek"
    if "openai" in p:
        return "openai"
    if "anthropic" in p or "claude" in p:
        return "anthropic"
    if "qwen" in p or "dashscope" in p:
        return "qwen"
    if "ollama" in p:
        return "ollama"
    return p or "deepseek"


def provider_requires_api_key(provider: str) -> bool:
    """Ollama cục bộ không yêu cầu API key, các nhà cung cấp cloud đều yêu cầu."""
    return normalize_provider_key(provider) != "ollama"


def get_secrets_file_path(custom_path: str | Path | None = None) -> Path:
    """Trả về đường dẫn tuyệt đối của file secrets."""
    if custom_path:
        p = Path(custom_path).expanduser()
        return p.resolve() if p.is_absolute() else (APP_ROOT / p).resolve()
    env_override = os.getenv("KG_STUDIO_SECRETS_FILE", "").strip()
    if env_override:
        p = Path(env_override).expanduser()
        return p.resolve() if p.is_absolute() else (APP_ROOT / p).resolve()
    return (APP_ROOT / "config" / ".secrets.toml").resolve()


def get_provider_env_keys(provider: str) -> list[str]:
    """Trả về danh sách tên biến môi trường tương ứng với nhà cung cấp (theo thứ tự ưu tiên)."""
    pkey = normalize_provider_key(provider)
    primary_env = f"{pkey.upper()}_API_KEY"
    keys = [primary_env]
    if pkey == "qwen":
        keys.extend(["DASHSCOPE_API_KEY", "QWEN_API_KEY"])
    elif pkey == "deepseek":
        keys.append("DEEPSEEK_API_KEY")
    elif pkey == "openai":
        keys.append("OPENAI_API_KEY")
    elif pkey == "anthropic":
        keys.append("ANTHROPIC_API_KEY")

    # Thêm fallback chung
    for fallback in ("KG_STUDIO_API_KEY", "LLM_API_KEY"):
        if fallback not in keys:
            keys.append(fallback)
    return keys


def parse_env_file(path: Path | None = None) -> dict[str, str]:
    """Đọc file .env nếu có mà không cần thư viện ngoài."""
    env_file = path or (APP_ROOT / ".env")
    if not env_file.is_file():
        return {}
    res: dict[str, str] = {}
    try:
        content = env_file.read_text(encoding="utf-8-sig", errors="ignore")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k:
                res[k] = v
    except Exception:
        pass
    return res


def read_secrets_file(path: Path | None = None) -> dict[str, Any]:
    """Đọc dữ liệu từ file secrets.toml."""
    target = path or get_secrets_file_path()
    if not target.is_file():
        return {}
    try:
        raw = target.read_text(encoding="utf-8-sig")
        return tomllib.loads(raw)
    except Exception:
        return {}


def get_api_key(
    provider: str,
    *,
    custom_secrets_path: Path | None = None,
    include_env: bool = True,
    include_secrets_file: bool = True,
    include_streamlit: bool = True,
) -> str:
    """Tra cứu API key theo phân cấp ưu tiên: Biến môi trường -> .secrets.toml -> .env -> st.secrets."""
    if not provider_requires_api_key(provider):
        return ""

    pkey = normalize_provider_key(provider)
    env_keys = get_provider_env_keys(provider)

    # 1. Biến môi trường hệ thống
    if include_env:
        for ek in env_keys:
            val = os.getenv(ek, "").strip()
            if val:
                return val

    # 2. File .secrets.toml
    if include_secrets_file:
        secrets_dict = read_secrets_file(custom_secrets_path)
        keys_section = secrets_dict.get(SECRETS_SECTION, {})
        if isinstance(keys_section, dict):
            val = str(keys_section.get(pkey, "")).strip()
            if val:
                return val

    # 3. File .env
    if include_env:
        env_dict = parse_env_file()
        for ek in env_keys:
            val = env_dict.get(ek, "").strip()
            if val:
                return val

    # 4. Streamlit secrets (nếu đang chạy trong môi trường streamlit)
    if include_streamlit and "streamlit" in sys.modules:
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                # Thử dạng st.secrets["llm_api_keys"]["deepseek"]
                sec_llm = st.secrets.get(SECRETS_SECTION, {})
                if isinstance(sec_llm, dict):
                    val = str(sec_llm.get(pkey, "")).strip()
                    if val:
                        return val
                # Thử dạng st.secrets["DEEPSEEK_API_KEY"]
                for ek in env_keys:
                    val = str(st.secrets.get(ek, "")).strip()
                    if val:
                        return val
        except Exception:
            pass

    return ""


def save_api_key(
    provider: str,
    api_key: str,
    *,
    custom_secrets_path: Path | None = None,
    update_environ: bool = True,
) -> Path:
    """Lưu API key vào file .secrets.toml một cách nguyên tử và đồng bộ biến môi trường."""
    target = custom_secrets_path or get_secrets_file_path()
    pkey = normalize_provider_key(provider)
    clean_val = (api_key or "").strip()

    # Đọc cấu trúc hiện tại nếu có
    current_data = read_secrets_file(target)
    keys_section = current_data.get(SECRETS_SECTION, {})
    if not isinstance(keys_section, dict):
        keys_section = {}

    if clean_val:
        keys_section[pkey] = clean_val
    else:
        keys_section.pop(pkey, None)

    current_data[SECRETS_SECTION] = keys_section

    # Tạo nội dung TOML chuẩn định dạng kèm chú thích bảo mật
    lines = [
        "# KG Studio - Local Secrets Storage (Bảo mật cục bộ)",
        "# File này tự động được .gitignore bỏ qua, tuyệt đối không commit lên Git hay chia sẻ.",
        f"[{SECRETS_SECTION}]",
    ]
    for k, v in sorted(keys_section.items()):
        escaped_v = str(v).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{k} = "{escaped_v}"')
    lines.append("")

    raw_toml = "\n".join(lines)
    # Xác thực cú pháp TOML
    tomllib.loads(raw_toml)

    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, raw_toml.encode("utf-8"))

    # Đặt quyền bảo mật (0o600: chỉ user sở hữu có quyền đọc/ghi) trên hệ thống hỗ trợ
    try:
        os.chmod(target, 0o600)
    except Exception:
        pass

    # Cập nhật biến môi trường cho tiến trình hiện tại
    if update_environ:
        primary_env = get_provider_env_keys(provider)[0]
        if clean_val:
            os.environ[primary_env] = clean_val
        else:
            os.environ.pop(primary_env, None)

    return target


def delete_api_key(
    provider: str,
    *,
    custom_secrets_path: Path | None = None,
    update_environ: bool = True,
) -> bool:
    """Xóa API key của nhà cung cấp khỏi file secrets và tiến trình."""
    target = custom_secrets_path or get_secrets_file_path()
    pkey = normalize_provider_key(provider)
    current_data = read_secrets_file(target)
    keys_section = current_data.get(SECRETS_SECTION, {})
    if isinstance(keys_section, dict) and pkey in keys_section:
        save_api_key(provider, "", custom_secrets_path=target, update_environ=update_environ)
        return True
    if update_environ:
        primary_env = get_provider_env_keys(provider)[0]
        os.environ.pop(primary_env, None)
    return False


def list_saved_providers(custom_secrets_path: Path | None = None) -> dict[str, str]:
    """Trả về từ điển {provider_key: masked_api_key} cho các key đã được lưu trong .secrets.toml."""
    target = custom_secrets_path or get_secrets_file_path()
    current_data = read_secrets_file(target)
    keys_section = current_data.get(SECRETS_SECTION, {})
    if not isinstance(keys_section, dict):
        return {}
    return {k: mask_api_key(str(v)) for k, v in keys_section.items() if str(v).strip()}


def mask_api_key(api_key: str) -> str:
    """Che bớt ký tự API key để hiển thị an toàn trên giao diện."""
    k = (api_key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "*" * len(k)
    return f"{k[:3]}...{k[-4:]}"


def has_persisted_key(provider: str, custom_secrets_path: Path | None = None) -> bool:
    """Kiểm tra xem nhà cung cấp đã có key lưu trữ (trong secrets file, .env hoặc env var) hay chưa."""
    key = get_api_key(provider, custom_secrets_path=custom_secrets_path)
    return bool(key)
