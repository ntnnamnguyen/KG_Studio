"""Quản lý Danh mục, Prompt, Đề xuất EDC và Duyệt Hàng Loạt (Độc lập 100%)."""
from __future__ import annotations

from collections.abc import Sequence
import copy
import hashlib
import json
from typing import Any

from shared.catalog_utils import apply_relations, edc_prompt, relation_catalog, validate_catalog
from shared.constants import (
    DEFAULT_EDC_PROMPT,
    MODE_EDC,
    MODE_EDC_PLUS_R,
    MODE_FIXED,
    STATUS_CHECK,
    STATUS_REJECTED,
)
from shared.schemas.edc import (
    BulkReviewPreviewDTO,
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
    ProposalDecisionDTO,
)
from shared.text_utils import clean_relation_name, normal, now_iso, sha, uid
from backend.domain.prompts.service import (
    get_active_prompt_content,
    save_prompt_version,
)


def prompt_signature(prompt: str, relations: list[str]) -> str:
    return sha(prompt + "\n" + "\n".join(relations))[:12]


def extraction_prompt(project: dict) -> str:
    mode = project.get("extraction_mode", MODE_FIXED)
    if mode in (MODE_EDC, MODE_EDC_PLUS_R):
        base = get_active_prompt_content(project, mode)
        return edc_prompt(base)
    base = get_active_prompt_content(project, MODE_FIXED)
    catalogs = {"relations": relation_catalog(project), "entity_types": project.get("entity_types", [])}
    return (
        base.strip()
        + "\n\nDANH MỤC QUAN HỆ VÀ LOẠI THỰC THỂ ĐƯỢC PHÉP (JSON):\n"
        + json.dumps(catalogs, ensure_ascii=False, indent=2)
        + "\nChỉ dùng name trong relations cho trường quan_he và name trong entity_types cho trường loai."
    )


def save_prompt_settings(project: dict, prompt: str, relations: list[dict], entity_types: list[dict]) -> bool:
    relations = validate_catalog(relations, "relations", allow_empty=True)
    entity_types = validate_catalog(entity_types, "entity_types", allow_empty=True)
    apply_relations(project, relations)
    project["entity_types"] = entity_types
    if isinstance(prompt, str) and prompt.strip():
        save_prompt_version(project, MODE_FIXED, prompt.strip(), note="Cập nhật kèm danh mục")
    return True


def catalog_rows(project: dict, kind: str) -> list[dict]:
    if kind == "relations":
        return relation_catalog(project)
    if kind == "entity_types":
        return validate_catalog(project.get("entity_types", []), "entity_types") if project.get("entity_types") else []
    raise ValueError("Nhóm đề xuất không hợp lệ")


def compute_catalog_hash(project: dict, kind: str | None = None) -> str:
    """Băm xác định cho danh mục hiện tại của dự án (theo từng kind hoặc toàn bộ)."""
    if kind in ("relations", "entity_types"):
        rows = catalog_rows(project, kind)
        return sha(json.dumps(rows, ensure_ascii=False, sort_keys=True))[:16]
    payload = {
        "relations": catalog_rows(project, "relations"),
        "entity_types": catalog_rows(project, "entity_types"),
    }
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def compute_project_revision(project: dict) -> str:
    """Tính revision phản ánh chính xác trạng thái dự án, danh mục, đề xuất và node/cạnh (streaming SHA-256 O(V+E+P))."""
    h = hashlib.sha256()
    upd = h.update
    sep = "\x1f"
    rec = "\x1e"

    upd(
        f"hdr{sep}{project.get('project_id', '')}{sep}{project.get('name', '')}{sep}{compute_catalog_hash(project)}{rec}".encode(
            "utf-8"
        )
    )

    prop_chunks: list[str] = []
    for p in project.get("schema_proposals", []):
        prop_chunks.append(
            f"{p.get('id', '')}{sep}{p.get('kind', '')}{sep}{p.get('name', '')}{sep}"
            f"{p.get('definition', '')}{sep}{p.get('description', '')}{sep}"
            f"{p.get('status', 'pending')}{sep}{p.get('canonical_name', '')}{sep}"
            f"{1 if p.get('auto_aligned', False) else 0}{sep}{p.get('decision_origin', '')}"
        )
    upd(("P:" + rec.join(prop_chunks) + rec).encode("utf-8"))

    node_chunks: list[str] = []
    for n in project.get("nodes", []):
        aliases_s = "\x1d".join(str(x) for x in n.get("aliases", ()))
        docs_s = "\x1d".join(str(x) for x in n.get("documents", ()))
        pids_s = "\x1d".join(str(x) for x in n.get("schema_proposal_ids", ()))
        node_chunks.append(
            f"{n.get('id', '')}{sep}{n.get('name', '')}{sep}{n.get('kind', '')}{sep}"
            f"{n.get('description', '')}{sep}{aliases_s}{sep}{docs_s}{sep}{pids_s}"
        )
    upd(("N:" + rec.join(node_chunks) + rec).encode("utf-8"))

    edge_chunks: list[str] = []
    for e in project.get("edges", []):
        pids_s = "\x1d".join(str(x) for x in e.get("schema_proposal_ids", ()))
        edge_chunks.append(
            f"{e.get('id', '')}{sep}{e.get('source', '')}{sep}{e.get('target', '')}{sep}"
            f"{e.get('relation', '')}{sep}{e.get('evidence', '')}{sep}{e.get('doc_id', '')}{sep}"
            f"{e.get('start_char')}{sep}{e.get('end_char')}{sep}{e.get('status', '')}{sep}"
            f"{1 if e.get('override', False) else 0}{sep}{e.get('rejection_code', '')}{sep}{pids_s}"
        )
    upd(("E:" + rec.join(edge_chunks) + rec).encode("utf-8"))

    node_redirs = sorted((str(k), str(v)) for k, v in (project.get("node_redirects") or {}).items())
    rel_redirs = sorted((str(k), str(v)) for k, v in (project.get("relation_redirects") or {}).items())
    p_bindings = sorted((str(k), str(v)) for k, v in (project.get("prompt_bindings") or {}).items())
    p_versions = sorted(str(v.get("id", "")) for v in project.get("prompt_versions", ()))
    tail = (
        f"T:{node_redirs}{sep}{rel_redirs}{sep}"
        f"{len(project.get('not_duplicate_pairs', ()))}{sep}"
        f"{len(project.get('not_duplicate_relation_pairs', ()))}{sep}"
        f"{p_bindings}{sep}{p_versions}"
    )
    upd(tail.encode("utf-8"))
    return h.hexdigest()[:16]


