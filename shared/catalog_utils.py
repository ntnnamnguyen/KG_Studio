"""Xử lý danh mục (Catalog v2) và hợp đồng JSON EDC hoàn toàn độc lập."""
from __future__ import annotations

import csv
import io
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
        extra = set(row) - {*CATALOG_FIELDS, "example", "aliases"}
        if extra:
            raise ValueError(f"{key}: mục {index} có trường không hỗ trợ: {', '.join(sorted(extra))}")
        item = {}
        for field in (*CATALOG_FIELDS, "example"):
            value = row.get(field, "")
            if not isinstance(value, str):
                raise ValueError(f"{key}: {field} tại mục {index} phải là chuỗi.")
            item[field] = value.strip()
        if "aliases" in row:
            raw_aliases = row["aliases"]
            if isinstance(raw_aliases, str):
                item["aliases"] = [a.strip() for a in raw_aliases.split(",") if a.strip()]
            elif isinstance(raw_aliases, (list, tuple, set)):
                item["aliases"] = [str(a).strip() for a in raw_aliases if str(a).strip()]
            else:
                item["aliases"] = []
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


def catalog_csv_bytes(rows: list[dict], key: str) -> bytes:
    """Xuất danh mục thực thể hoặc quan hệ ra định dạng CSV với UTF-8 BOM cho Excel."""
    valid_rows = validate_catalog(rows, key, allow_empty=True)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "description", "definition"])
    for r in valid_rows:
        writer.writerow([r.get("name", ""), r.get("description", ""), r.get("definition", "")])
    return output.getvalue().encode("utf-8-sig")


_CATALOG_FIELD_CANDIDATES = {
    "name": ("name", "tên", "ten", "loại", "loai", "quan hệ", "quan_he", "quanhe", "type", "relation", "entity_type", "label"),
    "description": ("description", "mô tả", "mo_ta", "mota", "desc", "ghi chú", "ghi_chu"),
    "definition": ("definition", "định nghĩa", "dinh_nghia", "dinhnghia", "def", "phạm vi", "pham_vi"),
    "example": ("example", "ví dụ", "vi_du", "vidu"),
    "aliases": ("aliases", "bí danh", "bi_danh", "alias"),
}


def _parse_csv_catalog(text: str, key: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text))
    raw_rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not raw_rows:
        return []

    first_row = [c.strip().lower() for c in raw_rows[0]]
    name_candidates = set(_CATALOG_FIELD_CANDIDATES["name"])
    has_name_header = any(col in name_candidates for col in first_row)

    records: list[dict[str, str]] = []
    if has_name_header:
        dict_reader = csv.DictReader(io.StringIO(text))
        for row in dict_reader:
            entry: dict[str, str] = {}
            for target_field, candidates in _CATALOG_FIELD_CANDIDATES.items():
                for col_name, val in row.items():
                    if col_name and col_name.strip().lower() in candidates:
                        if val is not None and str(val).strip():
                            entry[target_field] = str(val).strip()
                            break
            if entry.get("name"):
                records.append(entry)
    else:
        for row in raw_rows:
            if not row or not row[0].strip():
                continue
            entry = {"name": row[0].strip()}
            if len(row) > 1 and row[1].strip():
                entry["description"] = row[1].strip()
            if len(row) > 2 and row[2].strip():
                entry["definition"] = row[2].strip()
            records.append(entry)
    return validate_catalog(records, key, allow_empty=True)


def decode_text_bytes(data: bytes | str) -> str:
    """Giải mã an toàn chuỗi byte tệp tải lên (CSV/JSON/TXT) tự động thích ứng với
    UTF-8, UTF-16, và CP1258 (Mã ANSI tiếng Việt mặc định của Excel Windows)."""
    if isinstance(data, str):
        return unicodedata.normalize("NFC", data.lstrip("\ufeff"))
    if not data:
        return ""

    # 1. Thử UTF-8 / UTF-8-BOM chuẩn
    try:
        return unicodedata.normalize("NFC", data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        pass

    # 2. Thử UTF-16 (Excel Unicode Text)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return unicodedata.normalize("NFC", data.decode("utf-16"))
        except UnicodeDecodeError:
            pass

    # 3. Thử CP1258 (Mã Windows-1258 tiếng Việt mặc định của Excel Windows tại VN)
    try:
        decoded = data.decode("cp1258")
        return unicodedata.normalize("NFC", decoded)
    except UnicodeDecodeError:
        pass

    # 4. Thử CP1252 / ISO-8859-1
    try:
        decoded = data.decode("cp1252")
        return unicodedata.normalize("NFC", decoded)
    except UnicodeDecodeError:
        pass

    # 5. Fallback an toàn với replace để không crash
    return unicodedata.normalize("NFC", data.decode("utf-8-sig", errors="replace"))


def parse_catalog(data: bytes | str, key: str, filename: str = "") -> list[dict]:
    text = decode_text_bytes(data).strip()
    if not text:
        return []

    lower_name = str(filename or "").lower()
    prefer_csv = lower_name.endswith(".csv")

    if not prefer_csv and (text.startswith("{") or text.startswith("[")):
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                return validate_catalog(payload, key, allow_empty=True)
            if isinstance(payload, dict):
                if key in payload and isinstance(payload[key], list):
                    return validate_catalog(payload[key], key, allow_empty=True)
                for alias in ("data", "items", "rows", "relation_types" if key == "relations" else "entities"):
                    if alias in payload and isinstance(payload[alias], list):
                        return validate_catalog(payload[alias], key, allow_empty=True)
        except json.JSONDecodeError:
            if not prefer_csv:
                raise

    return _parse_csv_catalog(text, key)


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
    aliases_map = project.get("relation_aliases", {})
    type_rows = {
        r.get("name"): r.get("aliases", [])
        for r in project.get("relation_types", [])
        if isinstance(r, dict) and r.get("name")
    }
    raw = []
    for name in project.get("relations", []):
        entry = dict(notes.get(name, {}), name=name)
        if "aliases" not in entry:
            cand_aliases = aliases_map.get(name) or type_rows.get(name)
            if cand_aliases:
                entry["aliases"] = list(cand_aliases)
        raw.append(entry)
    return validate_catalog(raw, "relations", allow_empty=True)


def apply_relations(project: dict, rows: list[dict]) -> None:
    rows = validate_catalog(rows, "relations", allow_empty=True)
    project["relations"] = [row["name"] for row in rows]
    project["relation_notes"] = {
        row["name"]: {
            "description": row["description"],
            "definition": row["definition"],
            "aliases": row.get("aliases", []),
        }
        for row in rows
    }

