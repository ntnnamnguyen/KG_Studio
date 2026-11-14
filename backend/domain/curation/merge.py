"""Xem trước và thực thi gộp N thực thể, bảo toàn cạnh và ánh xạ node_redirects."""
from __future__ import annotations

import copy
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
from .gazetteer import enrich_gazetteer_from_merge
from .merge_core import (
    DisjointSetUnion,
    _clone_project_for_merge_mutation,
    consolidate_edge_evidences,
    consolidate_node_attributes,
    flatten_redirects,
    group_edges_by_triplet,
    normalize_pair_key,
    rank_representative_edge,
    remap_graph_edges_endpoints,
    sort_edges_by_priority,
    update_redirect_map,
)
from .relation_merge import (
    apply_relation_merge,
    bulk_apply_relation_merges,
    clear_relation_duplicate_suggestions_cache,
    collapse_duplicate_edges,
    mark_relation_pair_not_duplicate,
    mark_relation_pairs_not_duplicate_bulk,
    relation_duplicate_suggestions,
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

    # Kiểm tra xung đột mô tả
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

    preview_target = {
        "id": keep_id,
        "name": chosen_name,
        "kind": chosen_kind,
        "description": chosen_description,
        "aliases": list(req.aliases) if req.aliases else [],
    }
    consolidate_node_attributes(preview_target, member_nodes, merge_time=now_iso())
    merged_node_preview = {
        "id": keep_id,
        "name": chosen_name,
        "kind": chosen_kind,
        "description": chosen_description,
        "aliases": preview_target["aliases"],
        "documents": preview_target["documents"],
        "schema_proposal_ids": preview_target["schema_proposal_ids"],
        "edc_observations": preview_target["edc_observations"],
    }

    # Tính toán mô phỏng tác động trên các cạnh
    drop_to_keep = {d_id: keep_id for d_id in drop_ids}
    kind_changed_by_member = {
        nid: normal(nodes_by_id[nid].get("kind", "")) != normal(chosen_kind)
        for nid in unique_members
        if nid in nodes_by_id
    }
    (
        affected_edge_ids,
        changed_endpoint_count,
        new_self_loop_ids,
        invalidated_approved_count,
        edge_changes,
        simulated_edges,
    ) = remap_graph_edges_endpoints(
        work_project.get("edges", []),
        drop_to_keep,
        member_set=set(unique_members),
        kind_changed_by_member=kind_changed_by_member,
        simulate_only=True,
    )
    affected_edge_count = len(affected_edge_ids)

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
    original_kinds_by_member = {
        nid: str(nodes_by_id[nid].get("kind", ""))
        for nid in fresh_preview.member_ids
        if nid in nodes_by_id
    }
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

    # Tự động làm giàu Từ điển bí danh dự án (Continuous Curation & Gazetteer Feedback Loop)
    dropped_nodes_list = [nodes_by_id[d_id] for d_id in drop_ids if d_id in nodes_by_id]
    added_gaz = enrich_gazetteer_from_merge(
        candidate,
        canonical_name=preview_node["name"],
        canonical_kind=preview_node["kind"],
        absorbed_nodes=dropped_nodes_list,
        merge_id=fresh_preview.request_hash or now_iso(),
        actor=req.actor,
    )

    drop_to_keep = {d_id: keep_id for d_id in drop_ids}
    (
        affected_edge_ids,
        changed_endpoints,
        new_self_loop_ids,
        _,
        _,
        _,
    ) = remap_graph_edges_endpoints(
        candidate.get("edges", []),
        drop_to_keep,
        member_set=set(fresh_preview.member_ids),
        kind_changed_by_member={
            nid: normal(original_kinds_by_member.get(nid, "")) != normal(preview_node["kind"])
            for nid in fresh_preview.member_ids
            if nid in original_kinds_by_member
        },
        merge_time=merge_time,
        actor=req.actor,
        keep_id=keep_id,
        curation_history=candidate.setdefault("curation_history", []),
        simulate_only=False,
    )

    candidate["node_redirects"] = update_redirect_map(
        candidate.get("node_redirects", {}),
        drop_to_keep,
        keep_id=keep_id,
    )

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
        "canonical_name": preview_node["name"],
        "canonical_kind": preview_node["kind"],
        "kind_resolution_note": req.kind_resolution_note,
        "canonical_description": preview_node["description"],
        "aliases": list(preview_node["aliases"]),
        "affected_edge_ids": affected_edge_ids,
        "changed_endpoints": changed_endpoints,
        "new_self_loop_ids": new_self_loop_ids,
        "merged_duplicate_edges": merged_dup_count,
        "gazetteer_aliases_added": [v.get("alias", k) for k, v in added_gaz.items()],
        "note": req.note,
    }
    candidate.setdefault("entity_merges", []).append(merge_record)

    item_results = [{"member_id": nid, "status": "kept" if nid == keep_id else "merged"} for nid in fresh_preview.member_ids]
    result = CurationResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=str(candidate.get("project_id") or project.get("name") or ""),
        operation="entity_merge",
        status="committed",
        apply_mode="all_or_nothing",
        revision_before=current_rev,
        revision_after=rev_after,
        applied_ids=fresh_preview.member_ids,
        skipped_ids=[],
        applied_count=len(fresh_preview.member_ids),
        skipped_count=0,
        item_results=item_results,
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
    """Hàm tương thích cho gộp 2 thực thể: chuyển tiếp sang apply_entity_merge an toàn."""
    if keep == drop:
        return {"ok": False, "reason": "Hai thực thể phải khác nhau"}
    nodes = {str(n["id"]): n for n in project.get("nodes", [])}
    if keep not in nodes or drop not in nodes:
        return {"ok": False, "reason": "Không tìm thấy thực thể cần gộp"}

    keep_node, drop_node = nodes[keep], nodes[drop]
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
    for raw_p in pairs:
        p = raw_p.to_dict() if hasattr(raw_p, "to_dict") else raw_p
        if isinstance(p, (tuple, list)) and len(p) >= 2:
            a, b = str(p[0]).strip(), str(p[1]).strip()
            if a and b and a != b and a in nodes_by_id and b in nodes_by_id:
                normalized_pairs.append((a, b))
        elif isinstance(p, dict):
            if p.get("member_ids") and p.get("keep_id"):
                k_id = str(p["keep_id"]).strip()
                if k_id in nodes_by_id:
                    for m_id in p["member_ids"]:
                        m_str = str(m_id).strip()
                        if m_str and m_str != k_id and m_str in nodes_by_id:
                            normalized_pairs.append((k_id, m_str))
                continue
            a = str(p.get("keep_id") or p.get("node_a_id") or (p.get("node_a", {}) or {}).get("id") or "").strip()
            b = str(p.get("drop_id") or p.get("node_b_id") or (p.get("node_b", {}) or {}).get("id") or "").strip()
            if a and b and a != b and a in nodes_by_id and b in nodes_by_id:
                normalized_pairs.append((a, b))

    if not normalized_pairs:
        raise ValueError(
            "Không có cặp thực thể hợp lệ nào tồn tại trong đồ thị để gộp "
            "(các cặp được chọn có thể bị trùng ID với chính nó hoặc các thực thể này đã được gộp trong phiên trước)."
        )

    dsu = DisjointSetUnion()
    for a, b in normalized_pairs:
        dsu.union(a, b)

    clusters_by_root: dict[str, set[str]] = {}
    for a, b in normalized_pairs:
        clusters_by_root.setdefault(dsu.find(a), set()).add(a)
        clusters_by_root.setdefault(dsu.find(b), set()).add(b)

    total_applied_clusters = 0
    all_dropped_ids: list[str] = []
    all_gaz_aliases_added: list[str] = []
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
        for d_id in drop_ids:
            drop_to_keep[d_id] = keep_id

        dropped_nodes = [nodes_by_id[d] for d in drop_ids]
        consolidate_node_attributes(
            keep_node,
            dropped_nodes,
            merge_time=merge_time,
            batch_id=batch_id,
        )
        added_gaz = enrich_gazetteer_from_merge(
            candidate,
            canonical_name=str(keep_node.get("name", "")),
            canonical_kind=str(keep_node.get("kind", "")),
            absorbed_nodes=dropped_nodes,
            merge_id=batch_id,
            actor=actor,
        )
        all_gaz_aliases_added.extend(v.get("alias", k) for k, v in added_gaz.items())
        total_applied_clusters += 1

    all_affected_edge_ids: list[str] = []
    total_changed_endpoints = 0
    invalidated_approved_count = 0
    kind_changed_by_member: dict[str, bool] = {}
    member_set: set[str] = set()
    for _, members in clusters_by_root.items():
        if len(members) < 2:
            continue
        member_set.update(members)
    for d_id, k_id in drop_to_keep.items():
        d_kind = normal(nodes_by_id.get(d_id, {}).get("kind", ""))
        k_kind = normal(nodes_by_id.get(k_id, {}).get("kind", ""))
        kind_changed_by_member[d_id] = d_kind != k_kind
        kind_changed_by_member.setdefault(k_id, False)

    if drop_to_keep:
        candidate["node_redirects"] = update_redirect_map(
            candidate.get("node_redirects", {}),
            drop_to_keep,
        )
        (
            all_affected_edge_ids,
            total_changed_endpoints,
            _,
            invalidated_approved_count,
            _,
            _,
        ) = remap_graph_edges_endpoints(
            edges,
            drop_to_keep,
            member_set=member_set,
            kind_changed_by_member=kind_changed_by_member,
            merge_time=merge_time,
            actor=actor,
            curation_history=candidate.setdefault("curation_history", []),
            simulate_only=False,
        )

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

    merge_entry = {
        "merge_id": batch_id,
        "request_id": request_id,
        "at": merge_time,
        "actor": actor,
        "is_bulk": True,
        "merged_clusters_count": total_applied_clusters,
        "merged_entities_count": len(all_dropped_ids),
        "affected_edge_count": len(all_affected_edge_ids),
        "changed_endpoints": total_changed_endpoints,
        "invalidated_approved_count": invalidated_approved_count,
        "merged_duplicate_edges": merged_dup_count,
        "gazetteer_aliases_added": all_gaz_aliases_added,
        "note": note or f"Gộp hàng loạt {len(normalized_pairs)} cặp thực thể qua DSU.",
    }
    candidate.setdefault("entity_merges", []).append(merge_entry)
    candidate.setdefault("curation_history", []).append(
        {
            "id": batch_id,
            "request_id": request_id,
            "at": merge_time,
            "actor": actor,
            "decision_origin": "human",
            "action": "bulk_entity_merge",
            "target_id": f"{total_applied_clusters}_clusters",
            "note": merge_entry["note"],
            "after": merge_entry,
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
        applied_ids=list(drop_to_keep.keys()),
        skipped_ids=[],
        applied_count=len(drop_to_keep),
        skipped_count=0,
        item_results=[{"drop_id": d, "keep_id": k} for d, k in drop_to_keep.items()],
        affected_edge_ids=all_affected_edge_ids,
        changed_endpoint_count=total_changed_endpoints,
        invalidated_approved_count=invalidated_approved_count,
        merged_duplicate_edges=merged_dup_count,
    )
    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)

    clear_duplicate_suggestions_cache()
    clear_relation_duplicate_suggestions_cache()
    return candidate, result
