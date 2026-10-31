"""Xử lý danh mục (Catalog v2) và hợp đồng JSON EDC hoàn toàn độc lập."""
from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path

from .constants import DEFAULT_EDC_PROMPT

CATALOG_KEYS = ("relations", "entity_types")
CATALOG_FILES = {key: f"{key}.json" for key in CATALOG_KEYS}
CATALOG_VERSION = 2
CATALOG_FIELDS = ("name", "description", "definition")


def _array_spec(fields: tuple[str, ...]) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {f: {"type": "string"} for f in fields},
            "required": list(fields),
            "additionalProperties": False,
        },
    }


EDC_SCHEMA = {
    "type": "object",
    "properties": {
        "thuc_the": _array_spec(("ten", "loai", "mo_ta")),
        "quan_he": _array_spec(("nguon", "quan_he", "dich", "trich_dan")),
        "dinh_nghia_quan_he": _array_spec(("ten", "dinh_nghia")),
        "dinh_nghia_loai": _array_spec(("ten", "dinh_nghia")),
    },
    "required": ["thuc_the", "quan_he", "dinh_nghia_quan_he", "dinh_nghia_loai"],
    "additionalProperties": False,
}


def edc_prompt(instructions: str = DEFAULT_EDC_PROMPT) -> str:
    example = {
        "thuc_the": [{"ten": "tên trong nguồn", "loai": "loại đề xuất", "mo_ta": "mô tả ngắn"}],
        "quan_he": [{"nguon": "tên nguồn", "quan_he": "tên quan hệ", "dich": "tên đích", "trich_dan": "nguyên văn"}],
        "dinh_nghia_quan_he": [{"ten": "tên quan hệ", "dinh_nghia": "ý nghĩa và chiều từ nguồn đến đích"}],
        "dinh_nghia_loai": [{"ten": "loại đề xuất", "dinh_nghia": "ý nghĩa loại"}],
    }
    return (
        instructions.strip()
        + "\n\nCấu trúc bắt buộc (bốn trường đều là mảng, không dùng null/object thay mảng):\n"
        + json.dumps(example, ensure_ascii=False)
    )


def validate_edc_payload(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != set(EDC_SCHEMA["required"]):
        raise ValueError("EDC cần đúng bốn trường: thuc_the, quan_he, dinh_nghia_quan_he, dinh_nghia_loai.")
    for key, spec in EDC_SCHEMA["properties"].items():
        if not isinstance(data[key], list):
            raise ValueError(f"{key} phải là danh sách (mảng JSON), kể cả khi rỗng.")
        fields = set(spec["items"]["required"])
        for index, item in enumerate(data[key], 1):
            if not isinstance(item, dict) or set(item) != fields:
                raise ValueError(f"{key}[{index}] cần đúng các trường: {', '.join(sorted(fields))}.")
            if any(not isinstance(value, str) for value in item.values()):
                raise ValueError(f"Các trường của {key}[{index}] phải là chuỗi.")
    return data


def validate_catalog(rows: object, key: str, allow_empty: bool = True) -> list[dict]:
    """Chuẩn hóa danh mục theo lược đồ v2 (`name`, `description`, `definition`)."""
    if key not in CATALOG_KEYS:
        raise ValueError(f"Danh mục không được hỗ trợ: {key}")
    if not isinstance(rows, list):
        raise ValueError(f"{key}: danh mục phải là danh sách.")
    if not rows:
        if allow_empty:
            return []
        raise ValueError(f"{key}: danh mục phải là danh sách không rỗng.")
    result, seen = [], set()
    for index, row in enumerate(rows, 1):
        if isinstance(row, str):
            row = {"name": row}
        if not isinstance(row, dict):
            raise ValueError(f"{key}: mục {index} phải là chuỗi tên hoặc JSON object có name.")
        extra = set(row) - {*CATALOG_FIELDS, "example"}
        if extra:
            raise ValueError(f"{key}: mục {index} có trường không hỗ trợ: {', '.join(sorted(extra))}")
        item = {}
        for field in (*CATALOG_FIELDS, "example"):
            value = row.get(field, "")
            if not isinstance(value, str):
                raise ValueError(f"{key}: {field} tại mục {index} phải là chuỗi.")
            item[field] = value.strip()
        if "definition" not in row:
            item["definition"] = item["description"]
        example = item.pop("example")
        if example:
            item["description"] = "\n".join(filter(None, (item["description"], "Ví dụ: " + example)))
        if not item["name"]:
            raise ValueError(f"{key}: tên tại mục {index} không được rỗng.")
        normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFC", item["name"])).casefold()
        if normalized in seen:
            raise ValueError(f"{key}: tên bị trùng: {item['name']}")
        seen.add(normalized)
        result.append(item)
    return result


def catalog_bytes(rows: list[dict], key: str) -> bytes:
    data = {"schema_version": CATALOG_VERSION, key: validate_catalog(rows, key, allow_empty=True)}
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def parse_catalog(data: bytes | str, key: str) -> list[dict]:
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data.lstrip("\ufeff")
    payload = json.loads(text)
    if isinstance(payload, list):
        return validate_catalog(payload, key, allow_empty=True)
    if isinstance(payload, dict):
        if key in payload and isinstance(payload[key], list):
            return validate_catalog(payload[key], key, allow_empty=True)
        for alias in ("data", "items", "rows", "relation_types" if key == "relations" else "entities"):
            if alias in payload and isinstance(payload[alias], list):
                return validate_catalog(payload[alias], key, allow_empty=True)
    raise ValueError(f"{key}: file JSON cần chứa danh sách {key} hoặc danh sách đối tượng có trường 'name'.")


def read_catalog(path: Path, key: str) -> list[dict]:
    return parse_catalog(path.read_bytes(), key)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_catalog(path: Path, rows: list[dict], key: str) -> None:
    data = catalog_bytes(rows, key)
    if path.exists() and path.read_bytes() == data:
        return
    atomic_write(path, data)


def relation_catalog(project: dict) -> list[dict]:
    notes = project.get("relation_notes", {})
    raw = [dict(notes.get(name, {}), name=name) for name in project.get("relations", [])]
    return validate_catalog(raw, "relations", allow_empty=True)


def apply_relations(project: dict, rows: list[dict]) -> None:
    rows = validate_catalog(rows, "relations", allow_empty=True)
    project["relations"] = [row["name"] for row in rows]
    project["relation_notes"] = {
        row["name"]: {"description": row["description"], "definition": row["definition"]}
        for row in rows
    }