def compute_decisions_hash(project_id: str, kind: str, decisions: list[ProposalDecisionDTO | dict]) -> str:
    """Băm danh sách quyết định trong lô (dùng để kiểm tra tính toàn vẹn giữa preview và apply)."""
    normalized = [ProposalDecisionDTO.from_dict(d).to_dict() for d in decisions]
    payload = {
        "project_id": str(project_id or "").strip(),
        "kind": str(kind or "").strip(),
        "decisions": normalized,
    }
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def compute_full_request_hash(req: BulkReviewRequestDTO | dict) -> str:
    """Băm toàn bộ nội dung request (kể cả apply_mode) để kiểm tra idempotency theo request_id."""
    dto = BulkReviewRequestDTO.from_dict(req)
    payload = {
        "project_id": dto.project_id,
        "kind": dto.kind,
        "apply_mode": dto.apply_mode,
        "decisions": [d.to_dict() for d in dto.decisions],
    }
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


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
    definitions = {}
    definitions["entity_types"] = {normal(row["ten"]): row["dinh_nghia"].strip() for row in payload.get("dinh_nghia_loai", [])}
    rel_defs = {}
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


def _default_description_for_approval(proposal: dict, target_name: str, explicit_description: str = "") -> str:
    if explicit_description.strip():
        return explicit_description.strip()
    if str(proposal.get("description") or "").strip():
        return str(proposal.get("description")).strip()
    example = next((item.get("example", "") for item in proposal.get("observations", []) if item.get("example")), "")
    return f"Ví dụ: {example}" if example else target_name


def _clone_project_for_edc_mutation(project: dict) -> dict:
    """Tạo bản sao có mục tiêu cho thao tác duyệt đề xuất EDC (tránh copy.deepcopy toàn bộ văn bản tài liệu lớn)."""
    candidate = dict(project)
    candidate["relations"] = list(project.get("relations", []))
    candidate["relation_notes"] = copy.deepcopy(project.get("relation_notes", {}))
    candidate["entity_types"] = [copy.deepcopy(r) for r in project.get("entity_types", [])]
    candidate["schema_proposals"] = list(project.get("schema_proposals", []))
    candidate["nodes"] = list(project.get("nodes", []))
    candidate["edges"] = list(project.get("edges", []))
    candidate["schema_decisions"] = list(project.get("schema_decisions", []))
    candidate["schema_decision_batches"] = list(project.get("schema_decision_batches", []))
    return candidate


