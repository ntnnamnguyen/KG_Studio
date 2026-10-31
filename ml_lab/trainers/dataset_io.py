"""Tiện ích đọc ghi dữ liệu huấn luyện ML Lab."""
from __future__ import annotations

import json
from pathlib import Path


def load_jsonl(path: str | Path) -> list[dict]:
    """Đọc tệp JSONL thành danh sách dict; trả về rỗng nếu tệp không tồn tại."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    rows: list[dict] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows

