"""Đọc cấu hình tập trung từ ``config/default.toml`` hoàn toàn độc lập."""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from .catalog_utils import atomic_write, read_catalog, validate_catalog

APP_ROOT = Path(__file__).resolve().parent.parent


def resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (APP_ROOT / path).resolve()


def load_config(path: str | Path | None = None) -> dict:
    selected = path or os.getenv("KG_STUDIO_CONFIG") or (APP_ROOT / "config" / "default.toml")
    config_path = resolve_path(selected)
    config = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    knowledge = config.setdefault("knowledge", {})
    for key in ("relations", "entity_types"):
        file_key = f"{key}_file"
        file_val = str(knowledge.get(file_key, "")).strip()
        if file_val:
            cat_path = resolve_path(file_val)
            if cat_path.exists():
                knowledge[key] = read_catalog(cat_path, key)
            else:
                knowledge[key] = []
        elif key in knowledge and isinstance(knowledge[key], list):
            knowledge[key] = validate_catalog(knowledge[key], key, allow_empty=True)
        else:
            knowledge[key] = []
    return config


CONFIG_PATH = resolve_path(os.getenv("KG_STUDIO_CONFIG") or (APP_ROOT / "config" / "default.toml"))
CONFIG = load_config(CONFIG_PATH)


def projects_root() -> Path:
    override = os.getenv("KG_STUDIO_PROJECTS_DIR", "").strip()
    return resolve_path(override or CONFIG["storage"]["projects_dir"])


def default_catalogs() -> dict:
    return {"relations": [], "entity_types": []}


def _upsert_toml_key_in_section(content: str, section_header: str, key: str, value_literal: str) -> str:
    """Cập nhật hoặc chèn thêm cặp key = value trong đúng khối [section] của file TOML mà giữ nguyên mọi chú thích."""
    sec_pattern = re.compile(rf"(?m)^\[{re.escape(section_header)}\]\s*$")
    match = sec_pattern.search(content)
    if not match:
        suffix = "" if content.endswith("\n") else "\n"
        return f"{content}{suffix}\n[{section_header}]\n{key} = {value_literal}\n"

    start = match.end()
    next_sec = re.search(r"(?m)^\[[^\]]+\]\s*$", content[start:])
    end = start + next_sec.start() if next_sec else len(content)
    block = content[start:end]

    key_pattern = re.compile(rf"(?m)^(\s*{re.escape(key)}\s*=\s*)([^\r\n#]+)(.*)$")
    if key_pattern.search(block):
        new_block = key_pattern.sub(
            lambda m: f"{m.group(1)}{value_literal}{m.group(3)}",
            block,
            count=1,
        )
    else:
        insert_line = f"{key} = {value_literal}\n"
        if block.startswith("\r\n"):
            new_block = "\r\n" + insert_line + block[2:]
        elif block.startswith("\n"):
            new_block = "\n" + insert_line + block[1:]
        else:
            new_block = "\n" + insert_line + block
    return content[:start] + new_block + content[end:]


def save_llm_token_config_to_toml(
    *,
    provider_key: str,
    model: str,
    base_url: str,
    max_input_tokens: int,
    max_output_tokens: int,
    chunk_size: int | None = None,
    path: str | Path | None = None,
) -> Path:
    """Lưu cấu hình token đầu vào, đầu ra, model và chunk_size vào config/default.toml rồi nạp lại CONFIG."""
    target_path = resolve_path(path or CONFIG_PATH)
    raw = target_path.read_text(encoding="utf-8-sig")

    prov_clean = (provider_key or "deepseek").strip().lower()
    in_tok = max(512, int(max_input_tokens))
    out_tok = max(256, int(max_output_tokens))
    eff_chunk = max(500, int(chunk_size)) if chunk_size is not None else int(CONFIG.get("extraction", {}).get("chunk_size", 4800))

    raw = _upsert_toml_key_in_section(raw, "llm", "default_provider", f'"{prov_clean}"')
    raw = _upsert_toml_key_in_section(raw, "llm", "max_input_tokens", str(in_tok))
    raw = _upsert_toml_key_in_section(raw, "llm", "max_tokens", str(out_tok))

    prov_section = f"llm.providers.{prov_clean}"
    escaped_model = str(model or "").replace("\\", "\\\\").replace('"', '\\"')
    escaped_url = str(base_url or "").replace("\\", "\\\\").replace('"', '\\"')
    raw = _upsert_toml_key_in_section(raw, prov_section, "model", f'"{escaped_model}"')
    raw = _upsert_toml_key_in_section(raw, prov_section, "base_url", f'"{escaped_url}"')
    raw = _upsert_toml_key_in_section(raw, prov_section, "max_input_tokens", str(in_tok))
    raw = _upsert_toml_key_in_section(raw, prov_section, "max_tokens", str(out_tok))
    raw = _upsert_toml_key_in_section(raw, prov_section, "recommended_chunk_size", str(eff_chunk))

    if chunk_size is not None:
        raw = _upsert_toml_key_in_section(raw, "extraction", "chunk_size", str(eff_chunk))

    # Kiểm tra cú pháp TOML hợp lệ trước khi ghi đĩa nguyên tử
    tomllib.loads(raw)
    atomic_write(target_path, raw.encode("utf-8"))

    fresh = load_config(target_path)
    CONFIG.clear()
    CONFIG.update(fresh)
    return target_path


