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
    """Bản sao đã loại bỏ khóa nhạy cảm trước khi lưu đĩa hoặc xuất file."""
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if str(key).lower() in SECRET_KEYS or key == "_storage_revision":
                continue
            out[key] = scrubbed(value)
        return out
    if isinstance(obj, list):
        return [scrubbed(x) for x in obj]
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

