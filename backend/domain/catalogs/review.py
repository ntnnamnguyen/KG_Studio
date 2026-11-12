"""Chính sách và thực thi duyệt đề xuất schema (EDC Proposals Review)."""
from __future__ import annotations

import copy
from typing import Any

from backend.domain.catalogs.core import (
    catalog_rows,
    compute_catalog_hash,
    compute_decisions_hash,
    compute_full_request_hash,
    compute_project_revision,
)
from backend.domain.catalogs.proposals import (
    batch_proposal_impacts,
    is_proposal_candidates_stale,
    proposal_impact,
)
from shared.catalog_utils import apply_relations, validate_catalog
from shared.constants import (
    STATUS_CHECK,
    STATUS_REJECTED,
)
from shared.schemas.edc import (
    BulkReviewPreviewDTO,
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
    ProposalDecisionDTO,
)
from shared.text_utils import normal, now_iso, uid


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