def decide_proposal(
    project: dict,
    proposal_id: str,
    action: str,
    canonical_name: str = "",
    definition: str = "",
    note: str = "",
    description: str = "",
    *,
    batch_id: str = "",
    request_id: str = "",
    decision_origin: str = "human",
    actor: str = "human_reviewer",
) -> dict:
    if action not in ("approve", "merge", "reject"):
        raise ValueError("Thao tác đề xuất không hợp lệ")
    candidate = _clone_project_for_edc_mutation(project)
    prop_idx = next(
        (idx for idx, p in enumerate(candidate["schema_proposals"]) if p["id"] == proposal_id),
        None,
    )
    if prop_idx is None:
        raise ValueError("Không tìm thấy đề xuất")
    orig_proposal = candidate["schema_proposals"][prop_idx]
    previous = copy.deepcopy(orig_proposal)
    proposal = copy.deepcopy(orig_proposal)
    candidate["schema_proposals"][prop_idx] = proposal

    impact = proposal_impact(candidate, proposal_id)
    rows = catalog_rows(candidate, proposal["kind"])
    target_name = canonical_name.strip()
    if action != "reject":
        if not target_name:
            raise ValueError("Tên chuẩn không được rỗng")
        target = next((row for row in rows if normal(row["name"]) == normal(target_name)), None)
        if action == "merge":
            if target is None:
                raise ValueError("Chọn một mục đã có trong danh mục để hợp nhất")
            target_name = target["name"]
        else:
            if target is not None:
                raise ValueError("Tên đã có trong danh mục. Hãy chọn Hợp nhất vào mục có sẵn.")
            if not definition.strip():
                raise ValueError("Cần định nghĩa trước khi duyệt mục mới")
            resolved_desc = _default_description_for_approval(proposal, target_name, description)
            rows = validate_catalog(
                rows
                + [
                    {
                        "name": target_name,
                        "description": resolved_desc,
                        "definition": definition.strip(),
                    }
                ],
                proposal["kind"],
            )
            if proposal["kind"] == "relations":
                apply_relations(candidate, rows)
            else:
                candidate["entity_types"] = rows
        if proposal["kind"] != "relations":
            nodes_list = candidate["nodes"]
            for idx, node in enumerate(nodes_list):
                if proposal_id in node.get("schema_proposal_ids", []):
                    new_node = dict(node)
                    new_node["kind"] = target_name
                    nodes_list[idx] = new_node

    affected_nodes = set(impact["nodes"])
    affected_edge_set = set(impact["edges"])
    is_rel_update = action != "reject" and proposal["kind"] == "relations"
    edges_list = candidate["edges"]
    for idx, edge in enumerate(edges_list):
        rel_hit = is_rel_update and (proposal_id in edge.get("schema_proposal_ids", []))
        status_hit = edge["id"] in affected_edge_set or (
            edge.get("source") in affected_nodes or edge.get("target") in affected_nodes
        )
        if rel_hit or status_hit:
            new_edge = dict(edge)
            if rel_hit:
                new_edge["relation"] = target_name
            if status_hit and new_edge.get("status") != STATUS_REJECTED:
                new_edge.update(status=STATUS_CHECK, reviewed_at="", override=False)
            edges_list[idx] = new_edge

    proposal.update(
        status={"approve": "approved", "merge": "merged", "reject": "rejected"}[action],
        canonical_name=target_name if action != "reject" else "",
        reviewed_at=now_iso(),
        definition=definition.strip() or proposal.get("definition", ""),
        review_note=note.strip(),
        auto_aligned=False,
        decision_origin=decision_origin,
        batch_id=batch_id,
    )
    if action == "approve":
        proposal["description"] = next(row["description"] for row in rows if normal(row["name"]) == normal(target_name))
    candidate["schema_decisions"].append(
        {
            "at": now_iso(),
            "proposal_id": proposal_id,
            "action": action,
            "before": previous,
            "after": copy.deepcopy(proposal),
            "impact": impact,
            "batch_id": batch_id,
            "request_id": request_id,
            "decision_origin": decision_origin,
            "actor": actor,
        }
    )
    project.clear()
    project.update(candidate)
    return impact


