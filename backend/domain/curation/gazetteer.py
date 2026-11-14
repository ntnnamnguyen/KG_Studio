"""Quản lý từ điển bí danh dự án (Project Domain Gazetteer) và cơ chế học phản hồi (Continuous Curation)."""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from shared.catalog_utils import decode_text_bytes
from shared.text_utils import normal, now_iso
from .common import clean_display_text


_GAZETTEER_ALIAS_SPLIT_RE = re.compile(r"[;|]+")

_ALIAS_FIELD_CANDIDATES = ("alias", "bi_danh", "bí danh", "from", "key", "ten_khac", "tên khác", "variant")
_ALIASES_LIST_CANDIDATES = (
    "aliases",
    "bi_danh_nhom",
    "bí danh nhóm",
    "danh_sach_bi_danh",
    "các bí danh",
    "cac_ten_khac",
    "các tên khác",
    "variants",
    "other_names",
)
_CANONICAL_FIELD_CANDIDATES = (
    "canonical_name",
    "canonical",
    "ten_chuan",
    "tên chuẩn",
    "ten_chinh",
    "tên chính",
    "thuc_the_chuan",
    "thực thể chuẩn",
    "to",
    "target",
    "name",
    "chuan_hoa",
)
_KIND_FIELD_CANDIDATES = ("kind", "type", "loai", "loại", "entity_type", "loại thực thể")
_SOURCE_FIELD_CANDIDATES = ("source", "nguồn", "nguon", "nguồn gốc")


def normalize_gazetteer_key(text: str) -> str:
    """Chuẩn hóa khóa tra cứu từ điển bí danh (chữ thường, loại bỏ dấu cách thừa)."""
    return normal(str(text or "")).strip()


def split_gazetteer_aliases(raw: Any) -> list[str]:
    """Tách danh sách bí danh theo ';' hoặc '|' (không tách theo ',' để bảo toàn tên địa danh có dấu phẩy)."""
    if raw is None:
        return []
    raw_items = raw if isinstance(raw, (list, tuple, set)) else [raw]
    aliases: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if item is None:
            continue
        for part in _GAZETTEER_ALIAS_SPLIT_RE.split(str(item)):
            cleaned = clean_display_text(part)
            key = normalize_gazetteer_key(cleaned)
            if cleaned and key and key not in seen:
                seen.add(key)
                aliases.append(cleaned)
    return aliases


def _extract_row_aliases_and_fields(
    item: dict[str, Any],
    fallback_alias: str = "",
) -> tuple[list[str], str, str, str]:
    """Trích xuất (aliases, canonical_name, kind, source) từ một dict bất kỳ theo nhiều quy ước tên cột."""
    lowered = {normal(str(k)): v for k, v in item.items()}

    aliases: list[str] = []
    for cand in (*_ALIASES_LIST_CANDIDATES, *_ALIAS_FIELD_CANDIDATES):
        val = lowered.get(normal(cand))
        if val is not None and (isinstance(val, (list, tuple, set)) or str(val).strip()):
            aliases = split_gazetteer_aliases(val)
            if aliases:
                break
    if not aliases and fallback_alias:
        aliases = split_gazetteer_aliases(fallback_alias)

    canonical = ""
    for cand in _CANONICAL_FIELD_CANDIDATES:
        val = lowered.get(normal(cand))
        if val is not None and str(val).strip():
            canonical = str(val).strip()
            break

    kind = ""
    for cand in _KIND_FIELD_CANDIDATES:
        val = lowered.get(normal(cand))
        if val is not None and str(val).strip():
            kind = str(val).strip()
            break

    source = ""
    if len(aliases) <= 1:
        for cand in _SOURCE_FIELD_CANDIDATES:
            val = lowered.get(normal(cand))
            if val is not None and str(val).strip() and "," not in str(val):
                source = str(val).strip()
                break

    return aliases, clean_display_text(canonical), clean_display_text(kind), source


def _extract_row_fields(item: dict[str, Any], fallback_alias: str = "") -> tuple[str, str, str, str]:
    """Trích xuất (alias, canonical_name, kind, source) từ một dict theo quy ước 1-1."""
    aliases, canonical, kind, source = _extract_row_aliases_and_fields(item, fallback_alias=fallback_alias)
    return (aliases[0] if aliases else ""), canonical, kind, source


