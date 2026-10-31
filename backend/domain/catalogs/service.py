"""Quản lý Danh mục, Prompt, Đề xuất EDC và Duyệt Hàng Loạt (Độc lập 100%)."""
from __future__ import annotations

import copy
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
from shared.text_utils import normal, now_iso, sha, uid
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
    """Tính revision phản ánh chính xác trạng thái dự án, danh mục, đề xuất và node/cạnh."""
    snapshot_state = {
        "project_id": str(project.get("project_id", "")),
        "name": str(project.get("name", "")),
        "catalog_hash": compute_catalog_hash(project),
        "proposals": [
            {
                "id": str(p.get("id", "")),
                "kind": str(p.get("kind", "")),
                "name": str(p.get("name", "")),
                "definition": str(p.get("definition", "")),
                "description": str(p.get("description", "")),
                "status": str(p.get("status", "pending")),
                "canonical_name": str(p.get("canonical_name", "")),
                "auto_aligned": bool(p.get("auto_aligned", False)),
                "decision_origin": str(p.get("decision_origin", "")),
            }
            for p in project.get("schema_proposals", [])
        ],
        "nodes": [
            {
                "id": str(n.get("id", "")),
                "name": str(n.get("name", "")),
                "kind": str(n.get("kind", "")),
                "description": str(n.get("description", "")),
                "aliases": list(n.get("aliases", [])),
                "documents": list(n.get("documents", [])),
                "schema_proposal_ids": list(n.get("schema_proposal_ids", [])),
            }
            for n in project.get("nodes", [])
        ],
        "edges": [
            {
                "id": str(e.get("id", "")),
                "source": str(e.get("source", "")),
                "target": str(e.get("target", "")),
                "relation": str(e.get("relation", "")),
                "evidence": str(e.get("evidence", "")),
                "doc_id": str(e.get("doc_id", "")),
                "start_char": e.get("start_char"),
                "end_char": e.get("end_char"),
                "status": str(e.get("status", "")),
                "override": bool(e.get("override", False)),
                "rejection_code": str(e.get("rejection_code", "")),
                "schema_proposal_ids": list(e.get("schema_proposal_ids", [])),
            }
            for e in project.get("edges", [])
        ],
        "node_redirects": dict(project.get("node_redirects") or {}),
        "not_duplicate_pairs_count": len(project.get("not_duplicate_pairs", [])),
        "prompt_bindings": dict(project.get("prompt_bindings") or {}),
        "prompt_version_ids": sorted([v.get("id", "") for v in project.get("prompt_versions", [])]),
    }
    return sha(json.dumps(snapshot_state, ensure_ascii=False, sort_keys=True))[:16]


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
) -> tuple[bool, str]:
    """Kiểm tra xem gợi ý ứng viên của đề xuất có bị cũ (stale) do đổi định nghĩa, catalog hoặc model không."""
    cands = proposal.get("alignment_candidates") or []
    if not cands:
        return False, ""
    kind = proposal.get("kind", "relations")
    cur_cat_hash = compute_catalog_hash(project, kind)
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
    for kind, key in (("relations", "dinh_nghia_quan_he"), ("entity_types", "dinh_nghia_loai")):
        definitions[kind] = {normal(row["ten"]): row["dinh_nghia"].strip() for row in payload.get(key, [])}
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


def schema_review_issue(project: dict, edge: dict) -> str:
    if edge.get("extraction_mode") not in (MODE_EDC, MODE_EDC_PLUS_R):
        return ""
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
    candidate = copy.deepcopy(project)
    proposal = next((p for p in candidate.get("schema_proposals", []) if p["id"] == proposal_id), None)
    if proposal is None:
        raise ValueError("Không tìm thấy đề xuất")
    previous = copy.deepcopy(proposal)
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
        if proposal["kind"] == "relations":
            for edge in candidate["edges"]:
                if proposal_id in edge.get("schema_proposal_ids", []):
                    edge["relation"] = target_name
        else:
            for node in candidate["nodes"]:
                if proposal_id in node.get("schema_proposal_ids", []):
                    node["kind"] = target_name
    affected_nodes = set(impact["nodes"])
    affected_edge_set = set(impact["edges"])
    for edge in candidate["edges"]:
        if edge["id"] in affected_edge_set or (affected_nodes & {edge.get("source"), edge.get("target")}):
            if edge.get("status") != STATUS_REJECTED:
                edge.update(status=STATUS_CHECK, reviewed_at="", override=False)
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
    candidate.setdefault("schema_decisions", []).append(
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
    """Kiểm tra toàn bộ lô quyết định trên bản sao dự án, trả về BulkReviewPreviewDTO."""
    req = BulkReviewRequestDTO.from_dict(request)
    work_project = copy.deepcopy(project)
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

    # 2. Kiểm tra từng dòng và thu thập thông tin để kiểm tra xung đột chéo trong lô
    item_map: dict[str, dict[str, Any]] = {}
    approve_name_groups: dict[str, list[str]] = {}
    newly_approved_norms: set[str] = set()

    for dec in deduped_decisions:
        pid = dec.proposal_id
        proposal = proposals_by_id.get(pid)
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
            impact = {"nodes": [], "edges": [], "direct_edges": [], "indirect_edges": []}
            orig_name = ""
            resolved_desc = dec.description.strip()
            resolved_def = dec.definition.strip()
            resolved_target = dec.canonical_name.strip()
        else:
            orig_name = str(proposal.get("name", ""))
            impact = proposal_impact(work_project, pid)
            prop_kind = str(proposal.get("kind", ""))
            if prop_kind != req.kind or (dec.kind and dec.kind != req.kind):
                errors.append(f"Đề xuất '{orig_name}' thuộc nhóm '{prop_kind}', không khớp bảng '{req.kind}'")
            if proposal.get("status") != "pending":
                errors.append(
                    f"Đề xuất '{orig_name}' đang ở trạng thái '{proposal.get('status')}' (chỉ duyệt hàng loạt mục 'pending')"
                )

            stale, stale_reason = is_proposal_candidates_stale(work_project, proposal, current_model_fingerprint)
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

    nodes_by_id = {n["id"]: n for n in work_project.get("nodes", [])}
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

    candidate = copy.deepcopy(project)
    batch_id = uid()
    request_id = req.request_id or uid()

    item_results: list[dict[str, Any]] = []
    applied_ids: list[str] = []
    skipped_ids: list[str] = []
    applied_nodes: list[str] = []
    applied_edges: list[str] = []
    action_counts = {"approve": 0, "merge": 0, "reject": 0}

    for item in fresh_preview.item_previews:
        pid = item["proposal_id"]
        if item["valid"]:
            impact = decide_proposal(
                candidate,
                pid,
                item["action"],
                canonical_name=item["canonical_name"],
                definition=item["definition"],
                note=item["note"],
                description=item["description"],
                batch_id=batch_id,
                request_id=request_id,
                decision_origin="human",
                actor=req.actor,
            )
            applied_ids.append(pid)
            action_counts[item["action"]] = action_counts.get(item["action"], 0) + 1
            applied_nodes.extend(impact["nodes"])
            applied_edges.extend(impact["edges"])
            item_results.append(
                {
                    "proposal_id": pid,
                    "original_name": item["original_name"],
                    "status": "applied",
                    "action": item["action"],
                    "canonical_name": item["canonical_name"],
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