def preview_proposal_decisions(
    project: dict,
    request: BulkReviewRequestDTO | dict,
    *,
    current_model_fingerprint: str = "",
) -> BulkReviewPreviewDTO:
    """Kiểm tra toàn bộ lô quyết định không ghi dự án (O(V+E+B)), trả về BulkReviewPreviewDTO."""
    req = BulkReviewRequestDTO.from_dict(request)
    work_project = project
    proj_id = str(work_project.get("project_id") or "")
    proj_name = str(work_project.get("name") or "")
    revision = compute_project_revision(work_project)

    batch_errors: list[str] = []
    if req.kind not in ("entity_types", "relations"):
        batch_errors.append(f"Nhóm danh mục không hợp lệ: '{req.kind}'")
    if req.project_id and req.project_id not in (proj_id, proj_name):
        batch_errors.append(f"project_id '{req.project_id}' không khớp với dự án đang mở ('{proj_name}')")
    if req.apply_mode not in ("all_or_nothing", "valid_only"):
        batch_errors.append(f"Chế độ áp dụng không hợp lệ: '{req.apply_mode}'")
    if not req.decisions:
        batch_errors.append("Chưa có quyết định nào trong lô để xem trước.")

    cat_hash = compute_catalog_hash(work_project, req.kind if req.kind in ("entity_types", "relations") else None)
    existing_rows = catalog_rows(work_project, req.kind) if req.kind in ("entity_types", "relations") else []
    existing_by_norm = {normal(row["name"]): row for row in existing_rows}

    proposals_by_id = {str(p.get("id", "")): p for p in work_project.get("schema_proposals", [])}

    # 1. Khử trùng ID giống hệt nhau; bắt lỗi nếu cùng ID nhưng có nhiều quyết định mâu thuẫn
    by_pid: dict[str, list[ProposalDecisionDTO]] = {}
    ordered_unique_pids: list[str] = []
    for dec in req.decisions:
        pid = dec.proposal_id
        if pid not in by_pid:
            ordered_unique_pids.append(pid)
            by_pid[pid] = []
        by_pid[pid].append(dec)

    conflicting_duplicate_pids: set[str] = set()
    deduped_decisions: list[ProposalDecisionDTO] = []
    for pid in ordered_unique_pids:
        group = by_pid[pid]
        sigs = {
            (
                d.kind or req.kind,
                d.action,
                normal(d.canonical_name) if d.action != "reject" else "",
                d.definition.strip() if d.action == "approve" else "",
                d.description.strip() if d.action == "approve" else "",
                d.note.strip(),
            )
            for d in group
        }
        if len(sigs) > 1:
            conflicting_duplicate_pids.add(pid)
        deduped_decisions.append(group[0])

    # Tính phạm vi ảnh hưởng một lần O(V+E) cho toàn bộ lô thay vì quét lại theo từng dòng
    existing_pids_in_batch = [pid for pid in ordered_unique_pids if pid in proposals_by_id]
    impacts_map = batch_proposal_impacts(work_project, existing_pids_in_batch) if existing_pids_in_batch else {}
    empty_impact = {"nodes": [], "edges": [], "direct_edges": [], "indirect_edges": []}

    # 2. Kiểm tra từng dòng và thu thập thông tin để kiểm tra xung đột chéo trong lô
    item_map: dict[str, dict[str, Any]] = {}
    approve_name_groups: dict[str, list[str]] = {}
    newly_approved_norms: set[str] = set()

    for dec in deduped_decisions:
        pid = dec.proposal_id
        if dec.action == "approve" and dec.canonical_name.strip():
            norm_target = normal(dec.canonical_name.strip())
            approve_name_groups.setdefault(norm_target, []).append(pid)
            newly_approved_norms.add(norm_target)

    for dec in deduped_decisions:
        pid = dec.proposal_id
        proposal = proposals_by_id.get(pid)
        errors: list[str] = []
        warnings: list[str] = []

        if req.project_id and req.project_id not in (proj_id, proj_name):
            errors.append(f"ID dự án '{req.project_id}' không khớp dự án hiện tại")

        if pid in conflicting_duplicate_pids:
            errors.append(f"ID đề xuất '{pid}' xuất hiện nhiều lần với quyết định mâu thuẫn trong cùng lô")

        if proposal is None:
            errors.append(f"Không tìm thấy đề xuất ID '{pid}' trong dự án")
            impact = dict(empty_impact)
            orig_name = ""
            resolved_desc = dec.description.strip()
            resolved_def = dec.definition.strip()
            resolved_target = dec.canonical_name.strip()
        else:
            orig_name = str(proposal.get("name", ""))
            impact = impacts_map.get(pid, dict(empty_impact))
            prop_kind = str(proposal.get("kind", ""))
            if prop_kind != req.kind or (dec.kind and dec.kind != req.kind):
                errors.append(f"Đề xuất '{orig_name}' thuộc nhóm '{prop_kind}', không khớp bảng '{req.kind}'")
            if proposal.get("status") != "pending":
                errors.append(
                    f"Đề xuất '{orig_name}' đang ở trạng thái '{proposal.get('status')}' (chỉ duyệt hàng loạt mục 'pending')"
                )

            stale_cat_hash = cat_hash if prop_kind == req.kind else None
            stale, stale_reason = is_proposal_candidates_stale(
                work_project,
                proposal,
                current_model_fingerprint,
                precomputed_cat_hash=stale_cat_hash,
            )
            if stale:
                warnings.append(stale_reason)

            resolved_def = dec.definition.strip() or str(proposal.get("definition", "")).strip()
            resolved_target = dec.canonical_name.strip()
            resolved_desc = dec.description.strip()

            if dec.action not in ("approve", "merge", "reject"):
                errors.append(f"Thao tác '{dec.action}' không hợp lệ (chỉ hỗ trợ approve, merge, reject)")
            elif dec.action == "approve":
                if not resolved_target:
                    errors.append("Tên chuẩn không được rỗng khi duyệt thành mục mới")
                if not resolved_def:
                    errors.append("Cần định nghĩa trước khi duyệt thành mục mới")
                if resolved_target:
                    norm_t = normal(resolved_target)
                    if norm_t in existing_by_norm:
                        errors.append(
                            f"Tên chuẩn mới '{resolved_target}' đã tồn tại trong danh mục ('{existing_by_norm[norm_t]['name']}'). Hãy chọn Hợp nhất."
                        )
                    if len(approve_name_groups.get(norm_t, [])) > 1:
                        others = [x for x in approve_name_groups[norm_t] if x != pid]
                        errors.append(
                            f"Tên chuẩn mới '{resolved_target}' trùng với mục mới khác trong cùng lô ({', '.join(others)})"
                        )
                resolved_desc = _default_description_for_approval(proposal, resolved_target or orig_name, dec.description)
                if not dec.description.strip():
                    warnings.append(f"Mô tả trống → tự động điền theo chính sách tương thích: '{resolved_desc}'")
            elif dec.action == "merge":
                if not resolved_target:
                    errors.append("Chưa chọn mục đích trong danh mục để hợp nhất")
                else:
                    norm_t = normal(resolved_target)
                    if norm_t not in existing_by_norm:
                        if norm_t in newly_approved_norms:
                            errors.append(
                                f"Không được hợp nhất vào mục '{resolved_target}' vừa tạo mới trong cùng lô"
                            )
                        else:
                            errors.append(
                                f"Mục đích '{resolved_target}' không tồn tại trong danh mục '{req.kind}' hiện tại"
                            )
                    else:
                        resolved_target = existing_by_norm[norm_t]["name"]
                        resolved_def = existing_by_norm[norm_t].get("definition", resolved_def)
                        resolved_desc = existing_by_norm[norm_t].get("description", "")
            elif dec.action == "reject":
                resolved_target = ""

        item_map[pid] = {
            "proposal_id": pid,
            "original_name": orig_name,
            "kind": dec.kind or req.kind,
            "action": dec.action,
            "canonical_name": resolved_target,
            "description": resolved_desc,
            "definition": resolved_def,
            "note": dec.note.strip(),
            "errors": errors,
            "warnings": warnings,
            "affected_node_ids": impact["nodes"],
            "affected_edge_ids": impact["edges"],
            "direct_edge_ids": impact["direct_edges"],
            "indirect_edge_ids": impact["indirect_edges"],
            "impact": impact,
        }

    # 3. Kiểm tra xung đột tác động trên cùng node hoặc cùng cạnh
    def _effective_outcome(pid: str) -> tuple[str, str]:
        it = item_map[pid]
        if it["action"] == "reject":
            return ("reject", "")
        return ("set", normal(it["canonical_name"]))

    batch_pid_set = set(item_map.keys())
    if len(batch_pid_set) > 1:
        for node in work_project.get("nodes", []):
            touching = [pid for pid in node.get("schema_proposal_ids", []) if pid in batch_pid_set]
            if len(touching) > 1:
                outcomes = {_effective_outcome(pid) for pid in touching}
                if len(outcomes) > 1:
                    for pid in touching:
                        msg = (
                            f"Xung đột tác động trên cùng node '{node.get('name', node['id'])}' ({node['id']}) "
                            f"giữa các đề xuất: {', '.join(touching)}"
                        )
                        if msg not in item_map[pid]["errors"]:
                            item_map[pid]["errors"].append(msg)

        nodes_by_id = {n["id"]: n for n in work_project.get("nodes", [])} if req.kind != "relations" else {}
        for edge in work_project.get("edges", []):
            touching = [pid for pid in edge.get("schema_proposal_ids", []) if pid in batch_pid_set]
            if len(touching) <= 1:
                continue
            if req.kind == "relations":
                outcomes = {_effective_outcome(pid) for pid in touching}
                if len(outcomes) > 1:
                    for pid in touching:
                        msg = f"Xung đột tác động trên cùng cạnh '{edge['id']}' giữa các đề xuất quan hệ: {', '.join(touching)}"
                        if msg not in item_map[pid]["errors"]:
                            item_map[pid]["errors"].append(msg)
            else:
                src_node = nodes_by_id.get(edge.get("source"), {})
                tgt_node = nodes_by_id.get(edge.get("target"), {})
                src_pids = set(src_node.get("schema_proposal_ids", []))
                tgt_pids = set(tgt_node.get("schema_proposal_ids", []))
                direct_only_pids = [pid for pid in touching if pid not in src_pids and pid not in tgt_pids]
                if len(direct_only_pids) > 1 or (direct_only_pids and len(touching) > 1):
                    outcomes = {_effective_outcome(pid) for pid in touching}
                    if len(outcomes) > 1:
                        for pid in touching:
                            msg = (
                                f"Xung đột tác động trên cùng cạnh '{edge['id']}' "
                                f"giữa các đề xuất loại thực thể: {', '.join(touching)}"
                            )
                            if msg not in item_map[pid]["errors"]:
                                item_map[pid]["errors"].append(msg)

    item_previews: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0
    valid_nodes: list[str] = []
    valid_edges: list[str] = []
    valid_direct_edges: list[str] = []
    valid_indirect_edges: list[str] = []

    all_nodes: list[str] = []
    all_edges: list[str] = []
    all_direct_edges: list[str] = []
    all_indirect_edges: list[str] = []

    for pid in ordered_unique_pids:
        it = item_map[pid]
        it["valid"] = len(it["errors"]) == 0 and len(batch_errors) == 0
        if it["valid"]:
            valid_count += 1
            valid_nodes.extend(it["affected_node_ids"])
            valid_edges.extend(it["affected_edge_ids"])
            valid_direct_edges.extend(it["direct_edge_ids"])
            valid_indirect_edges.extend(it["indirect_edge_ids"])
        else:
            invalid_count += 1
        all_nodes.extend(it["affected_node_ids"])
        all_edges.extend(it["affected_edge_ids"])
        all_direct_edges.extend(it["direct_edge_ids"])
        all_indirect_edges.extend(it["indirect_edge_ids"])
        item_previews.append(it)

    use_nodes = valid_nodes if valid_count > 0 else all_nodes
    use_edges = valid_edges if valid_count > 0 else all_edges
    use_direct = valid_direct_edges if valid_count > 0 else all_direct_edges
    use_indirect = valid_indirect_edges if valid_count > 0 else all_indirect_edges

    dedup_nodes = list(dict.fromkeys(use_nodes))
    dedup_direct = list(dict.fromkeys(use_direct))
    dedup_direct_set = set(dedup_direct)
    dedup_indirect = [eid for eid in dict.fromkeys(use_indirect) if eid not in dedup_direct_set]
    dedup_edges = list(dict.fromkeys([*dedup_direct, *dedup_indirect, *use_edges]))

    req_hash = compute_decisions_hash(req.project_id or proj_id, req.kind, deduped_decisions)
    can_apply_all = len(batch_errors) == 0 and valid_count > 0 and invalid_count == 0
    can_apply_valid_only = len(batch_errors) == 0 and valid_count > 0 and invalid_count > 0

    return BulkReviewPreviewDTO(
        preview_id=uid(),
        project_id=proj_id or req.project_id,
        kind=req.kind,
        revision=revision,
        catalog_hash=cat_hash,
        request_hash=req_hash,
        locked_proposal_ids=ordered_unique_pids,
        valid_count=valid_count,
        invalid_count=invalid_count,
        item_previews=item_previews,
        batch_errors=batch_errors,
        affected_node_ids=dedup_nodes,
        affected_edge_ids=dedup_edges,
        direct_edge_ids=dedup_direct,
        indirect_edge_ids=dedup_indirect,
        can_apply_all=can_apply_all,
        can_apply_valid_only=can_apply_valid_only,
    )