def _normalize_entries_collection(raw: Any) -> list[dict[str, str]]:
    """Chuẩn hóa dữ liệu đầu vào (dict phẳng, dict nhóm aliases, hoặc list) thành danh sách bản ghi phẳng."""
    results: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    def _push(alias: str, canon: str, kind: str = "", source: str = "") -> None:
        a_clean = clean_display_text(alias)
        c_clean = clean_display_text(canon)
        k_clean = clean_display_text(kind)
        key = normalize_gazetteer_key(a_clean)
        canon_key = normalize_gazetteer_key(c_clean)
        if not key or not canon_key or key == canon_key or key in seen_keys:
            return
        seen_keys.add(key)
        row: dict[str, str] = {
            "alias": a_clean,
            "canonical_name": c_clean,
            "kind": k_clean,
        }
        if source:
            row["source"] = source
        results.append(row)

    def _push_many(aliases: list[str], canon: str, kind: str = "", source: str = "") -> None:
        for alias in aliases:
            _push(alias, canon, kind, source)

    if isinstance(raw, dict):
        # Hỗ trợ file bọc bởi {"domain_gazetteer": ...} hoặc {"entries": ...}
        if set(raw.keys()) <= {"domain_gazetteer", "entries", "gazetteer"}:
            inner = raw.get("domain_gazetteer") or raw.get("entries") or raw.get("gazetteer")
            if inner is not None:
                return _normalize_entries_collection(inner)

        for raw_k, val in raw.items():
            if isinstance(val, dict):
                aliases, c, k, src = _extract_row_aliases_and_fields(val, fallback_alias=str(raw_k))
                _push_many(aliases, c, k, src)
            elif val is not None:
                _push_many(split_gazetteer_aliases(str(raw_k)), str(val))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                aliases, c, k, src = _extract_row_aliases_and_fields(item)
                _push_many(aliases, c, k, src)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                _push_many(
                    split_gazetteer_aliases(str(item[0])),
                    str(item[1]),
                    str(item[2]) if len(item) >= 3 else "",
                )

    return results


def parse_gazetteer_bytes(raw_bytes: bytes, filename: str = "") -> list[dict[str, str]]:
    """Phân tích tệp JSON hoặc CSV từ điển bí danh (hỗ trợ cả dạng 1-1 lẫn gom nhóm aliases bằng ; hoặc |)."""
    if not raw_bytes:
        return []
    text = decode_text_bytes(raw_bytes).strip()
    if not text:
        return []

    lower_name = str(filename or "").lower()
    prefer_csv = lower_name.endswith(".csv")

    if not prefer_csv and (text.startswith("{") or text.startswith("[")):
        parsed = json.loads(text)
        return _normalize_entries_collection(parsed)

    # Phân tích CSV (hỗ trợ cả có tiêu đề 1-1 / gom nhóm aliases và không có tiêu đề)
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return []

    header = [normal(c) for c in rows[0]]
    alias_headers = {normal(c) for c in (*_ALIAS_FIELD_CANDIDATES, *_ALIASES_LIST_CANDIDATES)}
    canon_headers = {normal(c) for c in _CANONICAL_FIELD_CANDIDATES}
    has_header = any(h in alias_headers for h in header) and any(h in canon_headers for h in header)

    if has_header:
        dict_reader = csv.DictReader(io.StringIO(text))
        return _normalize_entries_collection(list(dict_reader))

    return _normalize_entries_collection(rows)


