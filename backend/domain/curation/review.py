"""Duyệt đơn lẻ, duyệt hàng loạt và chỉnh sửa cạnh quan hệ với revision protection."""
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
    MODE_EDC,
    MODE_EDC_PLUS_R,
    STATUSES,
    STATUS_APPROVED,
    STATUS_CHECK,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from shared.schemas.curation import (
    REJECTION_REASON_CODES,
    CurationPreviewDTO,
    CurationResultDTO,
    CurationReviewRequestDTO,
    EdgeReviewDecisionDTO,
)
from shared.text_utils import normal, now_iso, sha, uid

from .common import clean_display_text, find_document, find_edge
from .evidence import recheck_edge_evidence
from .validation import validate_edge_for_approval


def _normalize_review_action(action: str) -> str:
    act = str(action or "").strip()
    mapping = {
        "approve": STATUS_APPROVED,
        STATUS_APPROVED: STATUS_APPROVED,
        "check": STATUS_CHECK,
        STATUS_CHECK: STATUS_CHECK,
        "reject": STATUS_REJECTED,
        STATUS_REJECTED: STATUS_REJECTED,
        "pending": STATUS_PENDING,
        STATUS_PENDING: STATUS_PENDING,
    }
    if act not in mapping:
        raise ValueError(f"Trạng thái/hành động kiểm duyệt không hợp lệ: {action}")
    return mapping[act]


def sync_edge_schema_to_catalog(project: dict, edge: dict) -> dict[str, Any]:
    """Tự động đồng bộ quan hệ và loại thực thể của cạnh vào danh mục chính thức, đồng thời un-reject/chuyển đề xuất liên quan thành approved."""
    rel_name = str(edge.get("relation") or "").strip()
    if not rel_name:
        return {"synced": False}

    proposals = project.setdefault("schema_proposals", [])
    rel_rows = project.get("relation_types")
    if rel_rows is None:
        rel_rows = []
        project["relation_types"] = rel_rows
    raw_relations = project.setdefault("relations", [])
    relation_notes = project.setdefault("relation_notes", {})

    # 1. Đồng bộ Quan hệ
    rel_norm = normal(rel_name)
    existing_rel = next((r for r in rel_rows if normal(r.get("name", "")) == rel_norm), None)
    if not existing_rel:
        rel_entry = {
            "name": rel_name,
            "description": f"Tự động nạp vào danh mục khi duyệt cạnh '{rel_name}'",
            "definition": f"Quan hệ '{rel_name}' được phê duyệt từ kiểm duyệt dữ kiện.",
        }
        rel_rows.append(rel_entry)
    if rel_name not in raw_relations:
        raw_relations.append(rel_name)
    if rel_name not in relation_notes:
        relation_notes[rel_name] = {
            "definition": f"Quan hệ '{rel_name}' được phê duyệt từ kiểm duyệt dữ kiện.",
            "description": f"Tự động nạp vào danh mục khi duyệt cạnh '{rel_name}'",
        }

    # Cập nhật đề xuất quan hệ (nếu có proposal liên quan đang rejected/pending thì mở khóa thành approved)
    for p in proposals:
        if p.get("kind") == "relations" and normal(p.get("name", "")) == rel_norm:
            if p.get("status") in ("rejected", "pending"):
                p["status"] = "approved"
                p["canonical_name"] = rel_name
                p["reviewed_at"] = now_iso()
                p["review_note"] = (str(p.get("review_note") or "") + " [Tự động duyệt qua kiểm duyệt cạnh]").strip()

    # 2. Đồng bộ Loại thực thể Nguồn & Đích
    nodes_by_id = {str(n.get("id", "")): n for n in project.get("nodes", [])}
    ent_types = project.setdefault("entity_types", [])
    for nid_key in ("source", "target"):
        nid = str(edge.get(nid_key) or "")
        node = nodes_by_id.get(nid)
        if not node:
            continue
        k_name = str(node.get("kind") or "").strip()
        if not k_name:
            continue
        k_norm = normal(k_name)
        existing_kind = next((k for k in ent_types if normal(k.get("name", "")) == k_norm), None)
        if not existing_kind:
            kind_entry = {
                "name": k_name,
                "description": f"Tự động nạp loại thực thể '{k_name}' khi duyệt cạnh",
                "definition": f"Loại thực thể '{k_name}' được kích hoạt từ kiểm duyệt dữ kiện.",
            }
            ent_types.append(kind_entry)

        for p in proposals:
            if p.get("kind") == "entity_types" and normal(p.get("name", "")) == k_norm:
                if p.get("status") in ("rejected", "pending"):
                    p["status"] = "approved"
                    p["canonical_name"] = k_name
                    p["reviewed_at"] = now_iso()
                    p["review_note"] = (str(p.get("review_note") or "") + " [Tự động duyệt qua kiểm duyệt cạnh]").strip()

    return {"synced": True, "relation": rel_name}