def apply_proposal_decisions(
    project: dict,
    request: BulkReviewRequestDTO | dict,
    *,
    preview: BulkReviewPreviewDTO | dict | None = None,
    current_model_fingerprint: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, BulkReviewResultDTO]:
    """Xác thực lại và áp dụng lô quyết định trên bản sao dự án."""
    req = BulkReviewRequestDTO.from_dict(request)
    current_rev = compute_project_revision(project)
    current_cat_hash = compute_catalog_hash(project, req.kind if req.kind in ("entity_types", "relations") else None)

    if req.expected_revision and req.expected_revision != current_rev:
        raise ValueError(
            "Trạng thái dự án hoặc danh mục đã thay đổi kể từ lúc xem trước (revision mismatch). Vui lòng xem trước lại."
        )

    fresh_preview = preview_proposal_decisions(
        project,
        req,
        current_model_fingerprint=current_model_fingerprint,
    )

    if preview is not None:
        prev_dto = BulkReviewPreviewDTO.from_dict(preview)
        if prev_dto.revision != current_rev or prev_dto.catalog_hash != current_cat_hash:
            raise ValueError(
                "Bản xem trước đã hết hiệu lực do dữ liệu dự án hoặc danh mục đã thay đổi. Vui lòng xem trước lại."
            )
        if prev_dto.request_hash != fresh_preview.request_hash:
            raise ValueError(
                "Nội dung quyết định đã thay đổi so với bản xem trước. Vui lòng chạy kiểm tra xem trước lại."
            )
        if prev_dto.locked_proposal_ids != fresh_preview.locked_proposal_ids:
            raise ValueError(
                "Tập ID đề xuất không khớp với tập ID đã chốt khi xem trước."
            )

    if fresh_preview.batch_errors:
        raise ValueError("; ".join(fresh_preview.batch_errors))

    if req.apply_mode == "all_or_nothing":
        if fresh_preview.invalid_count > 0:
            raise ValueError(
                f"Lô có {fresh_preview.invalid_count} mục lỗi validation. Không thể áp dụng toàn bộ lô (all_or_nothing)."
            )
        if fresh_preview.valid_count == 0:
            raise ValueError("Không có mục hợp lệ nào để áp dụng.")
    elif req.apply_mode == "valid_only":
        if fresh_preview.valid_count == 0:
            raise ValueError("Không có mục hợp lệ nào trong lô để áp dụng một phần (valid_only).")
    else:
        raise ValueError(f"Chế độ áp dụng không được hỗ trợ: {req.apply_mode}")

    candidate = _clone_project_for_edc_mutation(project)
    batch_id = uid()
    request_id = req.request_id or uid()
    decision_ts = now_iso()

    item_results: list[dict[str, Any]] = []
    applied_ids: list[str] = []
    skipped_ids: list[str] = []
    applied_nodes: list[str] = []
    applied_edges: list[str] = []
    action_counts = {"approve": 0, "merge": 0, "reject": 0}

    proposals_list = candidate["schema_proposals"]
    prop_idx_by_id = {str(p.get("id", "")): idx for idx, p in enumerate(proposals_list)}

    rows = catalog_rows(candidate, req.kind)
    rows_by_norm = {normal(row["name"]): row for row in rows}

    # 1. Gom toàn bộ mục mới cần nạp vào danh mục để validate và cập nhật đúng 1 lần
    new_catalog_rows: list[dict] = []
    for item in fresh_preview.item_previews:
        if item["valid"] and item["action"] == "approve":
            p_idx = prop_idx_by_id.get(item["proposal_id"])
            if p_idx is None:
                continue
            orig_prop = proposals_list[p_idx]
            target_name = item["canonical_name"].strip()
            resolved_desc = _default_description_for_approval(orig_prop, target_name, item["description"])
            new_catalog_rows.append(
                {
                    "name": target_name,
                    "description": resolved_desc,
                    "definition": item["definition"].strip(),
                }
            )

    if new_catalog_rows:
        rows = validate_catalog(rows + new_catalog_rows, req.kind)
        rows_by_norm = {normal(row["name"]): row for row in rows}
        if req.kind == "relations":
            apply_relations(candidate, rows)
        else:
            candidate["entity_types"] = rows

    # 2. Áp dụng quyết định lên từng proposal, thu thập ánh xạ pid -> target_name và tập ảnh hưởng
    pid_to_target: dict[str, str] = {}
    pid_order_rank: dict[str, int] = {}
    status_map = {"approve": "approved", "merge": "merged", "reject": "rejected"}

    for rank_idx, item in enumerate(fresh_preview.item_previews):
        pid = item["proposal_id"]
        if item["valid"]:
            p_idx = prop_idx_by_id.get(pid)
            if p_idx is None:
                raise ValueError("Không tìm thấy đề xuất")
            orig_prop = proposals_list[p_idx]
            previous = copy.deepcopy(orig_prop)
            updated_prop = copy.deepcopy(orig_prop)
            proposals_list[p_idx] = updated_prop

            act = item["action"]
            target_name = item["canonical_name"].strip() if act != "reject" else ""
            if act == "merge":
                matched_row = rows_by_norm.get(normal(target_name))
                if matched_row is None:
                    raise ValueError("Chọn một mục đã có trong danh mục để hợp nhất")
                target_name = matched_row["name"]

            if act != "reject":
                pid_to_target[pid] = target_name
                pid_order_rank[pid] = rank_idx

            updated_prop.update(
                status=status_map[act],
                canonical_name=target_name,
                reviewed_at=decision_ts,
                definition=item["definition"].strip() or updated_prop.get("definition", ""),
                review_note=item["note"].strip(),
                auto_aligned=False,
                decision_origin="human",
                batch_id=batch_id,
            )
            if act == "approve":
                updated_prop["description"] = rows_by_norm[normal(target_name)]["description"]

            impact = item["impact"]
            candidate["schema_decisions"].append(
                {
                    "at": decision_ts,
                    "proposal_id": pid,
                    "action": act,
                    "before": previous,
                    "after": copy.deepcopy(updated_prop),
                    "impact": impact,
                    "batch_id": batch_id,
                    "request_id": request_id,
                    "decision_origin": "human",
                    "actor": req.actor,
                }
            )
            applied_ids.append(pid)
            action_counts[act] = action_counts.get(act, 0) + 1
            applied_nodes.extend(impact["nodes"])
            applied_edges.extend(impact["edges"])
            item_results.append(
                {
                    "proposal_id": pid,
                    "original_name": item["original_name"],
                    "status": "applied",
                    "action": act,
                    "canonical_name": target_name if act != "reject" else item["canonical_name"],
                    "errors": [],
                    "impact": impact,
                }
            )
        else:
            skipped_ids.append(pid)
            item_results.append(
                {
                    "proposal_id": pid,
                    "original_name": item["original_name"],
                    "status": "skipped_invalid",
                    "action": item["action"],
                    "canonical_name": item["canonical_name"],
                    "errors": list(item["errors"]),
                    "impact": item["impact"],
                }
            )

    # 3. Quét 1 lượt duy nhất trên nodes & edges để cập nhật kind/relation và trạng thái Cần kiểm tra
    if req.kind == "entity_types" and pid_to_target:
        nodes_list = candidate["nodes"]
        for idx, node in enumerate(nodes_list):
            best_pid = ""
            best_rank = -1
            for pid in node.get("schema_proposal_ids", []):
                if pid in pid_to_target and pid_order_rank[pid] > best_rank:
                    best_rank = pid_order_rank[pid]
                    best_pid = pid
            if best_pid:
                new_node = dict(node)
                new_node["kind"] = pid_to_target[best_pid]
                nodes_list[idx] = new_node

    affected_nodes_set = set(applied_nodes)
    affected_edges_set = set(applied_edges)
    is_rel_batch = req.kind == "relations" and bool(pid_to_target)

    if affected_nodes_set or affected_edges_set or is_rel_batch:
        edges_list = candidate["edges"]
        for idx, edge in enumerate(edges_list):
            best_rel_pid = ""
            if is_rel_batch:
                best_rank = -1
                for pid in edge.get("schema_proposal_ids", []):
                    if pid in pid_to_target and pid_order_rank[pid] > best_rank:
                        best_rank = pid_order_rank[pid]
                        best_rel_pid = pid

            status_hit = edge["id"] in affected_edges_set or (
                edge.get("source") in affected_nodes_set or edge.get("target") in affected_nodes_set
            )
            if best_rel_pid or status_hit:
                new_edge = dict(edge)
                if best_rel_pid:
                    new_edge["relation"] = pid_to_target[best_rel_pid]
                if status_hit and new_edge.get("status") != STATUS_REJECTED:
                    new_edge.update(status=STATUS_CHECK, reviewed_at="", override=False)
                edges_list[idx] = new_edge

    dedup_nodes = list(dict.fromkeys(applied_nodes))
    dedup_edges = list(dict.fromkeys(applied_edges))
    rev_after = compute_project_revision(candidate)
    full_hash = compute_full_request_hash(req)

    batch_record = {
        "batch_id": batch_id,
        "request_id": request_id,
        "request_hash": full_hash,
        "decisions_hash": fresh_preview.request_hash,
        "at": now_iso(),
        "actor": req.actor,
        "decision_origin": "human",
        "kind": req.kind,
        "apply_mode": req.apply_mode,
        "filter_summary": dict(req.filter_summary),
        "locked_proposal_ids": list(fresh_preview.locked_proposal_ids),
        "applied_ids": applied_ids,
        "skipped_ids": skipped_ids,
        "counts": {
            "approved": action_counts.get("approve", 0),
            "merged": action_counts.get("merge", 0),
            "rejected": action_counts.get("reject", 0),
            "unprocessed": len(skipped_ids),
        },
        "affected_node_ids": dedup_nodes,
        "affected_edge_ids": dedup_edges,
        "revision_before": current_rev,
        "revision_after": rev_after,
        "snapshot_path": "",
        "item_results": copy.deepcopy(item_results),
    }
    candidate.setdefault("schema_decision_batches", []).append(batch_record)

    result = BulkReviewResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=str(candidate.get("project_id") or req.project_id),
        kind=req.kind,
        status="committed",
        apply_mode=req.apply_mode,
        revision_before=current_rev,
        revision_after=rev_after,
        applied_count=len(applied_ids),
        skipped_count=len(skipped_ids),
        invalid_count=len(skipped_ids),
        item_results=item_results,
        affected_node_ids=dedup_nodes,
        affected_edge_ids=dedup_edges,
        snapshot_path="",
        sync_status="synced",
        sync_error="",
        vector_index_status="invalidated" if action_counts.get("approve", 0) > 0 else "valid",
        idempotent_replay=False,
        batch_errors=[],
    )

    if mutate_in_place:
        project.clear()
        project.update(candidate)

    return candidate, result
