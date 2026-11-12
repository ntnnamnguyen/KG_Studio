"""Quản lý tiếp nhận Đề xuất EDC, kiểm tra độ mới và tính toán phạm vi ảnh hưởng."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from backend.domain.catalogs.core import catalog_rows, compute_catalog_hash
from shared.constants import MODE_EDC, MODE_EDC_PLUS_R
from shared.text_utils import clean_relation_name, normal, now_iso, sha, uid


def is_proposal_candidates_stale(
    project: dict,
    proposal: dict,
    current_model_fingerprint: str = "",
    *,
    precomputed_cat_hash: str | None = None,
) -> tuple[bool, str]:
    """Kiểm tra xem gợi ý ứng viên của đề xuất có bị cũ (stale) do đổi định nghĩa, catalog hoặc model không."""
    cands = proposal.get("alignment_candidates") or []
    if not cands:
        return False, ""
    kind = proposal.get("kind", "relations")
    cur_cat_hash = precomputed_cat_hash if precomputed_cat_hash is not None else compute_catalog_hash(project, kind)
    saved_cat_hash = str(proposal.get("candidates_catalog_hash") or "")
    if saved_cat_hash and saved_cat_hash != cur_cat_hash:
        return True, "Danh mục đã thay đổi kể từ lần gợi ý trước"

    cur_def_hash = sha(str(proposal.get("definition", "")).strip())[:16]
    saved_def_hash = str(proposal.get("candidates_definition_hash") or "")
    if saved_def_hash and saved_def_hash != cur_def_hash:
        return True, "Định nghĩa đề xuất đã thay đổi kể từ lần gợi ý trước"

    saved_model_fp = str(proposal.get("candidates_model_fingerprint") or "")
    if current_model_fingerprint and saved_model_fp and saved_model_fp != current_model_fingerprint:
        return True, "Mô hình embedding đã thay đổi kể từ lần gợi ý trước"

    return False, ""


def propose_term(project: dict, kind: str, name: str, definition: str, observation: dict) -> tuple[str, str]:
    rows = catalog_rows(project, kind)
    canonical = {normal(row["name"]): row["name"] for row in rows}
    if kind == "relations":
        for row in rows:
            canonical[normal(clean_relation_name(row["name"]))] = row["name"]
        match = canonical.get(normal(name))
        if match is None:
            cleaned = clean_relation_name(name)
            match = canonical.get(normal(cleaned))
            if match is None:
                name = cleaned
            else:
                name = match
        else:
            name = match

    proposals = project.setdefault("schema_proposals", [])
    proposal = next((p for p in proposals if p["kind"] == kind and normal(p["name"]) == normal(name)), None)
    if proposal is None and normal(name) in canonical:
        return canonical[normal(name)], ""
    if proposal is None:
        proposal = {
            "id": uid(),
            "kind": kind,
            "name": name,
            "definition": definition,
            "description": "",
            "status": "pending",
            "canonical_name": "",
            "auto_aligned": False,
            "decision_origin": "",
            "observations": [],
            "created_at": now_iso(),
        }
        proposals.append(proposal)
    observed = dict(observation, definition=definition)
    identity = lambda item: (item.get("doc_id"), item.get("chunk_hash"), item.get("example"), item.get("definition"))
    if not any(identity(item) == identity(observed) for item in proposal["observations"]):
        proposal["observations"].append(observed)
    if not proposal["definition"] and definition:
        proposal["definition"] = definition
    target = canonical.get(normal(proposal.get("canonical_name", "")))
    if proposal["status"] in ("approved", "merged") and target:
        return target, proposal["id"]
    return name, proposal["id"]


def prepare_edc(project: dict, clean: dict, payload: dict, context: dict) -> None:
    definitions: dict[str, dict[str, str]] = {}
    definitions["entity_types"] = {normal(row["ten"]): row["dinh_nghia"].strip() for row in payload.get("dinh_nghia_loai", [])}
    rel_defs: dict[str, str] = {}
    for row in payload.get("dinh_nghia_quan_he", []):
        raw_t = row.get("ten", "")
        clean_t = clean_relation_name(raw_t)
        d_val = row.get("dinh_nghia", "").strip()
        rel_defs[normal(raw_t)] = d_val
        rel_defs[normal(clean_t)] = d_val
    definitions["relations"] = rel_defs

    entities = {}
    for entity in clean["thuc_the"]:
        original = entity["loai"]
        relevant = [r["trich_dan"] for r in clean["quan_he"] if normal(entity["ten"]) in (normal(r["nguon"]), normal(r["dich"]))]
        kind, proposal_id = propose_term(
            project,
            "entity_types",
            original,
            definitions["entity_types"].get(normal(original), ""),
            dict(context, example=entity["ten"], evidence="\n".join(dict.fromkeys(relevant))),
        )
        entity.update(loai=kind, original_kind=original, schema_proposal_ids=[proposal_id] if proposal_id else [])
        entities[normal(entity["ten"])] = entity
    for relation in clean["quan_he"]:
        original = {field: relation[field] for field in ("nguon", "quan_he", "dich", "trich_dan")}
        label, proposal_id = propose_term(
            project,
            "relations",
            relation["quan_he"],
            definitions["relations"].get(normal(relation["quan_he"]), ""),
            dict(context, example=f"{relation['nguon']} — {relation['quan_he']} → {relation['dich']}", evidence=relation["trich_dan"]),
        )
        ids = [proposal_id] if proposal_id else []
        for endpoint in (relation["nguon"], relation["dich"]):
            ids.extend(entities[normal(endpoint)]["schema_proposal_ids"])
        relation.update(quan_he=label, edc_original=original, schema_proposal_ids=list(dict.fromkeys(ids)))


def schema_review_issue(
    project: dict,
    edge: dict,
    *,
    precomputed: dict[str, Any] | None = None,
) -> str:
    if edge.get("extraction_mode") not in (MODE_EDC, MODE_EDC_PLUS_R):
        return ""
    if precomputed is not None:
        proposals = precomputed.get("proposals", {})
        nodes = precomputed.get("nodes", {})
        rel_rows = precomputed.get("rel_norms", set())
        types = precomputed.get("type_norms", set())
    else:
        proposals = {p["id"]: p for p in project.get("schema_proposals", [])}
        nodes = {n["id"]: n for n in project.get("nodes", [])}
        rel_rows = {normal(row["name"]) for row in catalog_rows(project, "relations")}
        types = {normal(row["name"]) for row in catalog_rows(project, "entity_types")}

    rel_name = str(edge.get("relation", "")).strip()
    src_node = nodes.get(edge.get("source"), {})
    tgt_node = nodes.get(edge.get("target"), {})
    src_kind = str(src_node.get("kind", "")).strip()
    tgt_kind = str(tgt_node.get("kind", "")).strip()

    # Nếu cả 3 thành phần (R, S.kind, T.kind) đều đã nằm trong danh mục đã duyệt -> hợp lệ hoàn toàn!
    if (
        normal(rel_name) in rel_rows
        and src_node
        and normal(src_kind) in types
        and tgt_node
        and normal(tgt_kind) in types
    ):
        return ""

    all_prop_ids = list(edge.get("schema_proposal_ids", []))
    for endpoint in ("source", "target"):
        node = nodes.get(edge.get(endpoint), {})
        for pid in node.get("schema_proposal_ids", []):
            if pid not in all_prop_ids:
                all_prop_ids.append(pid)

    for identifier in all_prop_ids:
        proposal = proposals.get(identifier)
        if not proposal:
            continue
        p_kind = proposal.get("kind")
        # Bỏ qua proposal nếu thành phần tương ứng đã có trong danh mục chính thức
        if p_kind == "relations" and normal(rel_name) in rel_rows:
            continue
        if p_kind == "entity_types":
            if (
                src_node
                and identifier in src_node.get("schema_proposal_ids", [])
                and normal(src_kind) in types
            ):
                continue
            if (
                tgt_node
                and identifier in tgt_node.get("schema_proposal_ids", [])
                and normal(tgt_kind) in types
            ):
                continue

        if proposal.get("status") not in ("approved", "merged"):
            return "Cần duyệt hoặc hợp nhất đề xuất loại/quan hệ EDC trước khi duyệt cạnh."
        target_rows = rel_rows if p_kind == "relations" else types
        if normal(proposal.get("canonical_name", "")) not in target_rows:
            return "Mục danh mục đã duyệt của đề xuất EDC không còn tồn tại."

    if normal(rel_name) not in rel_rows:
        return "Tên quan hệ EDC chưa có trong danh mục đã duyệt."
    if any(normal(nodes.get(edge.get(endpoint), {}).get("kind", "")) not in types for endpoint in ("source", "target")):
        return "Loại thực thể của cạnh EDC chưa có trong danh mục đã duyệt."
    return ""


def batch_proposal_impacts(project: dict, proposal_ids: Sequence[str] | None = None) -> dict[str, dict]:
    """Tính phạm vi ảnh hưởng cho nhiều đề xuất bằng reverse index trong một lần quét O(N + E)."""
    target_ids = set(str(pid) for pid in proposal_ids) if proposal_ids is not None else None

    # 1. Reverse index từ proposal_id -> direct nodes
    prop_to_nodes: dict[str, list[str]] = {}
    node_to_props: dict[str, set[str]] = {}
    for n in project.get("nodes", []):
        nid = str(n.get("id", ""))
        for pid in n.get("schema_proposal_ids", []):
            spid = str(pid)
            if target_ids is None or spid in target_ids:
                prop_to_nodes.setdefault(spid, []).append(nid)
                node_to_props.setdefault(nid, set()).add(spid)

    # 2. Reverse index từ proposal_id -> direct edges & indirect edges
    prop_to_direct_edges: dict[str, list[str]] = {}
    prop_to_indirect_edges: dict[str, list[str]] = {}

    for e in project.get("edges", []):
        eid = str(e.get("id", ""))
        e_props = set(str(pid) for pid in e.get("schema_proposal_ids", []))

        # Cạnh trực tiếp gắn proposal_id này
        for pid in e_props:
            if target_ids is None or pid in target_ids:
                prop_to_direct_edges.setdefault(pid, []).append(eid)

        # Cạnh gián tiếp qua source hoặc target mang proposal_id này
        src_id = str(e.get("source", ""))
        tgt_id = str(e.get("target", ""))
        touching_props = (node_to_props.get(src_id, set()) | node_to_props.get(tgt_id, set())) - e_props
        for pid in touching_props:
            if target_ids is None or pid in target_ids:
                prop_to_indirect_edges.setdefault(pid, []).append(eid)

    all_keys = target_ids if target_ids is not None else (set(prop_to_nodes.keys()) | set(prop_to_direct_edges.keys()))
    results: dict[str, dict] = {}
    for pid in all_keys:
        d_nodes = prop_to_nodes.get(pid, [])
        d_edges = prop_to_direct_edges.get(pid, [])
        ind_edges = prop_to_indirect_edges.get(pid, [])
        all_e = list(dict.fromkeys([*d_edges, *ind_edges]))
        results[pid] = {
            "nodes": d_nodes,
            "edges": all_e,
            "direct_edges": d_edges,
            "indirect_edges": ind_edges,
        }
    return results


def proposal_impact(project: dict, proposal_id: str) -> dict:
    """Tính phạm vi ảnh hưởng của đề xuất: bao gồm cả cạnh trực tiếp và cạnh gián tiếp qua đổi loại node."""
    res = batch_proposal_impacts(project, [str(proposal_id)])
    return res.get(str(proposal_id), {"nodes": [], "edges": [], "direct_edges": [], "indirect_edges": []})