def set_edge_status(
    project: dict,
    edge_id: str,
    status: str,
    override_reason: str = "",
    reviewer: str = "",
    *,
    reason_code: str = "",
    note: str = "",
    override_method: str = "",
    self_loop_confirmed: bool = False,
    batch_id: str = "",
    request_id: str = "",
    allow_schema_bypass: bool = False,
    auto_sync_catalog: bool = True,
) -> dict:
    target_status = _normalize_review_action(status)
    if target_status not in STATUSES:
        raise ValueError(f"Trạng thái không hợp lệ: {status}")
    edge = find_edge(project, edge_id)
    if not edge:
        raise ValueError("Không tìm thấy quan hệ")

    before_edge = copy.deepcopy(edge)

    if target_status == STATUS_APPROVED:
        val = validate_edge_for_approval(
            project,
            edge,
            is_batch=False,
            override_reason=override_reason or ("Duyệt ngoại lệ/cưỡng chế" if allow_schema_bypass else ""),
            self_loop_confirmed=self_loop_confirmed or bool(edge.get("self_loop_confirmed")) or allow_schema_bypass,
            note=note or override_reason,
            allow_schema_bypass=allow_schema_bypass,
        )
        if not val["ok"]:
            raise ValueError(val["errors"][0])

        ev_ctx = val["evidence_ctx"]
        edge["evidence_found"] = bool(ev_ctx.get("found", False))
        edge["doc_fingerprint"] = ev_ctx.get("doc_fingerprint", "")
        if not ev_ctx.get("found", False):
            clean_reason = str(override_reason or "").strip() or "Duyệt ngoại lệ (chấp nhận bởi người kiểm duyệt)"
            edge["override"] = True
            edge["override_reason"] = clean_reason
            edge["override_method"] = str(override_method or "manual_verification").strip()
            edge["match_method"] = "override"
            tag = f"[Ngoại lệ bằng chứng] {clean_reason}" + (f" — {reviewer}" if reviewer else "")
            if tag not in str(edge.get("review_note", "")):
                edge["review_note"] = (str(edge.get("review_note", "")) + "\n" + tag).strip()
        else:
            edge["override"] = False
            edge["override_reason"] = ""
            edge["override_method"] = ""
            edge["match_method"] = ev_ctx.get("match_method", "exact")
            if ev_ctx.get("start_char") is not None and not ev_ctx.get("ambiguous"):
                edge["start_char"] = ev_ctx["start_char"]
                edge["end_char"] = ev_ctx["end_char"]
            if ev_ctx.get("page") is not None:
                edge["page"] = ev_ctx["page"]

        if val["is_self_loop"]:
            edge["self_loop_confirmed"] = True
        edge["rejection_code"] = ""
        if note.strip():
            edge["review_note"] = note.strip()

        if auto_sync_catalog:
            sync_edge_schema_to_catalog(project, edge)

    elif target_status == STATUS_REJECTED:
        eff_code = str(reason_code or "").strip()
        if eff_code and eff_code not in REJECTION_REASON_CODES:
            raise ValueError(f"Mã lý do loại bỏ không hợp lệ: {eff_code}")
        edge["rejection_code"] = eff_code or ("other" if note.strip() else edge.get("rejection_code", ""))
        edge["override"] = False
        edge["override_reason"] = ""
        if note.strip():
            code_label = REJECTION_REASON_CODES.get(edge["rejection_code"], "")
            prefix = f"[{code_label}] " if code_label else ""
            edge["review_note"] = f"{prefix}{note.strip()}".strip()
        elif eff_code:
            edge["review_note"] = f"[{REJECTION_REASON_CODES[eff_code]}]"

    else:
        # Chuyển về Cần kiểm tra / Chờ duyệt -> xóa hiệu lực duyệt/ngoại lệ cũ
        edge["override"] = False
        edge["override_reason"] = ""
        if note.strip():
            edge["review_note"] = note.strip()

    edge["status"] = target_status
    edge["reviewed_at"] = now_iso() if target_status in (STATUS_APPROVED, STATUS_REJECTED) else ""
    edge["reviewed_by"] = reviewer or "human_reviewer"

    project.setdefault("curation_history", []).append(
        {
            "id": uid(),
            "batch_id": batch_id,
            "request_id": request_id,
            "at": now_iso(),
            "actor": reviewer or "human_reviewer",
            "decision_origin": "human",
            "action": f"review_edge:{target_status}",
            "target_id": edge_id,
            "reason_code": edge.get("rejection_code", ""),
            "note": note.strip() or override_reason.strip(),
            "before": before_edge,
            "after": copy.deepcopy(edge),
        }
    )
    return edge