def enrich_gazetteer_from_merge(
    project: dict,
    canonical_name: str,
    canonical_kind: str,
    absorbed_nodes: list[dict[str, Any]],
    merge_id: str = "",
    actor: str = "",
) -> dict[str, dict[str, Any]]:
    """Tự động làm giàu từ điển bí danh của dự án khi chuyên viên phê duyệt gộp thực thể.
    Mỗi tên gọi và bí danh của các thực thể bị gộp sẽ được ánh xạ về tên chuẩn (canonical_name).
    """
    canon_clean = clean_display_text(canonical_name)
    if not canon_clean:
        return {}

    canon_key = normalize_gazetteer_key(canon_clean)
    gazetteer = project.setdefault("domain_gazetteer", {})
    ts = now_iso()
    added_or_updated: dict[str, dict[str, Any]] = {}

    for node in absorbed_nodes:
        node_name = clean_display_text(str(node.get("name", "")))
        node_kind = clean_display_text(str(node.get("kind", ""))) or canonical_kind
        aliases = list(node.get("aliases") or [])

        candidates: list[str] = []
        if node_name:
            candidates.append(node_name)
        candidates.extend(str(a) for a in aliases if a)

        for candidate in candidates:
            c_clean = clean_display_text(candidate)
            c_key = normalize_gazetteer_key(c_clean)
            if not c_key or c_key == canon_key:
                continue

            entry: dict[str, Any] = {
                "alias": c_clean,
                "canonical_name": canon_clean,
                "kind": canonical_kind or node_kind,
                "source": "human_curation_merge",
                "created_at": ts,
                "source_merge_id": str(merge_id or ""),
                "actor": str(actor or ""),
            }
            gazetteer[c_key] = entry
            added_or_updated[c_key] = entry

    return added_or_updated


def upsert_gazetteer_entry(
    project: dict,
    alias: str,
    canonical_name: str,
    kind: str = "",
    source: str = "manual",
    actor: str = "",
) -> dict[str, Any]:
    """Thêm hoặc cập nhật một mục trong từ điển bí danh dự án."""
    alias_clean = clean_display_text(alias)
    canon_clean = clean_display_text(canonical_name)
    if not alias_clean:
        raise ValueError("Bí danh (alias) không được để trống")
    if not canon_clean:
        raise ValueError("Tên chuẩn (canonical_name) không được để trống")

    key = normalize_gazetteer_key(alias_clean)
    canon_key = normalize_gazetteer_key(canon_clean)
    if key == canon_key:
        raise ValueError("Bí danh không được trùng với tên chuẩn hóa")

    gazetteer = project.setdefault("domain_gazetteer", {})
    entry: dict[str, Any] = {
        "alias": alias_clean,
        "canonical_name": canon_clean,
        "kind": clean_display_text(kind),
        "source": str(source or "manual"),
        "created_at": now_iso(),
        "source_merge_id": "",
        "actor": str(actor or ""),
    }
    gazetteer[key] = entry
    return entry


def delete_gazetteer_entry(
    project: dict,
    alias: str,
    actor: str = "",
) -> bool:
    """Xóa một mục khỏi từ điển bí danh dự án (van an toàn khi gộp nhầm)."""
    key = normalize_gazetteer_key(alias)
    gazetteer = project.get("domain_gazetteer", {})
    if key in gazetteer:
        del gazetteer[key]
        return True
    return False


def replace_gazetteer_entries(
    project: dict,
    entries: dict[str, Any] | list[dict[str, Any]],
    *,
    source: str = "manual_editor",
    actor: str = "",
) -> int:
    """Thay thế toàn bộ từ điển dự án bằng danh sách mới, bảo toàn metadata với các mục không thay đổi."""
    old_gaz = dict(project.get("domain_gazetteer") or {})
    normalized = _normalize_entries_collection(entries)
    new_gaz: dict[str, dict[str, Any]] = {}
    ts = now_iso()

    for row in normalized:
        key = normalize_gazetteer_key(row["alias"])
        prev = old_gaz.get(key)
        prev_canon = str(prev.get("canonical_name", "")) if isinstance(prev, dict) else (str(prev) if prev else "")
        prev_kind = str(prev.get("kind", "")) if isinstance(prev, dict) else ""

        if isinstance(prev, dict) and prev_canon == row["canonical_name"] and prev_kind == row["kind"]:
            preserved = dict(prev)
            preserved["alias"] = row["alias"]
            new_gaz[key] = preserved
        else:
            new_gaz[key] = {
                "alias": row["alias"],
                "canonical_name": row["canonical_name"],
                "kind": row["kind"],
                "source": row.get("source") or str(source or "manual_editor"),
                "created_at": ts,
                "source_merge_id": "",
                "actor": str(actor or ""),
            }

    project["domain_gazetteer"] = new_gaz
    return len(new_gaz)


