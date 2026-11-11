"""Kiểm tra toàn vẹn đồ thị và xuất dữ liệu JSON/CSV/ZIP (Độc lập 100%)."""
from __future__ import annotations

import csv
import io
import json
import zipfile

from backend.domain.catalogs.service import schema_review_issue
from backend.domain.curation.service import (
    build_curation_validation_context,
    is_edge_exportable,
    validate_edge_for_approval,
)
from shared.constants import STATUS_APPROVED
from shared.text_utils import now_iso, scrubbed


def validate_integrity(project: dict) -> list[str]:
    problems: list[str] = []
    problems_seen: set[str] = set()

    def _add_problem(msg: str) -> None:
        if msg not in problems_seen:
            problems_seen.add(msg)
            problems.append(msg)

    nodes = project.get("nodes", [])
    edges = project.get("edges", [])
    node_ids = [n.get("id") for n in nodes]
    edge_ids = [e.get("id") for e in edges]

    if len(node_ids) != len(set(node_ids)):
        _add_problem("Có ID thực thể bị trùng")
    if len(edge_ids) != len(set(edge_ids)):
        _add_problem("Có ID quan hệ bị trùng")

    known = set(node_ids)
    for node in nodes:
        if not str(node.get("name") or "").strip():
            _add_problem(f"Thực thể {node.get('id')} không có tên")

    has_approved = any(e.get("status") == STATUS_APPROVED for e in edges)
    val_ctx = build_curation_validation_context(project) if has_approved else None

    for edge in edges:
        eid = edge.get("id")
        if edge.get("source") not in known or edge.get("target") not in known:
            _add_problem(f"Quan hệ {eid} trỏ tới thực thể không tồn tại")
        if edge.get("source") == edge.get("target") and edge.get("status") == STATUS_APPROVED:
            if not edge.get("self_loop_confirmed") or not str(edge.get("review_note") or "").strip():
                _add_problem(f"Quan hệ {eid} là tự tham chiếu nhưng đang được duyệt")
        if edge.get("status") == STATUS_APPROVED:
            if schema_review_issue(project, edge, precomputed=val_ctx):
                _add_problem(f"Quan hệ đã duyệt {eid} còn vướng đề xuất danh mục EDC")
            if not str(edge.get("evidence") or "").strip():
                _add_problem(f"Quan hệ đã duyệt {eid} thiếu bằng chứng")
            val = validate_edge_for_approval(
                project,
                edge,
                is_batch=False,
                check_existing_override=True,
                precomputed=val_ctx,
                include_evidence_snippets=False,
            )
            if not val["ok"]:
                for err in val["errors"]:
                    _add_problem(f"Quan hệ đã duyệt {eid} mất hiệu lực: {err}")
                if not val["evidence_ctx"].get("found") and not edge.get("override"):
                    _add_problem(f"Quan hệ đã duyệt {eid} có bằng chứng không khớp nguồn")
    return problems


def approved_graph(project: dict) -> tuple[list[dict], list[dict]]:
    all_edges = project.get("edges", [])
    has_approved = any(e.get("status") == STATUS_APPROVED for e in all_edges)
    if not has_approved:
        return [], []
    val_ctx = build_curation_validation_context(project)
    edges = [
        e
        for e in all_edges
        if is_edge_exportable(project, e, precomputed=val_ctx)
    ]
    ids = {x for e in edges for x in (e["source"], e["target"])}
    nodes = [n for n in project.get("nodes", []) if n["id"] in ids]
    return nodes, edges