def set_edges_status(project: dict, edge_ids: list[str], status: str, *, note: str = "", reason_code: str = "") -> dict:
    changed = 0
    skipped: list[dict] = []
    batch_id = uid()
    for edge_id in edge_ids:
        try:
            edge = find_edge(project, edge_id)
            if edge is None:
                raise ValueError("Không tìm thấy quan hệ")
            if status == STATUS_APPROVED:
                val = validate_edge_for_approval(project, edge, is_batch=True)
                if not val["ok"]:
                    raise ValueError(val["errors"][0])
            set_edge_status(
                project,
                edge_id,
                status,
                reason_code=reason_code,
                note=note,
                batch_id=batch_id,
            )
            changed += 1
        except ValueError as exc:
            skipped.append({"id": edge_id, "reason": str(exc)})
    return {"changed": changed, "skipped": skipped, "batch_id": batch_id}


def compute_curation_decisions_hash(project_id: str, decisions: list[EdgeReviewDecisionDTO | dict]) -> str:
    normalized = [EdgeReviewDecisionDTO.from_dict(d).to_dict() for d in decisions]
    payload = {"project_id": str(project_id or "").strip(), "decisions": normalized}
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def compute_curation_request_hash(req: Any) -> str:
    if isinstance(req, CurationReviewRequestDTO) or (isinstance(req, dict) and "decisions" in req):
        dto = CurationReviewRequestDTO.from_dict(req)
        payload: dict[str, Any] = {
            "project_id": dto.project_id,
            "apply_mode": dto.apply_mode,
            "is_batch": dto.is_batch,
            "allow_schema_bypass": dto.allow_schema_bypass,
            "auto_sync_catalog": dto.auto_sync_catalog,
            "decisions": [d.to_dict() for d in dto.decisions],
        }
        return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]
    if hasattr(req, "to_dict"):
        raw = dict(req.to_dict())
    elif isinstance(req, dict):
        raw = dict(req)
    else:
        raw = {"value": str(req)}
    raw.pop("request_id", None)
    raw.pop("expected_revision", None)
    return sha(json.dumps(raw, ensure_ascii=False, sort_keys=True))[:16]