def merge_gazetteer_entries(
    project: dict,
    entries: dict[str, Any] | list[dict[str, Any]],
    *,
    source: str = "imported_file",
    actor: str = "",
    overwrite_existing: bool = False,
) -> dict[str, int]:
    """Gộp thêm các mục từ file/template vào từ điển dự án hiện có."""
    normalized = _normalize_entries_collection(entries)
    gazetteer = project.setdefault("domain_gazetteer", {})
    added = 0
    updated = 0
    skipped = 0

    for row in normalized:
        key = normalize_gazetteer_key(row["alias"])
        existed = key in gazetteer
        if existed and not overwrite_existing:
            skipped += 1
            continue
        upsert_gazetteer_entry(
            project,
            alias=row["alias"],
            canonical_name=row["canonical_name"],
            kind=row["kind"],
            source=row.get("source") or source,
            actor=actor,
        )
        if existed:
            updated += 1
        else:
            added += 1

    return {
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "total": len(gazetteer),
    }


def clear_gazetteer(project: dict) -> int:
    """Xóa toàn bộ từ điển bí danh của dự án."""
    gaz = project.get("domain_gazetteer") or {}
    count = len(gaz)
    project["domain_gazetteer"] = {}
    return count


def list_gazetteer_entries(project: dict) -> list[dict[str, Any]]:
    """Lấy danh sách các mục từ điển bí danh dự án theo thứ tự chuẩn hóa."""
    gazetteer = project.get("domain_gazetteer", {})
    rows: list[dict[str, Any]] = []
    for key, val in gazetteer.items():
        if isinstance(val, dict):
            rows.append(
                {
                    "alias_key": key,
                    "alias": val.get("alias") or key,
                    "canonical_name": val.get("canonical_name", ""),
                    "kind": val.get("kind", ""),
                    "source": val.get("source", "unknown"),
                    "created_at": val.get("created_at", ""),
                    "source_merge_id": val.get("source_merge_id", ""),
                    "actor": val.get("actor", ""),
                }
            )
        elif isinstance(val, str):
            rows.append(
                {
                    "alias_key": key,
                    "alias": key,
                    "canonical_name": val,
                    "kind": "",
                    "source": "legacy",
                    "created_at": "",
                    "source_merge_id": "",
                    "actor": "",
                }
            )
    rows.sort(key=lambda r: (r["canonical_name"].lower(), r["alias"].lower()))
    return rows


def list_grouped_gazetteer_entries(project: dict) -> list[dict[str, Any]]:
    """Gom nhóm từ điển bí danh theo cặp (canonical_name, kind) phục vụ nhập/sửa theo dạng nhiều aliases."""
    flat_rows = list_gazetteer_entries(project)
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    for row in flat_rows:
        canon = clean_display_text(str(row.get("canonical_name") or ""))
        kind = clean_display_text(str(row.get("kind") or ""))
        alias = clean_display_text(str(row.get("alias") or ""))
        source = clean_display_text(str(row.get("source") or ""))
        if not canon:
            continue

        group_key = (normalize_gazetteer_key(canon), normalize_gazetteer_key(kind))
        grp = groups.get(group_key)
        if grp is None:
            grp = {
                "canonical_name": canon,
                "kind": kind,
                "alias_list": [],
                "alias_keys": set(),
                "source_list": [],
            }
            groups[group_key] = grp
        elif canon and canon[0].isupper() and grp["canonical_name"] and not grp["canonical_name"][0].isupper():
            grp["canonical_name"] = canon

        alias_key = normalize_gazetteer_key(alias)
        if alias and alias_key and alias_key not in grp["alias_keys"]:
            grp["alias_keys"].add(alias_key)
            grp["alias_list"].append(alias)
        if source and source not in grp["source_list"]:
            grp["source_list"].append(source)

    grouped: list[dict[str, Any]] = []
    for grp in groups.values():
        sorted_aliases = sorted(grp["alias_list"], key=lambda a: a.casefold())
        grouped.append(
            {
                "canonical_name": grp["canonical_name"],
                "kind": grp["kind"],
                "aliases": "; ".join(sorted_aliases),
                "sources": ", ".join(grp["source_list"]) if grp["source_list"] else "manual_editor",
                "alias_count": len(sorted_aliases),
            }
        )
    grouped.sort(key=lambda g: (g["canonical_name"].casefold(), g["kind"].casefold()))
    return grouped


