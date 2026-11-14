"""Hàm chuẩn hóa văn bản tiếng Việt, tách từ, sinh ID/hash dùng chung giữa lúc Train và lúc Serve."""
from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import SECRET_KEYS

_WORD_RE = re.compile(r"[0-9a-zA-ZÀ-ỹ_]+", re.UNICODE)


def now_iso() -> str:
    """Thời điểm hiện tại dạng ISO-8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    """ID nội bộ ngắn 14 ký tự hex."""
    return uuid.uuid4().hex[:14]


def normal(value: str) -> str:
    """Chuẩn hóa chuỗi tiếng Việt: NFC, gộp khoảng trắng, chữ thường."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(value or "")).strip()).casefold()


def sha(value: str | bytes) -> str:
    """SHA-256 hex xác định cho chuỗi UTF-8 hoặc bytes."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def slug(value: str) -> str:
    """Slug ASCII dùng làm tên thư mục dự án."""
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower()
    return value[:60] or "du_an"


def safe_filename(name: str, max_chars: int = 200) -> str:
    """Làm sạch tên tệp upload."""
    base = Path(str(name).replace("\\", "/")).name
    base = "".join(ch for ch in base if ch >= " " and ch != "\x7f").strip()
    base = base[:max_chars]
    return base or "tai_lieu"


def scrubbed(obj: Any) -> Any:
    """Bản sao đã loại bỏ khóa nhạy cảm trước khi lưu đĩa hoặc xuất file (copy-on-change tránh cấp phát thừa)."""
    if isinstance(obj, dict):
        changed = False
        out: dict[Any, Any] = {}
        for key, value in obj.items():
            if (isinstance(key, str) and (key == "_storage_revision" or key.lower() in SECRET_KEYS)) or (
                not isinstance(key, str) and str(key).lower() in SECRET_KEYS
            ):
                changed = True
                continue
            new_val = scrubbed(value)
            if new_val is not value:
                changed = True
            out[key] = new_val
        return out if changed else obj
    if isinstance(obj, list):
        changed = False
        out_list: list[Any] = []
        for x in obj:
            nx = scrubbed(x)
            if nx is not x:
                changed = True
            out_list.append(nx)
        return out_list if changed else obj
    return obj


def tokenize_vn(text: str, *, include_bigrams: bool = True) -> list[str]:
    """Tách từ đơn và từ ghép đôi (word bigrams) cho tiếng Việt."""
    cleaned = normal(text)
    if not cleaned:
        return []
    words = _WORD_RE.findall(cleaned)
    if not include_bigrams or len(words) < 2:
        return words
    bigrams = [f"{words[i]}_{words[i + 1]}" for i in range(len(words) - 1)]
    return words + bigrams


def clean_relation_name(raw_rel: str) -> str:
    """Chuẩn hóa tên quan hệ: bỏ snake_case (_/ -), gộp khoảng trắng, chuyển chữ thường tiếng Việt,
    và lược bỏ các từ nối / giới từ rườm rà ở cuối (của, về, là, cho).
    Ví dụ:
        'cần_sự_đồng_ý_của' -> 'cần sự đồng ý'
        'dự_kiến_ban_đầu_là' -> 'dự kiến ban đầu'
        'giảm giá cho' -> 'giảm giá'
        'giới_thiệu_về' -> 'giới thiệu'
        'có_tầng_2_diện_tích' -> 'có tầng 2 diện tích'
    """
    if not raw_rel:
        return ""
    text = re.sub(r"[_\-]+", " ", str(raw_rel)).strip()
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).casefold()

    protected = {"thuộc về", "trở về", "quay về", "hướng về"}
    if text in protected:
        return text

    for p in (" của", " về", " là", " cho"):
        if text.endswith(p):
            stem = text[: -len(p)].strip()
            if stem and stem not in ("là", "của", "về", "cho"):
                text = stem
                break
    return text


def clean_entity_type_name(raw_type: str) -> str:
    """Chuẩn hóa tên loại thực thể: thay thế _ và - bằng khoảng trắng, NFC, casefold.
    Ví dụ: 'E21_Person' -> 'e21 person', 'E53-Place' -> 'e53 place'.
    """
    if not raw_type:
        return ""
    text = re.sub(r"[_\-]+", " ", str(raw_type)).strip()
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).casefold()