def preview_curation_decisions(
    project: dict,
    request: CurationReviewRequestDTO | dict,
) -> CurationPreviewDTO:
    """Xem trước lô kiểm duyệt dữ kiện (không ghi dự án, không đổi trạng thái)."""
    req = CurationReviewRequestDTO.from_dict(request)
    work_project = copy.deepcopy(project)
    proj_id = str(work_project.get("project_id") or "")
    proj_name = str(work_project.get("name") or "")
    revision = compute_project_revision(work_project)
    cat_hash = compute_catalog_hash(work_project)

    batch_errors: list[str] = []
    if req.project_id and req.project_id not in (proj_id, proj_name):
        batch_errors.append(f"project_id '{req.project_id}' không khớp dự án hiện tại ('{proj_name}')")
    if req.apply_mode not in ("all_or_nothing", "valid_only"):
        batch_errors.append(f"Chế độ áp dụng không hợp lệ: '{req.apply_mode}'")
    if not req.decisions:
        batch_errors.append("Danh sách quyết định kiểm duyệt trống.")

    edges_by_id = {str(e.get("id", "")): e for e in work_project.get("edges", [])}
    nodes_by_id = {str(n.get("id", "")): n for n in work_project.get("nodes", [])}

    by_eid: dict[str, list[EdgeReviewDecisionDTO]] = {}
    ordered_eids: list[str] = []
    for dec in req.decisions:
        eid = dec.edge_id
        if eid not in by_eid:
            ordered_eids.append(eid)
            by_eid[eid] = []
        by_eid[eid].append(dec)

    conflicting_eids: set[str] = set()
    deduped_decisions: list[EdgeReviewDecisionDTO] = []
    for eid in ordered_eids:
        group = by_eid[eid]
        sigs = {(d.action, d.reason_code, d.note.strip(), d.override_reason.strip(), d.self_loop_confirmed) for d in group}
        if len(sigs) > 1:
            conflicting_eids.add(eid)
        deduped_decisions.append(group[0])

    item_previews: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0
    excluded_processed_count = 0

    for dec in deduped_decisions:
        eid = dec.edge_id
        edge = edges_by_id.get(eid)
        errors: list[str] = []
        warnings: list[str] = []

        if req.project_id and req.project_id not in (proj_id, proj_name):
            errors.append(f"ID dự án '{req.project_id}' không khớp dự án hiện tại")
        if eid in conflicting_eids:
            errors.append(f"Cạnh '{eid}' xuất hiện nhiều lần với quyết định mâu thuẫn trong cùng lô")

        try:
            target_status = _normalize_review_action(dec.action)
        except ValueError as exc:
            target_status = dec.action
            errors.append(str(exc))

        if edge is None:
            errors.append(f"Không tìm thấy cạnh ID '{eid}' trong dự án")
            src_name = ""
            tgt_name = ""
            rel_name = ""
            status_before = ""
            blocking_pids: list[str] = []
        else:
            src_name = nodes_by_id.get(str(edge.get("source", "")), {}).get("name", str(edge.get("source", "")))
            tgt_name = nodes_by_id.get(str(edge.get("target", "")), {}).get("name", str(edge.get("target", "")))
            rel_name = str(edge.get("relation", ""))
            status_before = str(edge.get("status", STATUS_PENDING))
            blocking_pids = []

            if req.is_batch and status_before in (STATUS_APPROVED, STATUS_REJECTED):
                excluded_processed_count += 1
                errors.append(
                    f"Cạnh đang ở trạng thái '{status_before}'; thao tác hàng loạt chỉ áp dụng cho cạnh Chờ duyệt / Cần kiểm tra."
                )

            if target_status == STATUS_APPROVED:
                val = validate_edge_for_approval(
                    work_project,
                    edge,
                    is_batch=req.is_batch,
                    override_reason=dec.override_reason or ("Duyệt ngoại lệ/cưỡng chế" if req.allow_schema_bypass else ""),
                    self_loop_confirmed=dec.self_loop_confirmed or req.allow_schema_bypass,
                    note=dec.note,
                    allow_schema_bypass=req.allow_schema_bypass,
                )
                errors.extend(val["errors"])
                warnings.extend(val["warnings"])
                blocking_pids = val["schema_info"].get("blocking_proposal_ids", [])
            elif target_status == STATUS_REJECTED:
                if dec.reason_code and dec.reason_code not in REJECTION_REASON_CODES:
                    errors.append(f"Mã lý do loại bỏ '{dec.reason_code}' không hợp lệ")
                if not dec.reason_code and not dec.note.strip():
                    errors.append("Cần chọn mã lý do hoặc nhập ghi chú khi loại bỏ dữ kiện")
            elif target_status not in (STATUS_CHECK, STATUS_PENDING):
                errors.append(f"Trạng thái đích '{target_status}' không được hỗ trợ")

        is_valid = len(errors) == 0 and len(batch_errors) == 0
        if is_valid:
            valid_count += 1
        else:
            invalid_count += 1

        item_previews.append(
            {
                "edge_id": eid,
                "source_name": src_name,
                "relation": rel_name,
                "target_name": tgt_name,
                "status_before": status_before,
                "status_after": target_status,
                "action": dec.action,
                "reason_code": dec.reason_code,
                "note": dec.note.strip(),
                "override_reason": dec.override_reason.strip(),
                "self_loop_confirmed": dec.self_loop_confirmed,
                "valid": is_valid,
                "errors": errors,
                "warnings": warnings,
                "blocking_proposal_ids": blocking_pids,
            }
        )

    req_hash = compute_curation_decisions_hash(req.project_id or proj_id, deduped_decisions)
    can_apply_all = len(batch_errors) == 0 and valid_count > 0 and invalid_count == 0
    can_apply_valid_only = len(batch_errors) == 0 and valid_count > 0 and invalid_count > 0

    return CurationPreviewDTO(
        preview_id=uid(),
        project_id=proj_id or req.project_id,
        revision=revision,
        catalog_hash=cat_hash,
        request_hash=req_hash,
        locked_edge_ids=ordered_eids,
        valid_count=valid_count,
        invalid_count=invalid_count,
        excluded_processed_count=excluded_processed_count,
        item_previews=item_previews,
        batch_errors=batch_errors,
        can_apply_all=can_apply_all,
        can_apply_valid_only=can_apply_valid_only,
    )