def expand_grouped_gazetteer_rows(
    grouped_rows: list[dict[str, Any]],
    *,
    strict_conflicts: bool = True,
) -> list[dict[str, str]]:
    """Bung phẳng các dòng gom nhóm (canonical_name, kind, aliases ngăn cách ';' hoặc '|') thành bản ghi 1-1."""
    expanded: list[dict[str, str]] = []
    assigned: dict[str, tuple[str, str, str]] = {}

    for row in grouped_rows:
        if not isinstance(row, dict):
            continue
        canon = clean_display_text(str(row.get("canonical_name") or ""))
        kind = clean_display_text(str(row.get("kind") or ""))
        raw_aliases = row.get("aliases") if "aliases" in row else row.get("alias", "")
        alias_list = split_gazetteer_aliases(raw_aliases)

        if not canon and not alias_list:
            continue
        if alias_list and not canon:
            raise ValueError(
                f"Đã nhập bí danh ('{'; '.join(alias_list[:3])}') nhưng chưa nhập Tên chuẩn trong đồ thị (canonical_name)."
            )
        if not alias_list:
            continue

        canon_key = normalize_gazetteer_key(canon)
        kind_key = normalize_gazetteer_key(kind)
        target_label = f"{canon} [{kind}]" if kind else canon

        for alias in alias_list:
            alias_key = normalize_gazetteer_key(alias)
            if not alias_key or alias_key == canon_key:
                continue
            prev = assigned.get(alias_key)
            if prev is not None:
                prev_canon_key, prev_kind_key, prev_label = prev
                if prev_canon_key == canon_key and prev_kind_key == kind_key:
                    continue
                if strict_conflicts:
                    raise ValueError(
                        f"Bí danh '{alias}' đang bị gán trùng cho nhiều thực thể khác nhau: "
                        f"'{prev_label}' và '{target_label}'. Vui lòng giữ mỗi bí danh cho một chủ thể duy nhất."
                    )
                continue

            assigned[alias_key] = (canon_key, kind_key, target_label)
            expanded.append(
                {
                    "alias": alias,
                    "canonical_name": canon,
                    "kind": kind,
                }
            )

    return expanded


def gazetteer_to_json_bytes(project: dict) -> bytes:
    """Xuất từ điển bí danh của dự án sang JSON UTF-8 định dạng chuẩn để tải về hoặc tái sử dụng."""
    payload = project.get("domain_gazetteer") or {}
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def gazetteer_to_csv_bytes(project: dict, *, grouped: bool = True) -> bytes:
    """Xuất từ điển bí danh của dự án sang CSV (UTF-8 BOM cho Excel).
    Mặc định xuất dạng gom nhóm (`canonical_name, kind, aliases, sources`) với dấu '; ' giống danh mục quan hệ.
    """
    buf = io.StringIO()
    if grouped:
        grouped_rows = list_grouped_gazetteer_entries(project)
        writer = csv.DictWriter(
            buf,
            fieldnames=["canonical_name", "kind", "aliases", "sources"],
        )
        writer.writeheader()
        for row in grouped_rows:
            writer.writerow(
                {
                    "canonical_name": row.get("canonical_name", ""),
                    "kind": row.get("kind", ""),
                    "aliases": row.get("aliases", ""),
                    "sources": row.get("sources", ""),
                }
            )
        return buf.getvalue().encode("utf-8-sig")

    entries = list_gazetteer_entries(project)
    writer = csv.DictWriter(
        buf,
        fieldnames=["alias", "canonical_name", "kind", "source", "created_at"],
    )
    writer.writeheader()
    for row in entries:
        writer.writerow(
            {
                "alias": row.get("alias", ""),
                "canonical_name": row.get("canonical_name", ""),
                "kind": row.get("kind", ""),
                "source": row.get("source", ""),
                "created_at": row.get("created_at", ""),
            }
        )
    return buf.getvalue().encode("utf-8-sig")


def preload_gazetteer_template(
    project: dict,
    template_entries: dict[str, Any] | list[dict[str, Any]],
    source: str = "preloaded_template",
    actor: str = "",
    overwrite_existing: bool = False,
) -> int:
    """Nạp một bộ từ điển mẫu (ví dụ: Địa danh & Di tích lịch sử Hà Nội) vào dự án."""
    summary = merge_gazetteer_entries(
        project,
        template_entries,
        source=source,
        actor=actor,
        overwrite_existing=overwrite_existing,
    )
    return summary["added"] + summary["updated"]
