"""Kiểm tra toàn vẹn đồ thị và xuất dữ liệu JSON/CSV/ZIP (Độc lập 100%)."""
from __future__ import annotations

import csv
import io
import json
import zipfile

from backend.domain.catalogs.service import schema_review_issue
from backend.domain.curation.service import is_edge_exportable, validate_edge_for_approval
from shared.constants import STATUS_APPROVED
from shared.text_utils import now_iso, scrubbed


def validate_integrity(project: dict) -> list[str]:
    problems: list[str] = []
    node_ids = [n.get("id") for n in project.get("nodes", [])]
    edge_ids = [e.get("id") for e in project.get("edges", [])]

    if len(node_ids) != len(set(node_ids)):
        problems.append("Có ID thực thể bị trùng")
    if len(edge_ids) != len(set(edge_ids)):
        problems.append("Có ID quan hệ bị trùng")

    known = set(node_ids)
    for node in project.get("nodes", []):
        if not str(node.get("name") or "").strip():
            problems.append(f"Thực thể {node.get('id')} không có tên")

    for edge in project.get("edges", []):
        eid = edge.get("id")
        if edge.get("source") not in known or edge.get("target") not in known:
            problems.append(f"Quan hệ {eid} trỏ tới thực thể không tồn tại")
        if edge.get("source") == edge.get("target") and edge.get("status") == STATUS_APPROVED:
            if not edge.get("self_loop_confirmed") or not str(edge.get("review_note") or "").strip():
                problems.append(f"Quan hệ {eid} là tự tham chiếu nhưng đang được duyệt")
        if edge.get("status") == STATUS_APPROVED:
            if schema_review_issue(project, edge):
                problems.append(f"Quan hệ đã duyệt {eid} còn vướng đề xuất danh mục EDC")
            if not str(edge.get("evidence") or "").strip():
                problems.append(f"Quan hệ đã duyệt {eid} thiếu bằng chứng")
            val = validate_edge_for_approval(project, edge, is_batch=False, check_existing_override=True)
            if not val["ok"]:
                for err in val["errors"]:
                    msg = f"Quan hệ đã duyệt {eid} mất hiệu lực: {err}"
                    if msg not in problems:
                        problems.append(msg)
                if not val["evidence_ctx"].get("found") and not edge.get("override"):
                    legacy_msg = f"Quan hệ đã duyệt {eid} có bằng chứng không khớp nguồn"
                    if legacy_msg not in problems:
                        problems.append(legacy_msg)
    return problems


def approved_graph(project: dict) -> tuple[list[dict], list[dict]]:
    edges = [
        e
        for e in project.get("edges", [])
        if is_edge_exportable(project, e)
    ]
    ids = {x for e in edges for x in (e["source"], e["target"])}
    nodes = [n for n in project.get("nodes", []) if n["id"] in ids]
    return nodes, edges


def approved_json_bytes(project: dict) -> bytes:
    nodes, edges = approved_graph(project)
    payload = {
        "project_id": project.get("project_id"),
        "ten_du_an": project.get("name"),
        "xuat_luc": now_iso(),
        "thuc_the": nodes,
        "quan_he": edges,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def csv_bytes(records: list[dict], headers: list[str], list_fields: tuple[str, ...] = ()) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        row = record.copy()
        for field in list_fields:
            if field in row and isinstance(row[field], list):
                row[field] = " | ".join(str(x) for x in row[field])
        writer.writerow(row)
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


def export_zip(project: dict) -> bytes:
    nodes, edges = approved_graph(project)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("du_an_day_du.json", json.dumps(scrubbed(project), ensure_ascii=False, indent=2))
        archive.writestr("do_thi_da_duyet.json", approved_json_bytes(project).decode("utf-8"))
        archive.writestr(
            "thuc_the.csv",
            csv_bytes(nodes, ["id", "name", "kind", "description", "aliases"], ("aliases",)),
        )
        archive.writestr(
            "quan_he.csv",
            csv_bytes(
                edges,
                ["id", "source", "target", "relation", "evidence", "doc_name", "chunk_number", "page", "status"],
            ),
        )
    return output.getvalue()