def apply_curation_decisions(
    project: dict,
    request: CurationReviewRequestDTO | dict,
    *,
    preview: CurationPreviewDTO | dict | None = None,
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Xác thực lại và áp dụng lô quyết định kiểm duyệt dữ kiện trên bản sao dự án."""
    req = CurationReviewRequestDTO.from_dict(request)
    current_rev = compute_project_revision(project)
    current_cat_hash = compute_catalog_hash(project)

    if req.expected_revision and req.expected_revision != current_rev:
        raise ValueError(
            "Trạng thái dự án hoặc danh mục đã thay đổi kể từ lúc xem trước (revision mismatch). Vui lòng xem trước lại."
        )

    fresh_preview = preview_curation_decisions(project, req)
    if preview is not None:
        prev_dto = CurationPreviewDTO.from_dict(preview)
        if prev_dto.revision != current_rev or prev_dto.catalog_hash != current_cat_hash:
            raise ValueError(
                "Bản xem trước đã hết hiệu lực do dữ liệu dự án hoặc danh mục đã thay đổi. Vui lòng xem trước lại."
            )
        if prev_dto.request_hash != fresh_preview.request_hash:
            raise ValueError("Nội dung quyết định đã thay đổi so với bản xem trước. Vui lòng xem trước lại.")
        if prev_dto.locked_edge_ids != fresh_preview.locked_edge_ids:
            raise ValueError("Tập ID cạnh không khớp với tập ID đã chốt khi xem trước.")

    if fresh_preview.batch_errors:
        raise ValueError("; ".join(fresh_preview.batch_errors))

    if req.apply_mode == "all_or_nothing":
        if fresh_preview.invalid_count > 0:
            raise ValueError(
                f"Lô có {fresh_preview.invalid_count} cạnh bị chặn validation. Chế độ all_or_nothing không lưu khi còn lỗi."
            )
        if fresh_preview.valid_count == 0:
            raise ValueError("Không có cạnh hợp lệ nào để áp dụng.")
    elif req.apply_mode == "valid_only":
        if fresh_preview.valid_count == 0:
            raise ValueError("Không có cạnh hợp lệ nào trong lô để áp dụng một phần (valid_only).")
    else:
        raise ValueError(f"Chế độ áp dụng không hợp lệ: {req.apply_mode}")

    candidate = copy.deepcopy(project)
    batch_id = uid()
    request_id = req.request_id or uid()
    applied_ids: list[str] = []
    skipped_ids: list[str] = []
    item_results: list[dict[str, Any]] = []

    for item in fresh_preview.item_previews:
        eid = item["edge_id"]
        if item["valid"]:
            set_edge_status(
                candidate,
                eid,
                item["status_after"],
                override_reason=item["override_reason"],
                reviewer=req.actor,
                reason_code=item["reason_code"],
                note=item["note"],
                self_loop_confirmed=bool(item.get("self_loop_confirmed", False)) or req.allow_schema_bypass,
                batch_id=batch_id,
                request_id=request_id,
                allow_schema_bypass=req.allow_schema_bypass,
                auto_sync_catalog=req.auto_sync_catalog,
            )
            applied_ids.append(eid)
            item_results.append(
                {
                    "edge_id": eid,
                    "status": "applied",
                    "status_before": item["status_before"],
                    "status_after": item["status_after"],
                    "errors": [],
                }
            )
        else:
            skipped_ids.append(eid)
            item_results.append(
                {
                    "edge_id": eid,
                    "status": "skipped_invalid",
                    "status_before": item["status_before"],
                    "status_after": item["status_before"],
                    "errors": list(item["errors"]),
                    "blocking_proposal_ids": list(item.get("blocking_proposal_ids", [])),
                }
            )

    rev_after = compute_project_revision(candidate)
    batch_entry = {
        "batch_id": batch_id,
        "request_id": request_id,
        "request_hash": compute_curation_request_hash(req),
        "at": now_iso(),
        "actor": req.actor,
        "operation": "edge_review",
        "apply_mode": req.apply_mode,
        "filter_summary": dict(req.filter_summary),
        "locked_edge_ids": list(fresh_preview.locked_edge_ids),
        "applied_ids": applied_ids,
        "skipped_ids": skipped_ids,
        "revision_before": current_rev,
        "revision_after": rev_after,
        "snapshot_path": "",
        "item_results": copy.deepcopy(item_results),
    }
    candidate.setdefault("curation_decision_batches", []).append(batch_entry)

    result = CurationResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=str(candidate.get("project_id") or req.project_id),
        operation="edge_review",
        status="committed",
        apply_mode=req.apply_mode,
        revision_before=current_rev,
        revision_after=rev_after,
        applied_ids=applied_ids,
        skipped_ids=skipped_ids,
        applied_count=len(applied_ids),
        skipped_count=len(skipped_ids),
        item_results=item_results,
        affected_edge_ids=applied_ids,
    )

    if mutate_in_place:
        project.clear()
        project.update(candidate)

    return candidate, result


def update_edge(project: dict, edge_id: str, **fields) -> dict:
    """Cập nhật dữ kiện theo đúng Ma trận ảnh hưởng mục 8.2:
    Đổi nguồn, đích, quan hệ, bằng chứng hoặc nguồn/vị trí dẫn chứng -> cạnh chuyển về Cần kiểm tra (trừ cạnh đã Loại bỏ)
    và xóa hiệu lực phê duyệt/ngoại lệ cũ, ngay cả khi câu bằng chứng vẫn khớp.
    """
    edge = find_edge(project, edge_id)
    if not edge:
        raise ValueError("Không tìm thấy quan hệ")
    before_edge = copy.deepcopy(edge)
    node_ids = {n["id"] for n in project.get("nodes", [])}

    semantic_changed = False
    if "source" in fields and fields["source"] is not None:
        new_src = str(fields["source"]).strip()
        if new_src not in node_ids:
            raise ValueError("Thực thể nguồn không tồn tại")
        if new_src != edge.get("source"):
            edge["source"] = new_src
            semantic_changed = True

    if "target" in fields and fields["target"] is not None:
        new_tgt = str(fields["target"]).strip()
        if new_tgt not in node_ids:
            raise ValueError("Thực thể đích không tồn tại")
        if new_tgt != edge.get("target"):
            edge["target"] = new_tgt
            semantic_changed = True

    if "relation" in fields and fields["relation"] is not None:
        rel = clean_display_text(str(fields["relation"]))
        if not rel:
            raise ValueError("Tên quan hệ không được rỗng")
        allowed_rels = {normal(r["name"]): r["name"] for r in catalog_rows(project, "relations")}
        if normal(rel) in allowed_rels:
            rel = allowed_rels[normal(rel)]
            proposals_by_id = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
            edge["schema_proposal_ids"] = [
                pid for pid in edge.get("schema_proposal_ids", [])
                if proposals_by_id.get(str(pid), {}).get("kind") != "relations"
            ]
        elif edge.get("extraction_mode") not in (MODE_EDC, MODE_EDC_PLUS_R):
            raise ValueError(f"Quan hệ '{rel}' không nằm trong danh mục đã duyệt của dự án.")
        if rel != edge.get("relation"):
            edge["relation"] = rel
            semantic_changed = True

    if "doc_id" in fields and fields["doc_id"] is not None:
        new_doc_id = str(fields["doc_id"]).strip()
        if not find_document(project, new_doc_id):
            raise ValueError("Tài liệu nguồn không tồn tại")
        if new_doc_id != edge.get("doc_id"):
            edge["doc_id"] = new_doc_id
            edge["start_char"] = None
            edge["end_char"] = None
            edge["verified_start_char"] = None
            edge["verified_end_char"] = None
            semantic_changed = True

    if "evidence" in fields and fields["evidence"] is not None:
        new_ev = str(fields["evidence"]).strip()
        if not new_ev:
            raise ValueError("Trích dẫn bằng chứng không được rỗng")
        if new_ev != str(edge.get("evidence", "")).strip():
            edge["evidence"] = new_ev
            edge["verified_start_char"] = None
            edge["verified_end_char"] = None
            semantic_changed = True

    if "start_char" in fields and fields["start_char"] is not None:
        if int(fields["start_char"]) != edge.get("start_char"):
            edge["start_char"] = int(fields["start_char"])
            semantic_changed = True

    if "end_char" in fields and fields["end_char"] is not None:
        if int(fields["end_char"]) != edge.get("end_char"):
            edge["end_char"] = int(fields["end_char"])
            semantic_changed = True

    recheck_edge_evidence(project, edge)

    if semantic_changed:
        if edge.get("status") != STATUS_REJECTED:
            edge["status"] = STATUS_CHECK
            edge["reviewed_at"] = ""
            edge["override"] = False
            edge["override_reason"] = ""
            edge["self_loop_confirmed"] = False
    elif edge.get("status") == STATUS_APPROVED and not edge.get("evidence_found") and not edge.get("override"):
        edge["status"] = STATUS_CHECK
        edge["reviewed_at"] = ""

    note = str(fields.get("note") or "").strip()
    if note:
        edge["review_note"] = note

    project.setdefault("curation_history", []).append(
        {
            "id": uid(),
            "request_id": str(fields.get("request_id") or ""),
            "at": now_iso(),
            "actor": str(fields.get("actor") or "human_reviewer"),
            "decision_origin": "human",
            "action": "edit_edge",
            "target_id": edge_id,
            "semantic_changed": semantic_changed,
            "note": note,
            "before": before_edge,
            "after": copy.deepcopy(edge),
        }
    )
    return edge

