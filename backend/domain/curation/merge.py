"""Xem trước và thực thi gộp N thực thể, bảo toàn cạnh và ánh xạ node_redirects."""
from __future__ import annotations

from collections import Counter
import copy
from difflib import SequenceMatcher
import json
from typing import Any

from backend.domain.catalogs.service import (
    catalog_rows,
    compute_catalog_hash,
    compute_project_revision,
)
from shared.constants import (
    STATUS_APPROVED,
    STATUS_CHECK,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from shared.schemas.curation import (
    CurationResultDTO,
    EntityMergePreviewDTO,
    EntityMergeRequestDTO,
)
from shared.text_utils import normal, now_iso, sha, uid

from .common import clean_aliases, clean_display_text
from .entities import clear_duplicate_suggestions_cache, compute_apparent_duplicate_edge_groups
from .merge_core import (
    DisjointSetUnion,
    consolidate_edge_evidences,
    flatten_redirects,
    group_edges_by_triplet,
    normalize_pair_key,
    rank_representative_edge,
    sort_edges_by_priority,
)


def compute_entity_merge_hash(req: EntityMergeRequestDTO | dict) -> str:
    dto = EntityMergeRequestDTO.from_dict(req)
    payload = {
        "project_id": dto.project_id,
        "member_ids": sorted(dto.member_ids),
        "keep_id": dto.keep_id,
        "canonical_name": clean_display_text(dto.canonical_name),
        "canonical_kind": clean_display_text(dto.canonical_kind),
        "kind_resolution_note": dto.kind_resolution_note.strip(),
        "canonical_description": clean_display_text(dto.canonical_description),
        "aliases": clean_aliases(dto.aliases, dto.canonical_name),
    }
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def preview_entity_merge(
    project: dict,
    request: EntityMergeRequestDTO | dict,
) -> EntityMergePreviewDTO:
    """Xem trước gộp 2 hoặc nhiều thực thể: kiểm tra xung đột loại/mô tả/schema và tính ảnh hưởng cạnh."""
    req = EntityMergeRequestDTO.from_dict(request)
    work_project = copy.deepcopy(project)
    proj_id = str(work_project.get("project_id") or "")
    proj_name = str(work_project.get("name") or "")
    revision = compute_project_revision(work_project)
    cat_hash = compute_catalog_hash(work_project)

    errors: list[str] = []
    warnings: list[str] = []
    if req.project_id and req.project_id not in (proj_id, proj_name):
        errors.append(f"project_id '{req.project_id}' không khớp dự án hiện tại ('{proj_name}')")

    unique_members = list(dict.fromkeys(req.member_ids))
    if len(unique_members) < 2:
        errors.append("Cần chọn ít nhất 2 thực thể khác nhau để thực hiện gộp.")

    nodes_by_id = {str(n.get("id", "")): n for n in work_project.get("nodes", [])}
    missing_ids = [nid for nid in unique_members if nid not in nodes_by_id]
    if missing_ids:
        errors.append(f"Các thực thể không còn tồn tại trong danh sách hoạt động: {', '.join(missing_ids)}")

    keep_id = req.keep_id
    if not keep_id:
        errors.append("Cần chọn rõ một thực thể giữ lại (keep_id); không tự động lấy thực thể đầu tiên.")
    elif keep_id not in unique_members:
        errors.append(f"Thực thể giữ lại '{keep_id}' phải nằm trong danh sách các thực thể đem gộp.")

    member_nodes = [nodes_by_id[nid] for nid in unique_members if nid in nodes_by_id]
    drop_ids = [nid for nid in unique_members if nid != keep_id]

    # Kiểm tra đề xuất schema chưa giải quyết trên các node thành viên
    proposals_by_id = {str(p.get("id", "")): p for p in work_project.get("schema_proposals", [])}
    blocking_pids: list[str] = []
    for node in member_nodes:
        for pid in node.get("schema_proposal_ids", []):
            prop = proposals_by_id.get(str(pid))
            if not prop or prop.get("status") not in ("approved", "merged"):
                if str(pid) not in blocking_pids:
                    blocking_pids.append(str(pid))
    if blocking_pids:
        errors.append(
            f"Các thực thể đem gộp còn vướng {len(blocking_pids)} đề xuất loại thực thể EDC chưa được duyệt tại Trang 4."
        )

    # Kiểm tra xung đột loại thực thể
    distinct_kinds: list[str] = []
    for node in member_nodes:
        k = clean_display_text(str(node.get("kind", "")))
        if k and normal(k) not in {normal(x) for x in distinct_kinds}:
            distinct_kinds.append(k)
    has_kind_conflict = len(distinct_kinds) > 1

    approved_types = {normal(t["name"]): t["name"] for t in catalog_rows(work_project, "entity_types")}
    chosen_kind = clean_display_text(req.canonical_kind)
    if not chosen_kind and len(distinct_kinds) == 1:
        chosen_kind = distinct_kinds[0]

    if has_kind_conflict:
        if not chosen_kind:
            errors.append(f"Có xung đột loại thực thể ({', '.join(distinct_kinds)}). Cần chọn loại chuẩn sau gộp.")
        if not req.kind_resolution_note.strip():
            errors.append("Cần nhập lý do giải quyết xung đột khi gộp các thực thể khác loại.")

    if chosen_kind:
        if normal(chosen_kind) not in approved_types:
            errors.append(f"Loại thực thể sau gộp '{chosen_kind}' phải nằm trong danh mục loại thực thể đã duyệt.")
        else:
            chosen_kind = approved_types[normal(chosen_kind)]
    else:
        errors.append("Chưa xác định loại thực thể sau gộp.")

    # Kiểm tra xung đột mô tả (không tự nối máy móc nếu có từ 2 mô tả khác nhau trở lên)
    distinct_descriptions: list[str] = []
    for node in member_nodes:
        desc = clean_display_text(str(node.get("description", "")))
        if desc and normal(desc) not in {normal(x) for x in distinct_descriptions}:
            distinct_descriptions.append(desc)
    has_description_conflict = len(distinct_descriptions) > 1

    chosen_description = clean_display_text(req.canonical_description)
    if not chosen_description:
        if len(distinct_descriptions) == 1:
            chosen_description = distinct_descriptions[0]
        elif has_description_conflict:
            errors.append("Các thực thể có mô tả khác nhau. Hãy chọn hoặc biên tập mô tả thống nhất thay vì nối tự động.")

    keep_node = nodes_by_id.get(keep_id, member_nodes[0] if member_nodes else {})
    chosen_name = clean_display_text(req.canonical_name) or clean_display_text(str(keep_node.get("name", "")))
    if not chosen_name:
        errors.append("Tên chính của thực thể sau gộp không được rỗng.")

    raw_aliases: list[str] = list(req.aliases) if req.aliases else []
    for node in member_nodes:
        raw_aliases.append(str(node.get("name", "")))
        raw_aliases.extend(str(a) for a in node.get("aliases", []))
    merged_aliases = clean_aliases(raw_aliases, chosen_name)

    merged_docs: list[str] = []
    merged_prop_ids: list[str] = []
    merged_obs: list[dict[str, Any]] = []
    for node in member_nodes:
        for d_id in node.get("documents", []):
            if d_id and d_id not in merged_docs:
                merged_docs.append(d_id)
        for p_id in node.get("schema_proposal_ids", []):
            if p_id and p_id not in merged_prop_ids:
                merged_prop_ids.append(p_id)
        for obs in node.get("edc_observations", []):
            if obs not in merged_obs:
                merged_obs.append(copy.deepcopy(obs))

    merged_node_preview = {
        "id": keep_id,
        "name": chosen_name,
        "kind": chosen_kind,
        "description": chosen_description,
        "aliases": merged_aliases,
        "documents": merged_docs,
        "schema_proposal_ids": merged_prop_ids,
        "edc_observations": merged_obs,
    }

    # Tính toán tác động trên các cạnh (bảo toàn mọi edge ID, không tự xóa cạnh trùng)
    drop_set = set(drop_ids)
    member_set = set(unique_members)
    kind_changed_by_member = {
        nid: normal(nodes_by_id[nid].get("kind", "")) != normal(chosen_kind)
        for nid in unique_members
        if nid in nodes_by_id
    }
    affected_edge_count = 0
    changed_endpoint_count = 0
    invalidated_approved_count = 0
    new_self_loop_ids: list[str] = []
    edge_changes: list[dict[str, Any]] = []
    simulated_edges: list[dict[str, Any]] = []

    for edge in work_project.get("edges", []):
        sim_edge = copy.deepcopy(edge)
        old_src = str(edge.get("source", ""))
        old_tgt = str(edge.get("target", ""))
        was_self = old_src == old_tgt
        src_changed = old_src in drop_set
        tgt_changed = old_tgt in drop_set
        endpoint_kind_changed = (old_src in member_set and kind_changed_by_member.get(old_src, False)) or (
            old_tgt in member_set and kind_changed_by_member.get(old_tgt, False)
        )

        if src_changed or tgt_changed or endpoint_kind_changed:
            if src_changed or tgt_changed:
                affected_edge_count += 1
                changed_endpoint_count += (1 if src_changed else 0) + (1 if tgt_changed else 0)
            new_src = keep_id if src_changed else old_src
            new_tgt = keep_id if tgt_changed else old_tgt
            sim_edge["source"] = new_src
            sim_edge["target"] = new_tgt

            became_self_loop = (new_src == new_tgt) and not was_self
            if became_self_loop:
                new_self_loop_ids.append(str(edge["id"]))

            old_status = str(edge.get("status", STATUS_PENDING))
            if old_status == STATUS_REJECTED:
                new_status = STATUS_REJECTED
            elif became_self_loop or endpoint_kind_changed:
                new_status = STATUS_CHECK
                if old_status == STATUS_APPROVED:
                    invalidated_approved_count += 1
            else:
                new_status = old_status
            sim_edge["status"] = new_status

            edge_changes.append(
                {
                    "edge_id": str(edge["id"]),
                    "relation": str(edge.get("relation", "")),
                    "source_before": old_src,
                    "target_before": old_tgt,
                    "source_after": new_src,
                    "target_after": new_tgt,
                    "endpoints_changed": (1 if src_changed else 0) + (1 if tgt_changed else 0),
                    "status_before": old_status,
                    "status_after": new_status,
                    "became_self_loop": became_self_loop,
                    "endpoint_kind_changed": endpoint_kind_changed,
                    "evidence": str(edge.get("evidence", "")),
                }
            )
        simulated_edges.append(sim_edge)

    dup_groups = [
        g
        for g in compute_apparent_duplicate_edge_groups(simulated_edges)
        if g["source"] == keep_id or g["target"] == keep_id
    ]
    if new_self_loop_ids:
        warnings.append(
            f"Phát sinh {len(new_self_loop_ids)} cạnh tự nối mới (self-loop); các cạnh này sẽ được giữ lại ở trạng thái Cần kiểm tra."
        )
    if dup_groups:
        warnings.append(
            f"Có {len(dup_groups)} nhóm cạnh cùng bộ ba (nguồn – quan hệ – đích) sau khi gộp; mọi ID và bằng chứng đều được giữ nguyên."
        )

    req_hash = compute_entity_merge_hash(req)
    return EntityMergePreviewDTO(
        preview_id=uid(),
        project_id=proj_id or req.project_id,
        revision=revision,
        catalog_hash=cat_hash,
        request_hash=req_hash,
        member_ids=unique_members,
        keep_id=keep_id,
        drop_ids=drop_ids,
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        blocking_proposal_ids=blocking_pids,
        has_kind_conflict=has_kind_conflict,
        distinct_kinds=distinct_kinds,
        has_description_conflict=has_description_conflict,
        distinct_descriptions=distinct_descriptions,
        merged_node_preview=merged_node_preview,
        affected_edge_count=affected_edge_count,
        changed_endpoint_count=changed_endpoint_count,
        invalidated_approved_count=invalidated_approved_count,
        new_self_loop_ids=new_self_loop_ids,
        apparent_duplicate_groups=dup_groups,
        edge_changes=edge_changes,
    )


def apply_entity_merge(
    project: dict,
    request: EntityMergeRequestDTO | dict,
    *,
    preview: EntityMergePreviewDTO | dict | None = None,
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Thực thi gộp N thực thể thành 1 an toàn:
    - Bảo toàn 100% edge ID và bằng chứng (không tự xóa cạnh trùng).
    - Chuyển mọi cạnh đổi đầu mút về Cần kiểm tra (trừ cạnh đang Loại bỏ).
    - Cập nhật bảng ánh xạ node_redirects không tạo vòng lặp.
    """
    req = EntityMergeRequestDTO.from_dict(request)
    current_rev = compute_project_revision(project)
    current_cat_hash = compute_catalog_hash(project)

    if req.expected_revision and req.expected_revision != current_rev:
        raise ValueError(
            "Trạng thái dự án đã thay đổi bởi phiên khác kể từ lúc xem trước (revision mismatch). Vui lòng tải lại và xem trước lại."
        )

    fresh_preview = preview_entity_merge(project, req)
    if preview is not None:
        prev_dto = EntityMergePreviewDTO.from_dict(preview)
        if prev_dto.revision != current_rev or prev_dto.catalog_hash != current_cat_hash:
            raise ValueError("Bản xem trước gộp thực thể đã hết hiệu lực do dữ liệu dự án hoặc danh mục đã thay đổi.")
        if prev_dto.request_hash != fresh_preview.request_hash:
            raise ValueError("Thông tin cấu hình gộp đã thay đổi so với bản xem trước. Vui lòng xem trước lại.")

    if not fresh_preview.valid:
        raise ValueError("; ".join(fresh_preview.errors))

    candidate = copy.deepcopy(project)
    keep_id = fresh_preview.keep_id
    drop_ids = fresh_preview.drop_ids
    drop_set = set(drop_ids)

    nodes_by_id = {str(n["id"]): n for n in candidate.get("nodes", [])}
    original_members = [copy.deepcopy(nodes_by_id[nid]) for nid in fresh_preview.member_ids if nid in nodes_by_id]
    original_kinds_by_member = {
        nid: str(nodes_by_id[nid].get("kind", ""))
        for nid in fresh_preview.member_ids
        if nid in nodes_by_id
    }
    member_set = set(fresh_preview.member_ids)
    target_node = nodes_by_id[keep_id]

    preview_node = fresh_preview.merged_node_preview
    target_node["name"] = preview_node["name"]
    target_node["kind"] = preview_node["kind"]
    target_node["description"] = preview_node["description"]
    target_node["aliases"] = list(preview_node["aliases"])
    target_node["documents"] = list(preview_node["documents"])
    if preview_node.get("schema_proposal_ids"):
        target_node["schema_proposal_ids"] = list(preview_node["schema_proposal_ids"])
    if preview_node.get("edc_observations"):
        target_node["edc_observations"] = copy.deepcopy(preview_node["edc_observations"])

    merge_time = now_iso()
    merged_from = list(target_node.get("merged_from", []))
    for d_id in drop_ids:
        dropped = nodes_by_id[d_id]
        merged_from.append(
            {
                "id": d_id,
                "name": dropped.get("name", ""),
                "kind": dropped.get("kind", ""),
                "description": dropped.get("description", ""),
                "aliases": list(dropped.get("aliases", [])),
                "documents": list(dropped.get("documents", [])),
                "at": merge_time,
            }
        )
    target_node["merged_from"] = merged_from

    affected_edge_ids: list[str] = []
    changed_endpoints = 0
    for edge in candidate.get("edges", []):
        old_src = str(edge.get("source", ""))
        old_tgt = str(edge.get("target", ""))
        was_self = old_src == old_tgt
        src_changed = old_src in drop_set
        tgt_changed = old_tgt in drop_set
        endpoint_kind_changed = (
            old_src in member_set and normal(original_kinds_by_member.get(old_src, "")) != normal(preview_node["kind"])
        ) or (
            old_tgt in member_set and normal(original_kinds_by_member.get(old_tgt, "")) != normal(preview_node["kind"])
        )
        if not (src_changed or tgt_changed or endpoint_kind_changed):
            continue

        before_edge = copy.deepcopy(edge)
        if src_changed or tgt_changed:
            affected_edge_ids.append(str(edge["id"]))
            changed_endpoints += (1 if src_changed else 0) + (1 if tgt_changed else 0)

        edge.setdefault("endpoint_history", []).append(
            {
                "at": merge_time,
                "source_before": old_src,
                "target_before": old_tgt,
                "status_before": edge.get("status", ""),
                "reviewed_at_before": edge.get("reviewed_at", ""),
                "override_before": bool(edge.get("override", False)),
            }
        )
        if src_changed:
            edge["source"] = keep_id
        if tgt_changed:
            edge["target"] = keep_id

        became_self = (edge["source"] == edge["target"]) and not was_self
        if became_self:
            edge["self_loop_after_merge"] = True
            edge["self_loop_confirmed"] = False
            self_note = f"[Cần kiểm tra: Tự nối phát sinh sau khi gộp thực thể vào {keep_id}]"
            if self_note not in str(edge.get("review_note", "")):
                edge["review_note"] = (str(edge.get("review_note", "")) + "\n" + self_note).strip()

        # Ma trận mục 8.2: Gộp cùng loại không sinh tự nối thì giữ nguyên trạng thái cạnh hợp lệ;
        # nếu phát sinh tự nối hoặc đổi loại thực thể đầu mút thì chuyển về Cần kiểm tra.
        if (became_self or endpoint_kind_changed) and edge.get("status") != STATUS_REJECTED:
            edge["status"] = STATUS_CHECK
            edge["reviewed_at"] = ""
            edge["override"] = False
            edge["override_reason"] = ""

        candidate.setdefault("curation_history", []).append(
            {
                "id": uid(),
                "at": merge_time,
                "actor": req.actor,
                "decision_origin": "human",
                "action": "edge_endpoint_remapped_by_merge",
                "target_id": str(edge["id"]),
                "before": before_edge,
                "after": copy.deepcopy(edge),
                "note": f"Đổi đầu mút do gộp thực thể vào {keep_id}",
            }
        )

    # Cập nhật bảng ánh xạ node_redirects phẳng, không tạo vòng lặp
    redirects: dict[str, str] = dict(candidate.get("node_redirects") or {})
    for old_k, old_v in list(redirects.items()):
        if old_v in drop_set:
            redirects[old_k] = keep_id
    for d_id in drop_ids:
        redirects[d_id] = keep_id
    redirects.pop(keep_id, None)
    candidate["node_redirects"] = redirects

    # Loại các node đã gộp khỏi danh sách node hoạt động (nhưng giữ toàn bộ edges!)
    candidate["nodes"] = [n for n in candidate.get("nodes", []) if str(n.get("id", "")) not in drop_set]

    merged_dup_count = 0
    if getattr(req, "collapse_edges", False):
        _, merged_dup_count, _ = collapse_duplicate_edges(
            candidate,
            actor=req.actor,
            note=f"Tự động hợp nhất cạnh trùng sau khi gộp thực thể về '{req.canonical_name or keep_id}'",
            mutate_in_place=True,
        )

    batch_id = uid()
    request_id = req.request_id or uid()
    rev_after = compute_project_revision(candidate)

    merge_record = {
        "merge_id": batch_id,
        "request_id": request_id,
        "request_hash": fresh_preview.request_hash,
        "at": merge_time,
        "actor": req.actor,
        "keep_id": keep_id,
        "drop_ids": drop_ids,
        "member_ids": fresh_preview.member_ids,
        "original_members": original_members,
        "merged_node": copy.deepcopy(target_node),
        "kind_resolution_note": req.kind_resolution_note.strip(),
        "note": req.note.strip(),
        "affected_edge_ids": affected_edge_ids,
        "changed_endpoint_count": changed_endpoints,
        "merged_duplicate_edges": merged_dup_count,
        "new_self_loop_ids": fresh_preview.new_self_loop_ids,
        "apparent_duplicate_groups": fresh_preview.apparent_duplicate_groups,
        "node_redirects_added": {d_id: keep_id for d_id in drop_ids},
        "revision_before": current_rev,
        "revision_after": rev_after,
        "snapshot_path": "",
    }
    candidate.setdefault("entity_merges", []).append(merge_record)
    candidate.setdefault("curation_history", []).append(
        {
            "id": batch_id,
            "batch_id": batch_id,
            "request_id": request_id,
            "at": merge_time,
            "actor": req.actor,
            "decision_origin": "human",
            "action": "merge_entities",
            "target_id": keep_id,
            "before": original_members,
            "after": copy.deepcopy(target_node),
            "note": req.note.strip() or req.kind_resolution_note.strip(),
        }
    )

    result = CurationResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=str(candidate.get("project_id") or req.project_id),
        operation="entity_merge",
        status="committed",
        apply_mode="all_or_nothing",
        revision_before=current_rev,
        revision_after=rev_after,
        applied_ids=[keep_id, *drop_ids],
        skipped_ids=[],
        applied_count=len(fresh_preview.member_ids),
        skipped_count=0,
        item_results=[merge_record],
        affected_edge_ids=affected_edge_ids,
        changed_endpoint_count=changed_endpoints,
        merged_duplicate_edges=merged_dup_count,
    )

    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)
    clear_duplicate_suggestions_cache()
    clear_relation_duplicate_suggestions_cache()
    return candidate, result


def merge_nodes(
    project: dict,
    keep: str,
    drop: str,
    *,
    canonical_kind: str = "",
    kind_resolution_note: str = "",
    canonical_description: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Hàm tương thích cho gộp 2 thực thể: sử dụng quy tắc bảo toàn dữ liệu mới (không tự xóa cạnh trùng, trả riêng số cạnh duy nhất và số đầu mút đổi)."""
    if keep == drop:
        return {"ok": False, "reason": "Hai thực thể phải khác nhau"}
    nodes = {str(n["id"]): n for n in project.get("nodes", [])}
    if keep not in nodes or drop not in nodes:
        return {"ok": False, "reason": "Không tìm thấy thực thể cần gộp"}

    keep_node = nodes[keep]
    drop_node = nodes[drop]
    eff_kind = canonical_kind or keep_node.get("kind", "")
    eff_kind_note = kind_resolution_note or "Chọn loại của thực thể giữ lại"
    if keep_node.get("description") and drop_node.get("description") and normal(keep_node["description"]) != normal(drop_node["description"]):
        eff_desc = canonical_description or f"{keep_node['description']}\n{drop_node['description']}".strip()
    else:
        eff_desc = canonical_description or keep_node.get("description") or drop_node.get("description") or ""

    req = EntityMergeRequestDTO(
        project_id=str(project.get("project_id", "")),
        member_ids=[keep, drop],
        keep_id=keep,
        canonical_name=keep_node.get("name", ""),
        canonical_kind=eff_kind,
        kind_resolution_note=eff_kind_note,
        canonical_description=eff_desc,
        note=note,
        expected_revision=compute_project_revision(project),
        request_id=uid(),
    )
    try:
        preview = preview_entity_merge(project, req)
        if not preview.valid:
            return {"ok": False, "reason": "; ".join(preview.errors), "preview": preview.to_dict()}
        _, result = apply_entity_merge(project, req, preview=preview, mutate_in_place=True)
        return {
            "ok": True,
            "affected_edges": len(result.affected_edge_ids),
            "changed_endpoints": result.changed_endpoint_count,
            "self_loops": len(preview.new_self_loop_ids),
            "apparent_duplicate_groups": len(preview.apparent_duplicate_groups),
            "merged_duplicate_edges": 0,
            "removed_node": drop,
            "kept_node": keep,
            "batch_id": result.batch_id,
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _clone_project_for_merge_mutation(project: dict) -> dict:
    """Tạo bản sao có mục tiêu cho gộp thực thể / quan hệ / cạnh trùng (tránh copy.deepcopy văn bản tài liệu lớn)."""
    candidate = dict(project)
    candidate["nodes"] = list(project.get("nodes", []))
    candidate["edges"] = list(project.get("edges", []))
    candidate["node_redirects"] = dict(project.get("node_redirects") or {})
    candidate["edge_redirects"] = dict(project.get("edge_redirects") or {})
    candidate["relation_redirects"] = dict(project.get("relation_redirects") or {})
    candidate["relation_aliases"] = copy.deepcopy(project.get("relation_aliases") or {})
    if project.get("relation_types") is not None:
        candidate["relation_types"] = [copy.deepcopy(r) for r in project.get("relation_types", [])]
    candidate["relation_notes"] = copy.deepcopy(project.get("relation_notes") or {})
    candidate["relations"] = list(project.get("relations", []))
    candidate["schema_proposals"] = list(project.get("schema_proposals", []))
    candidate["entity_merges"] = list(project.get("entity_merges", []))
    candidate["relation_merges"] = list(project.get("relation_merges", []))
    candidate["curation_history"] = list(project.get("curation_history", []))
    return candidate


def apply_bulk_entity_merges(
    project: dict,
    pairs: list[dict | tuple[str, str]],
    *,
    collapse_edges: bool = False,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Gộp hàng loạt N cặp thực thể nghi trùng.
    Tự động gom các cặp giao nhau thành các cụm (connected components/DSU)
    và chọn thực thể có bậc liên kết cao nhất làm đại diện (keep_id).
    Bảo toàn 100% ID cạnh, bằng chứng và cập nhật node_redirects phẳng.
    """
    if not pairs:
        raise ValueError("Danh sách cặp thực thể cần gộp trống.")

    candidate = _clone_project_for_merge_mutation(project)
    rev_before = compute_project_revision(candidate)
    nodes_list = candidate["nodes"]
    node_idx_by_id = {str(n["id"]).strip(): idx for idx, n in enumerate(nodes_list) if n.get("id")}
    nodes_by_id = {nid: nodes_list[idx] for nid, idx in node_idx_by_id.items()}
    edges = candidate["edges"]

    degs: dict[str, int] = {}
    for e in edges:
        s = str(e.get("source", "")).strip()
        t = str(e.get("target", "")).strip()
        degs[s] = degs.get(s, 0) + 1
        degs[t] = degs.get(t, 0) + 1

    normalized_pairs: list[tuple[str, str]] = []
    for p in pairs:
        if isinstance(p, (tuple, list)) and len(p) >= 2:
            a, b = str(p[0]).strip(), str(p[1]).strip()
        elif isinstance(p, dict):
            a = str(p.get("keep_id") or p.get("node_a_id") or (p.get("node_a", {}) or {}).get("id") or "").strip()
            b = str(p.get("drop_id") or p.get("node_b_id") or (p.get("node_b", {}) or {}).get("id") or "").strip()
        else:
            continue
        if a and b and a != b and a in nodes_by_id and b in nodes_by_id:
            normalized_pairs.append((a, b))

    if not normalized_pairs:
        raise ValueError(
            "Không có cặp thực thể hợp lệ nào tồn tại trong đồ thị để gộp "
            "(các cặp được chọn có thể bị trùng ID với chính nó hoặc các thực thể này đã được gộp trong phiên trước)."
        )

    # Gom cụm sử dụng DisjointSetUnion dùng chung
    dsu = DisjointSetUnion()
    for a, b in normalized_pairs:
        dsu.union(a, b)

    clusters_by_root: dict[str, set[str]] = {}
    for a, b in normalized_pairs:
        clusters_by_root.setdefault(dsu.find(a), set()).add(a)
        clusters_by_root.setdefault(dsu.find(b), set()).add(b)

    total_applied_clusters = 0
    all_dropped_ids: list[str] = []
    all_affected_edge_ids: set[str] = set()
    total_changed_endpoints = 0
    merge_time = now_iso()
    batch_id = uid()
    request_id = uid()

    drop_to_keep: dict[str, str] = {}

    for root, member_ids in clusters_by_root.items():
        if len(member_ids) < 2:
            continue
        sorted_members = sorted(
            list(member_ids),
            key=lambda nid: (
                degs.get(nid, 0),
                len(nodes_by_id[nid].get("documents", [])),
                len(nodes_by_id[nid].get("aliases", [])),
            ),
            reverse=True,
        )
        keep_id = sorted_members[0]
        drop_ids = sorted_members[1:]
        keep_node = copy.deepcopy(nodes_by_id[keep_id])
        nodes_list[node_idx_by_id[keep_id]] = keep_node
        nodes_by_id[keep_id] = keep_node
        all_dropped_ids.extend(drop_ids)

        raw_aliases: list[str] = list(keep_node.get("aliases", []))
        merged_docs = list(keep_node.get("documents", []))
        merged_props = list(keep_node.get("schema_proposal_ids", []))
        merged_obs = list(keep_node.get("edc_observations", []))
        merged_from = list(keep_node.get("merged_from", []))

        for d_id in drop_ids:
            drop_to_keep[d_id] = keep_id
            d_node = nodes_by_id[d_id]
            raw_aliases.append(str(d_node.get("name", "")))
            raw_aliases.extend(str(a) for a in d_node.get("aliases", []))
            for doc_id in d_node.get("documents", []):
                if doc_id and doc_id not in merged_docs:
                    merged_docs.append(doc_id)
            for p_id in d_node.get("schema_proposal_ids", []):
                if p_id and p_id not in merged_props:
                    merged_props.append(p_id)
            for obs in d_node.get("edc_observations", []):
                if obs not in merged_obs:
                    merged_obs.append(copy.deepcopy(obs))
            merged_from.append(
                {
                    "id": d_id,
                    "name": d_node.get("name", ""),
                    "kind": d_node.get("kind", ""),
                    "description": d_node.get("description", ""),
                    "aliases": list(d_node.get("aliases", [])),
                    "documents": list(d_node.get("documents", [])),
                    "at": merge_time,
                    "batch_id": batch_id,
                }
            )

        keep_node["aliases"] = clean_aliases(raw_aliases, keep_node.get("name", ""))
        keep_node["documents"] = merged_docs
        keep_node["schema_proposal_ids"] = list(dict.fromkeys(merged_props))
        keep_node["edc_observations"] = merged_obs
        keep_node["merged_from"] = merged_from
        total_applied_clusters += 1

    if drop_to_keep:
        redirects = candidate.setdefault("node_redirects", {})
        for old_id, target in list(redirects.items()):
            if target in drop_to_keep:
                redirects[old_id] = drop_to_keep[target]
        redirects.update(drop_to_keep)

        for idx, edge in enumerate(edges):
            src = str(edge.get("source", ""))
            tgt = str(edge.get("target", ""))
            src_changed = src in drop_to_keep
            tgt_changed = tgt in drop_to_keep
            if src_changed or tgt_changed:
                new_edge = dict(edge)
                all_affected_edge_ids.add(str(new_edge["id"]))
                total_changed_endpoints += (1 if src_changed else 0) + (1 if tgt_changed else 0)
                if src_changed:
                    new_edge["source"] = drop_to_keep[src]
                if tgt_changed:
                    new_edge["target"] = drop_to_keep[tgt]
                if new_edge["source"] == new_edge["target"]:
                    new_edge["status"] = STATUS_CHECK
                    new_edge["self_loop_confirmed"] = False
                edges[idx] = new_edge

    dropped_set = set(all_dropped_ids)
    candidate["nodes"] = [n for n in candidate.get("nodes", []) if str(n.get("id")) not in dropped_set]

    merged_dup_count = 0
    if collapse_edges:
        _, merged_dup_count, _ = collapse_duplicate_edges(
            candidate,
            actor=actor,
            note=f"Tự động hợp nhất cạnh trùng sau khi gộp hàng loạt {len(normalized_pairs)} cặp thực thể",
            mutate_in_place=True,
        )

    candidate.setdefault("entity_merges", []).append(
        {
            "merge_id": batch_id,
            "request_id": request_id,
            "at": merge_time,
            "actor": actor,
            "is_bulk": True,
            "clusters_count": total_applied_clusters,
            "dropped_count": len(all_dropped_ids),
            "affected_edge_count": len(all_affected_edge_ids),
            "changed_endpoint_count": total_changed_endpoints,
            "merged_duplicate_edges": merged_dup_count,
            "note": note or f"Gộp hàng loạt {len(normalized_pairs)} cặp thực thể qua {total_applied_clusters} cụm.",
        }
    )

    rev_after = compute_project_revision(candidate)
    result = CurationResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=str(candidate.get("project_id") or project.get("name") or ""),
        operation="bulk_entity_merge",
        status="applied",
        apply_mode="all_or_nothing",
        revision_before=rev_before,
        revision_after=rev_after,
        applied_ids=list(all_dropped_ids),
        skipped_ids=[],
        applied_count=len(all_dropped_ids),
        skipped_count=0,
        item_results=[{"cluster_root": r, "members": list(m)} for r, m in clusters_by_root.items()],
        affected_edge_ids=list(all_affected_edge_ids),
        changed_endpoint_count=total_changed_endpoints,
        merged_duplicate_edges=merged_dup_count,
    )
    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)
    clear_duplicate_suggestions_cache()
    clear_relation_duplicate_suggestions_cache()
    return candidate, result


_RELATION_DUPLICATE_SUGGESTIONS_CACHE: dict[tuple[str, str, float], list[dict[str, Any]]] = {}


def clear_relation_duplicate_suggestions_cache() -> None:
    """Xóa bộ nhớ đệm gợi ý quan hệ nghi trùng."""
    _RELATION_DUPLICATE_SUGGESTIONS_CACHE.clear()


def relation_duplicate_suggestions(
    project: dict,
    fuzzy_threshold: float = 0.75,
    *,
    include_dismissed: bool = False,
) -> list[dict[str, Any]]:
    """Phát hiện các cặp quan hệ nghi trùng hoặc tương đồng cao trong đồ thị và danh mục."""
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    rev = compute_project_revision(project)
    cache_key = (proj_id, rev, float(fuzzy_threshold))

    if cache_key not in _RELATION_DUPLICATE_SUGGESTIONS_CACHE:
        redirects = project.get("relation_redirects", {})
        edges = project.get("edges", [])
        edge_counts = Counter(str(e.get("relation", "")).strip() for e in edges if e.get("relation"))
        catalog_rels = {
            str(r.get("name", "")).strip() if isinstance(r, dict) else str(r).strip()
            for r in (project.get("relation_types") or []) + (project.get("relations") or [])
            if (isinstance(r, dict) and r.get("name")) or (isinstance(r, str) and r.strip())
        }

        # Loại trừ quan hệ đã bị gộp (redirects) hoặc không còn cạnh nào trong đồ thị (và không thuộc catalog)
        all_rels_set = {
            r for r in (set(edge_counts.keys()) | catalog_rels)
            if r and r not in redirects and (edge_counts.get(r, 0) > 0 or r in catalog_rels)
        }
        all_rels = sorted(all_rels_set)
        n_rels = len(all_rels)
        norms = [normal(r) for r in all_rels]
        cleans = [n_val.replace("_", " ").strip() for n_val in norms]
        words_list = [set(c_val.split()) for c_val in cleans]

        candidate_pairs: set[tuple[int, int]] | None = None
        if n_rels >= 120:
            candidate_pairs = set()
            clean_buckets: dict[str, list[int]] = {}
            fourgram_buckets: dict[str, set[int]] = {}
            word_buckets: dict[str, list[int]] = {}
            word_pair_buckets: dict[tuple[str, str], list[int]] = {}
            prefix3_buckets: dict[str, list[int]] = {}

            for idx, c_val in enumerate(cleans):
                if not c_val:
                    continue
                clean_buckets.setdefault(c_val, []).append(idx)
                if len(c_val) >= 3:
                    prefix3_buckets.setdefault(c_val[:3], []).append(idx)
                if len(c_val) >= 4:
                    for pos in range(len(c_val) - 3):
                        fourgram_buckets.setdefault(c_val[pos : pos + 4], set()).add(idx)

                w_sorted = sorted(words_list[idx])
                for tok in w_sorted:
                    if len(tok) >= 2:
                        word_buckets.setdefault(tok, []).append(idx)
                if len(w_sorted) >= 2:
                    for wi in range(len(w_sorted)):
                        for wj in range(wi + 1, len(w_sorted)):
                            word_pair_buckets.setdefault((w_sorted[wi], w_sorted[wj]), []).append(idx)

            def _add_cand(a_i: int, b_i: int) -> None:
                if a_i != b_i:
                    candidate_pairs.add((a_i, b_i) if a_i < b_i else (b_i, a_i))  # type: ignore[union-attr]

            # 1. Exact clean / norm matches
            for bucket in clean_buckets.values():
                if len(bucket) > 1:
                    for bi in range(len(bucket)):
                        for bj in range(bi + 1, len(bucket)):
                            _add_cand(bucket[bi], bucket[bj])

            # 2. Exact substring matches (100% recall via first-4gram & last-4gram intersection)
            for idx, c_val in enumerate(cleans):
                if len(c_val) >= 4:
                    head_set = fourgram_buckets.get(c_val[:4])
                    tail_set = fourgram_buckets.get(c_val[-4:])
                    if head_set and tail_set:
                        small, large = (head_set, tail_set) if len(head_set) <= len(tail_set) else (tail_set, head_set)
                        for other_idx in small:
                            if other_idx != idx and other_idx in large and len(cleans[other_idx]) >= len(c_val):
                                _add_cand(idx, other_idx)

            # 3. Word-pair overlap (100% recall for Jaccard >= 0.65 when |W| >= 2)
            for bucket in word_pair_buckets.values():
                if 1 < len(bucket) <= 250:
                    for bi in range(len(bucket)):
                        for bj in range(bi + 1, len(bucket)):
                            _add_cand(bucket[bi], bucket[bj])

            # 4. Shared token & 3-char prefix buckets for high character similarity
            for bucket in word_buckets.values():
                if 1 < len(bucket) <= 80:
                    for bi in range(len(bucket)):
                        for bj in range(bi + 1, len(bucket)):
                            _add_cand(bucket[bi], bucket[bj])
            for bucket in prefix3_buckets.values():
                if 1 < len(bucket) <= 80:
                    for bi in range(len(bucket)):
                        for bj in range(bi + 1, len(bucket)):
                            _add_cand(bucket[bi], bucket[bj])

        pair_iter = (
            sorted(candidate_pairs)
            if candidate_pairs is not None
            else ((i, j) for i in range(n_rels) for j in range(i + 1, n_rels))
        )

        pairs: list[dict[str, Any]] = []

        for i, j in pair_iter:
            r1 = all_rels[i]
            r2 = all_rels[j]

            # Nếu quan hệ đã được gộp/chuyển hướng về nhau hoặc về cùng một đích -> bỏ qua
            if r1 in redirects or r2 in redirects:
                continue
            if redirects.get(r1) == r2 or redirects.get(r2) == r1:
                continue
            if redirects.get(r1) and redirects.get(r1) == redirects.get(r2):
                continue

            norm_1 = norms[i]
            norm_2 = norms[j]
            clean_1 = cleans[i]
            clean_2 = cleans[j]

            reasons: list[str] = []
            score = 0.0

            if norm_1 == norm_2:
                reasons.append("Trùng tên chuẩn hóa")
                score = 1.0
            elif clean_1 == clean_2:
                reasons.append("Trùng tên khi chuẩn hóa khoảng trắng/gạch dưới")
                score = 0.98
            else:
                is_sub = min(len(clean_1), len(clean_2)) >= 4 and (clean_1 in clean_2 or clean_2 in clean_1)
                sm = SequenceMatcher(None, clean_1, clean_2)
                if is_sub:
                    ratio = sm.ratio()
                    reasons.append("Chứa nhau (tiền tố/hậu tố)")
                    score = max(0.85, ratio)
                elif sm.real_quick_ratio() >= fuzzy_threshold and sm.quick_ratio() >= fuzzy_threshold:
                    ratio = sm.ratio()
                    if ratio >= fuzzy_threshold:
                        reasons.append(f"Độ giống tên cao ({ratio:.2f})")
                        score = ratio

                w1 = words_list[i]
                w2 = words_list[j]
                if w1 and w2:
                    inter_len = len(w1 & w2)
                    if inter_len > 0:
                        union_len = len(w1) + len(w2) - inter_len
                        jaccard = inter_len / union_len
                        if jaccard >= 0.65 and jaccard > score:
                            reasons.append(f"Trùng {inter_len}/{union_len} từ khóa")
                            score = max(score, jaccard)

            if reasons and score >= fuzzy_threshold:
                cnt_1 = edge_counts.get(r1, 0)
                cnt_2 = edge_counts.get(r2, 0)

                # Ưu tiên quan hệ có nhiều cạnh hơn làm đích
                if cnt_1 > cnt_2:
                    target = r1
                    source = r2
                elif cnt_2 > cnt_1:
                    target = r2
                    source = r1
                elif r1 in catalog_rels and r2 not in catalog_rels:
                    target = r1
                    source = r2
                elif r2 in catalog_rels and r1 not in catalog_rels:
                    target = r2
                    source = r1
                else:
                    target = r1 if len(r1) >= len(r2) else r2
                    source = r2 if target == r1 else r1

                pair_fp = sha(f"{min(norm_1, norm_2)}::{max(norm_1, norm_2)}")[:16]
                pairs.append(
                    {
                        "pair_key": f"{r1} ↔ {r2}",
                        "pair_fingerprint": pair_fp,
                        "relation_a": r1,
                        "relation_b": r2,
                        "count_a": cnt_1,
                        "count_b": cnt_2,
                        "target": target,
                        "source": source,
                        "suggested_target": target,
                        "suggested_drop": source,
                        "score": round(score, 2),
                        "reason": "; ".join(reasons),
                    }
                )

        pairs.sort(key=lambda x: -x["score"])
        if len(_RELATION_DUPLICATE_SUGGESTIONS_CACHE) > 32:
            _RELATION_DUPLICATE_SUGGESTIONS_CACHE.clear()
        _RELATION_DUPLICATE_SUGGESTIONS_CACHE[cache_key] = pairs

    all_pairs = [dict(p) for p in _RELATION_DUPLICATE_SUGGESTIONS_CACHE[cache_key]]
    dismissed_map = {
        normalize_pair_key(rec.get("relation_a", ""), rec.get("relation_b", ""))
        for rec in project.get("not_duplicate_relation_pairs", [])
    }

    if include_dismissed:
        return all_pairs
    return [
        p for p in all_pairs
        if normalize_pair_key(p["relation_a"], p["relation_b"]) not in dismissed_map
    ]


def collapse_duplicate_edges(
    project: dict,
    *,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, int, list[dict[str, Any]]]:
    """Hợp nhất thông minh các cạnh có cùng bộ ba (source, normal(relation), target).
    
    Bảo toàn 100% bằng chứng: dồn toàn bộ evidences của các cạnh trùng vào cạnh đại diện.
    Thu thập tất cả original_relations và cập nhật bảng ánh xạ edge_redirects.
    """
    candidate = _clone_project_for_merge_mutation(project)
    edges = candidate.get("edges", [])
    if not edges:
        return candidate, 0, []
    edge_idx_by_id = {str(e.get("id", "")): idx for idx, e in enumerate(edges)}

    groups = group_edges_by_triplet(edges, exclude_rejected=True)

    dropped_ids: set[str] = set()
    collapsed_records: list[dict[str, Any]] = []
    edge_redirects = candidate.setdefault("edge_redirects", {})
    now_time = now_iso()

    for (s, r, t), grp in groups.items():
        if len(grp) <= 1:
            continue

        sorted_grp = sort_edges_by_priority(grp)
        kept = copy.deepcopy(sorted_grp[0])
        if str(kept.get("id", "")) in edge_idx_by_id:
            edges[edge_idx_by_id[str(kept["id"])]] = kept
        duplicates = sorted_grp[1:]

        orig_rels = list(kept.get("original_relations") or [])
        if not orig_rels:
            if kept.get("original_relation"):
                orig_rels.append(kept["original_relation"])
            if kept.get("relation") and kept["relation"] not in orig_rels:
                orig_rels.append(kept["relation"])

        for dup in duplicates:
            dup_id = str(dup["id"])
            dropped_ids.add(dup_id)
            edge_redirects[dup_id] = str(kept["id"])

            d_origs = list(dup.get("original_relations") or [])
            if not d_origs:
                if dup.get("original_relation"):
                    d_origs.append(dup["original_relation"])
                if dup.get("relation") and dup["relation"] not in d_origs:
                    d_origs.append(dup["relation"])
            for d_rel in d_origs:
                if d_rel and d_rel not in orig_rels:
                    orig_rels.append(d_rel)

            if dup.get("override") and kept.get("status") == STATUS_APPROVED:
                kept["override"] = True
                ovr_note = str(dup.get("override_reason") or "")
                if ovr_note and ovr_note not in str(kept.get("override_reason", "")):
                    kept["override_reason"] = (str(kept.get("override_reason") or "") + "; " + ovr_note).strip("; ")

        kept_evs = consolidate_edge_evidences(kept, duplicates)
        kept["evidences"] = kept_evs
        kept["original_relations"] = orig_rels

        collapsed_records.append({
            "kept_edge_id": str(kept["id"]),
            "dropped_edge_ids": [str(d["id"]) for d in duplicates],
            "triple": (s, kept.get("relation", ""), t),
            "total_evidences": len(kept_evs),
            "at": now_time,
        })

    if dropped_ids:
        candidate["edges"] = [e for e in candidate.get("edges", []) if str(e.get("id")) not in dropped_ids]
        candidate.setdefault("curation_history", []).append({
            "id": uid(),
            "at": now_time,
            "actor": actor,
            "action": "collapse_duplicate_edges",
            "dropped_count": len(dropped_ids),
            "records": collapsed_records,
            "note": note or f"Hợp nhất {len(dropped_ids)} cạnh trùng bộ ba.",
        })

    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)

    return candidate, len(dropped_ids), collapsed_records


def apply_relation_merge(
    project: dict,
    source_relations: list[str],
    target_relation: str,
    *,
    collapse_edges: bool = False,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Gộp một hoặc nhiều quan hệ nguồn về 1 quan hệ đích duy nhất."""
    target_clean = str(target_relation or "").strip()
    if not target_clean:
        raise ValueError("Quan hệ đích không được rỗng.")

    sources = [str(r).strip() for r in source_relations if str(r).strip() and str(r).strip() != target_clean]
    if not sources:
        raise ValueError("Cần ít nhất một quan hệ nguồn khác quan hệ đích để thực hiện gộp.")

    candidate = _clone_project_for_merge_mutation(project)
    rev_before = compute_project_revision(candidate)
    batch_id = uid()
    request_id = uid()
    merge_time = now_iso()

    source_set = set(sources)
    affected_edges: list[str] = []
    edges_list = candidate["edges"]

    for idx, edge in enumerate(edges_list):
        r = str(edge.get("relation", "")).strip()
        if r in source_set:
            new_edge = dict(edge)
            new_edge["original_relation"] = new_edge.get("original_relation") or r
            new_edge["relation"] = target_clean
            edges_list[idx] = new_edge
            affected_edges.append(str(new_edge["id"]))

    redirects = candidate.setdefault("relation_redirects", {})
    for s in sources:
        redirects[s] = target_clean
    for old_r, tgt in list(redirects.items()):
        if tgt in source_set:
            redirects[old_r] = target_clean

    aliases_map = candidate.setdefault("relation_aliases", {})
    tgt_aliases = list(aliases_map.get(target_clean, []))
    for s in sources:
        if s not in tgt_aliases and normal(s) != normal(target_clean):
            tgt_aliases.append(s)
    aliases_map[target_clean] = tgt_aliases

    rel_types = candidate.setdefault("relation_types", [])
    candidate["relation_types"] = [
        r for r in rel_types if str(r.get("name", "")).strip() not in source_set
    ]
    has_target = False
    for r in candidate["relation_types"]:
        if normal(r.get("name", "")) == normal(target_clean):
            has_target = True
            r_aliases = list(r.get("aliases") or [])
            for a in tgt_aliases:
                if a not in r_aliases and normal(a) != normal(target_clean):
                    r_aliases.append(a)
            r["aliases"] = r_aliases

    if not has_target:
        candidate["relation_types"].append(
            {
                "name": target_clean,
                "description": f"Quan hệ chuẩn hóa sau gộp từ: {', '.join(sources)}",
                "definition": f"Quan hệ '{target_clean}' gộp từ các biến thể.",
                "aliases": list(tgt_aliases),
            }
        )
    rel_notes = candidate.setdefault("relation_notes", {})
    for s in sources:
        rel_notes.pop(s, None)
    rel_notes.setdefault(target_clean, {})["aliases"] = list(tgt_aliases)

    raw_rels = candidate.setdefault("relations", [])
    candidate["relations"] = [r for r in raw_rels if r not in source_set]
    if target_clean not in candidate["relations"]:
        candidate["relations"].append(target_clean)

    props_list = candidate.get("schema_proposals", [])
    for idx, p in enumerate(props_list):
        if p.get("kind") == "relations" and p.get("name") in source_set:
            new_p = copy.deepcopy(p)
            new_p["status"] = "merged"
            new_p["canonical_name"] = target_clean
            new_p["reviewed_at"] = merge_time
            new_p["review_note"] = (str(new_p.get("review_note") or "") + f" [Gộp vào '{target_clean}']").strip()
            props_list[idx] = new_p

    merged_dup_count = 0
    if collapse_edges:
        _, merged_dup_count, _ = collapse_duplicate_edges(
            candidate,
            actor=actor,
            note=f"Tự động hợp nhất cạnh trùng sau khi gộp quan hệ về '{target_clean}'",
            mutate_in_place=True,
        )

    candidate.setdefault("relation_merges", []).append(
        {
            "merge_id": batch_id,
            "request_id": request_id,
            "at": merge_time,
            "actor": actor,
            "source_relations": sources,
            "target_relation": target_clean,
            "affected_edge_count": len(affected_edges),
            "merged_duplicate_edges": merged_dup_count,
            "aliases_stored": list(tgt_aliases),
            "note": note or f"Gộp quan hệ: {', '.join(sources)} → {target_clean}",
        }
    )

    rev_after = compute_project_revision(candidate)
    result = CurationResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=str(candidate.get("project_id") or project.get("name") or ""),
        operation="relation_merge",
        status="applied",
        apply_mode="all_or_nothing",
        revision_before=rev_before,
        revision_after=rev_after,
        applied_ids=sources,
        skipped_ids=[],
        applied_count=len(sources),
        skipped_count=0,
        item_results=[{"source": s, "target": target_clean} for s in sources],
        affected_edge_ids=affected_edges,
        merged_duplicate_edges=merged_dup_count,
    )
    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)
    clear_duplicate_suggestions_cache()
    clear_relation_duplicate_suggestions_cache()
    return candidate, result


def bulk_apply_relation_merges(
    project: dict,
    mappings: list[dict | tuple[str, str]] | dict[str, str],
    *,
    collapse_edges: bool = False,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Gộp hàng loạt nhiều cặp quan hệ nghi trùng cùng lúc.
    Mỗi phần tử trong mappings là (source_relation, target_relation) hoặc {'source': ..., 'target': ...} hoặc mapping dict.
    """
    if not mappings:
        raise ValueError("Danh sách quan hệ cần gộp trống.")

    candidate = _clone_project_for_merge_mutation(project)
    rev_before = compute_project_revision(candidate)
    batch_id = uid()
    request_id = uid()
    merge_time = now_iso()

    resolved_pairs: list[tuple[str, str]] = []
    items_to_process = list(mappings.items()) if isinstance(mappings, dict) else mappings
    for item in items_to_process:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            s, t = str(item[0]).strip(), str(item[1]).strip()
        elif isinstance(item, dict):
            s = str(item.get("source") or item.get("source_relation") or "").strip()
            t = str(item.get("target") or item.get("target_relation") or "").strip()
        else:
            continue
        if s and t and s != t:
            resolved_pairs.append((s, t))

    if not resolved_pairs:
        raise ValueError("Không có cặp quan hệ hợp lệ để gộp.")

    flat_map = flatten_redirects(resolved_pairs)

    affected_edges: list[str] = []
    edges_list = candidate["edges"]
    for idx, edge in enumerate(edges_list):
        r = str(edge.get("relation", "")).strip()
        if r in flat_map:
            new_edge = dict(edge)
            new_edge["original_relation"] = new_edge.get("original_relation") or r
            new_edge["relation"] = flat_map[r]
            edges_list[idx] = new_edge
            affected_edges.append(str(new_edge["id"]))

    redirects = candidate.setdefault("relation_redirects", {})
    for s, t in flat_map.items():
        redirects[s] = t

    aliases_map = candidate.setdefault("relation_aliases", {})
    for s, t in flat_map.items():
        t_aliases = list(aliases_map.get(t, []))
        if s not in t_aliases and normal(s) != normal(t):
            t_aliases.append(s)
        aliases_map[t] = t_aliases

    source_set = set(flat_map.keys())
    rel_types = candidate.setdefault("relation_types", [])
    candidate["relation_types"] = [
        r for r in rel_types if str(r.get("name", "")).strip() not in source_set
    ]
    raw_rels = candidate.setdefault("relations", [])
    candidate["relations"] = [r for r in raw_rels if r not in source_set]
    raw_rels_set = set(candidate["relations"])
    all_targets = set(flat_map.values())
    rel_notes = candidate.setdefault("relation_notes", {})
    for s in source_set:
        rel_notes.pop(s, None)

    rel_types_by_norm: dict[str, list[dict]] = {}
    for r in candidate["relation_types"]:
        rel_types_by_norm.setdefault(normal(r.get("name", "")), []).append(r)

    for t in all_targets:
        t_aliases = aliases_map.get(t, [])
        t_norm = normal(t)
        matched_rows = rel_types_by_norm.get(t_norm)
        if matched_rows:
            for r in matched_rows:
                curr_r_aliases = list(r.get("aliases") or [])
                curr_set = set(curr_r_aliases)
                for a in t_aliases:
                    if a not in curr_set and normal(a) != t_norm:
                        curr_r_aliases.append(a)
                        curr_set.add(a)
                r["aliases"] = curr_r_aliases
        else:
            new_rt = {
                "name": t,
                "description": "Quan hệ nạp tự động qua gộp hàng loạt",
                "definition": f"Quan hệ '{t}' gộp hàng loạt.",
                "aliases": list(t_aliases),
            }
            candidate["relation_types"].append(new_rt)
            rel_types_by_norm.setdefault(t_norm, []).append(new_rt)
        rel_notes.setdefault(t, {})["aliases"] = list(t_aliases)
        if t not in raw_rels_set:
            candidate["relations"].append(t)
            raw_rels_set.add(t)

    props_list = candidate.get("schema_proposals", [])
    for idx, p in enumerate(props_list):
        p_name = p.get("name", "")
        if p.get("kind") == "relations" and p_name in flat_map:
            new_p = copy.deepcopy(p)
            new_p["status"] = "merged"
            new_p["canonical_name"] = flat_map[p_name]
            new_p["reviewed_at"] = merge_time
            props_list[idx] = new_p

    merged_dup_count = 0
    if collapse_edges:
        _, merged_dup_count, _ = collapse_duplicate_edges(
            candidate,
            actor=actor,
            note=f"Tự động hợp nhất cạnh trùng sau khi gộp hàng loạt {len(flat_map)} quan hệ",
            mutate_in_place=True,
        )

    candidate.setdefault("relation_merges", []).append(
        {
            "merge_id": batch_id,
            "request_id": request_id,
            "at": merge_time,
            "actor": actor,
            "is_bulk": True,
            "merged_relations_count": len(flat_map),
            "affected_edge_count": len(affected_edges),
            "merged_duplicate_edges": merged_dup_count,
            "note": note or f"Gộp hàng loạt {len(flat_map)} quan hệ.",
        }
    )

    rev_after = compute_project_revision(candidate)
    result = CurationResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=str(candidate.get("project_id") or project.get("name") or ""),
        operation="bulk_relation_merge",
        status="applied",
        apply_mode="all_or_nothing",
        revision_before=rev_before,
        revision_after=rev_after,
        applied_ids=list(flat_map.keys()),
        skipped_ids=[],
        applied_count=len(flat_map),
        skipped_count=0,
        item_results=[{"source": s, "target": t} for s, t in flat_map.items()],
        affected_edge_ids=affected_edges,
        merged_duplicate_edges=merged_dup_count,
    )
    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)
    clear_duplicate_suggestions_cache()
    clear_relation_duplicate_suggestions_cache()
    return candidate, result


def mark_relation_pair_not_duplicate(project: dict, rel_a: str, rel_b: str, note: str = "") -> dict:
    """Đánh dấu hai quan hệ là khác nhau để không gợi ý lại."""
    a = str(rel_a or "").strip()
    b = str(rel_b or "").strip()
    if not a or not b or a == b:
        return {"ok": False, "reason": "Tên hai quan hệ không hợp lệ"}

    pairs = project.setdefault("not_duplicate_relation_pairs", [])
    entry = {
        "relation_a": min(a, b),
        "relation_b": max(a, b),
        "at": now_iso(),
        "note": note.strip(),
    }
    key = normalize_pair_key(a, b)
    existing = [p for p in pairs if normalize_pair_key(p.get("relation_a", ""), p.get("relation_b", "")) == key]
    if not existing:
        pairs.append(entry)
    clear_relation_duplicate_suggestions_cache()
    return {"ok": True, "entry": entry}


def mark_relation_pairs_not_duplicate_bulk(
    project: dict,
    pairs: list[tuple[str, str] | list[str] | dict[str, Any]],
    note: str = "",
) -> dict[str, Any]:
    """Đánh dấu hàng loạt cặp quan hệ là khác nhau trong một lần quét O(R + K)."""
    existing_list = project.setdefault("not_duplicate_relation_pairs", [])
    seen_keys = {
        normalize_pair_key(str(p.get("relation_a", "")), str(p.get("relation_b", "")))
        for p in existing_list
    }
    ts = now_iso()
    clean_note = str(note or "").strip()
    added = 0
    for item in pairs:
        if isinstance(item, dict):
            a = str(item.get("relation_a") or item.get("source") or "").strip()
            b = str(item.get("relation_b") or item.get("target") or "").strip()
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            a, b = str(item[0]).strip(), str(item[1]).strip()
        else:
            continue
        if not a or not b or a == b:
            continue
        key = normalize_pair_key(a, b)
        if key not in seen_keys:
            seen_keys.add(key)
            existing_list.append(
                {
                    "relation_a": min(a, b),
                    "relation_b": max(a, b),
                    "at": ts,
                    "note": clean_note,
                }
            )
            added += 1
    clear_relation_duplicate_suggestions_cache()
    return {"ok": True, "added_count": added}