def _build_enriched_export_payload(project: dict, nodes: list[dict], edges: list[dict]) -> tuple[list[dict], bytes]:
    nodes_by_id = {n["id"]: n for n in nodes}
    enriched_edges = []
    for e in edges:
        ec = dict(e)
        src = nodes_by_id.get(e.get("source"), {})
        tgt = nodes_by_id.get(e.get("target"), {})
        ec["source_name"] = src.get("name", "")
        ec["source_kind"] = src.get("kind", "")
        ec["target_name"] = tgt.get("name", "")
        ec["target_kind"] = tgt.get("kind", "")
        enriched_edges.append(ec)
    payload = {
        "project_id": project.get("project_id"),
        "ten_du_an": project.get("name"),
        "xuat_luc": now_iso(),
        "thuc_the": nodes,
        "quan_he": enriched_edges,
    }
    return enriched_edges, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def approved_json_bytes(project: dict) -> bytes:
    nodes, edges = approved_graph(project)
    _, json_data = _build_enriched_export_payload(project, nodes, edges)
    return json_data


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


def export_zip(project: dict, *, qa_max_samples: int = 2000) -> bytes:
    from backend.domain.graph.qa_generator import generate_training_qa_dataset

    nodes, edges = approved_graph(project)
    enriched_edges, approved_bytes = _build_enriched_export_payload(project, nodes, edges)
    if edges:
        ds = generate_training_qa_dataset(project, max_samples=qa_max_samples, approved_only=True)
        qa_dataset = ds["all_samples"]
        train_jsonl = "\n".join(json.dumps(item, ensure_ascii=False) for item in ds["train_samples"])
        val_jsonl = "\n".join(json.dumps(item, ensure_ascii=False) for item in ds["val_samples"])
        test_jsonl = "\n".join(json.dumps(item, ensure_ascii=False) for item in ds["test_samples"])
    else:
        qa_dataset = []
        train_jsonl = ""
        val_jsonl = ""
        test_jsonl = ""
    qa_jsonl = "\n".join(json.dumps(item, ensure_ascii=False) for item in qa_dataset)

    # Định dạng chuẩn PyTorch Geometric (PyG G-Retriever: node_id,node_attr và src,edge_attr,dst)
    node_idx_map = {n["id"]: idx for idx, n in enumerate(nodes)}
    pyg_nodes = [
        {
            "node_id": idx,
            "orig_id": n.get("id", ""),
            "node_attr": f"{n.get('name', '')} ({n.get('kind', '')}): {n.get('description', '')}".strip(),
        }
        for idx, n in enumerate(nodes)
    ]
    pyg_edges = [
        {
            "src": node_idx_map[e["source"]],
            "edge_attr": f"{e.get('relation', '')} | Bằng chứng: {e.get('evidence', '')}".strip(),
            "dst": node_idx_map[e["target"]],
            "orig_edge_id": e.get("id", ""),
        }
        for e in enriched_edges
        if e.get("source") in node_idx_map and e.get("target") in node_idx_map
    ]

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("du_an_day_du.json", json.dumps(scrubbed(project), ensure_ascii=False, indent=2))
        archive.writestr("do_thi_da_duyet.json", approved_bytes.decode("utf-8"))
        archive.writestr("bo_cau_hoi_g_retriever.json", json.dumps(qa_dataset, ensure_ascii=False, indent=2))
        archive.writestr("bo_cau_hoi_g_retriever.jsonl", qa_jsonl)
        archive.writestr("train.jsonl", train_jsonl)
        archive.writestr("val.jsonl", val_jsonl)
        archive.writestr("test.jsonl", test_jsonl)
        archive.writestr(
            "thuc_the.csv",
            csv_bytes(nodes, ["id", "name", "kind", "description", "aliases"], ("aliases",)),
        )
        archive.writestr(
            "quan_he.csv",
            csv_bytes(
                enriched_edges,
                [
                    "id",
                    "source",
                    "source_name",
                    "source_kind",
                    "relation",
                    "target",
                    "target_name",
                    "target_kind",
                    "evidence",
                    "doc_name",
                    "chunk_number",
                    "page",
                    "status",
                ],
            ),
        )
        archive.writestr(
            "pyg_nodes.csv",
            csv_bytes(pyg_nodes, ["node_id", "orig_id", "node_attr"]),
        )
        archive.writestr(
            "pyg_edges.csv",
            csv_bytes(pyg_edges, ["src", "edge_attr", "dst", "orig_edge_id"]),
        )
    return output.getvalue()

