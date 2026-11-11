"""Kiểm tra điều kiện schema, bằng chứng và tính hợp lệ để duyệt/xuất cạnh quan hệ."""
from __future__ import annotations

from typing import Any

from backend.domain.catalogs.service import catalog_rows, schema_review_issue
from shared.constants import (
    STATUS_APPROVED,
    STATUS_CHECK,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from shared.text_utils import normal

from .common import doc_fingerprint, find_document, find_node
from .evidence import evidence_context


def build_schema_precomputed(project: dict) -> dict[str, Any]:
    """Xây dựng chỉ mục O(1) cho kiểm tra danh mục / đề xuất schema của cạnh."""
    proposals: dict[str, dict] = {}
    proposals_by_kind_norm: dict[tuple[str, str], list[str]] = {}
    for p in project.get("schema_proposals", []):
        pid = str(p.get("id", ""))
        if not pid:
            continue
        proposals[pid] = p
        pk = str(p.get("kind", ""))
        pn = normal(str(p.get("name", "")))
        if pk and pn:
            proposals_by_kind_norm.setdefault((pk, pn), []).append(pid)

    nodes = {str(n.get("id", "")): n for n in project.get("nodes", []) if n.get("id")}
    rel_norms = {normal(r["name"]) for r in catalog_rows(project, "relations")}
    type_norms = {normal(t["name"]) for t in catalog_rows(project, "entity_types")}
    return {
        "proposals": proposals,
        "proposals_by_kind_norm": proposals_by_kind_norm,
        "nodes": nodes,
        "rel_norms": rel_norms,
        "type_norms": type_norms,
    }


def build_curation_validation_context(project: dict) -> dict[str, Any]:
    """Xây dựng ngữ cảnh tra cứu O(1) đầy đủ (schema + nodes + documents + fingerprints) cho thao tác hàng loạt."""
    ctx = build_schema_precomputed(project)
    docs_by_id = {str(d.get("id", "")): d for d in project.get("documents", []) if d.get("id")}
    doc_fingerprints = {did: doc_fingerprint(d) for did, d in docs_by_id.items()}
    ctx["docs_by_id"] = docs_by_id
    ctx["doc_fingerprints"] = doc_fingerprints
    return ctx


def inspect_edge_schema_status(
    project: dict,
    edge: dict,
    *,
    precomputed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phân loại chi tiết tình trạng danh mục (Schema) của một cạnh theo 3 thành phần độc lập:
    1. Quan hệ R: Nếu đã có trong danh mục quan hệ -> Hợp lệ về mặt quan hệ.
    2. Loại Node nguồn S: Nếu đã có trong danh mục loại thực thể -> Hợp lệ về loại nguồn.
    3. Loại Node đích T: Nếu đã có trong danh mục loại thực thể -> Hợp lệ về loại đích.
    Khi cả 3 thành phần đều nằm trong danh mục đã duyệt -> Cạnh đạt trạng thái Hợp lệ ('valid') 100%.
    Hỗ trợ tham số precomputed để tối ưu hóa O(1) khi gọi hàng loạt trong review_stats hoặc bộ lọc.
    """
    if precomputed:
        proposals = precomputed.get("proposals", {})
        proposals_by_kind_norm = precomputed.get("proposals_by_kind_norm")
        nodes = precomputed.get("nodes", {})
        rel_norms = precomputed.get("rel_norms", set())
        type_norms = precomputed.get("type_norms", set())
    else:
        proposals = {str(p.get("id", "")): p for p in project.get("schema_proposals", [])}
        proposals_by_kind_norm = None
        nodes = {str(n.get("id", "")): n for n in project.get("nodes", [])}
        rel_norms = {normal(r["name"]) for r in catalog_rows(project, "relations")}
        type_norms = {normal(t["name"]) for t in catalog_rows(project, "entity_types")}

    src_id = str(edge.get("source", ""))
    tgt_id = str(edge.get("target", ""))
    src_node = nodes.get(src_id)
    tgt_node = nodes.get(tgt_id)
    src_name = src_node.get("name", src_id) if src_node else src_id
    tgt_name = tgt_node.get("name", tgt_id) if tgt_node else tgt_id
    rel_name = str(edge.get("relation", "")).strip()

    edge_pids = [str(pid) for pid in edge.get("schema_proposal_ids", []) if str(pid)]
    src_pids = [str(pid) for pid in (src_node.get("schema_proposal_ids", []) if src_node else []) if str(pid)]
    tgt_pids = [str(pid) for pid in (tgt_node.get("schema_proposal_ids", []) if tgt_node else []) if str(pid)]

    blocking_proposal_ids: list[str] = []
    issues: list[str] = []
    rel_issue_type: str = ""
    src_issue_type: str = ""
    tgt_issue_type: str = ""

    # 1. KIỂM TRA QUAN HỆ (R)
    if not rel_name:
        issues.append("Tên quan hệ không được rỗng.")
        rel_issue_type = "out_of_catalog"
    elif normal(rel_name) in rel_norms:
        # Quan hệ đã có trong danh mục chính thức -> Hợp lệ 100% về mặt quan hệ!
        pass
    else:
        # Quan hệ chưa có trong danh mục -> tìm đề xuất quan hệ (kind == 'relations')
        rel_prop_candidates = [
            pid for pid in edge_pids
            if proposals.get(pid, {}).get("kind") == "relations"
        ]
        if not rel_prop_candidates:
            rel_norm_key = normal(rel_name)
            if proposals_by_kind_norm is not None:
                rel_prop_candidates = list(proposals_by_kind_norm.get(("relations", rel_norm_key), ()))
            else:
                rel_prop_candidates = [
                    pid for pid, p in proposals.items()
                    if p.get("kind") == "relations" and normal(p.get("name", "")) == rel_norm_key
                ]

        if rel_prop_candidates:
            for pid in rel_prop_candidates:
                prop = proposals.get(pid, {})
                p_st = prop.get("status", "pending")
                blocking_proposal_ids.append(pid)
                if p_st == "rejected":
                    issues.append(f"Quan hệ '{rel_name}' thuộc đề xuất đã bị từ chối ở Phân khu 1.")
                    rel_issue_type = "rejected_proposal"
                elif p_st == "pending":
                    issues.append(f"Quan hệ '{rel_name}' đang chờ duyệt đề xuất ở Phân khu 1.")
                    if rel_issue_type != "rejected_proposal":
                        rel_issue_type = "pending_proposal"
                elif p_st in ("approved", "merged"):
                    if normal(prop.get("canonical_name", "")) not in rel_norms:
                        issues.append(f"Mục danh mục của đề xuất quan hệ '{rel_name}' không còn tồn tại.")
                        rel_issue_type = "out_of_catalog"
        else:
            issues.append(f"Quan hệ '{rel_name}' chưa có trong danh mục quan hệ đã duyệt.")
            rel_issue_type = "out_of_catalog"

    # 2. KIỂM TRA LOẠI THỰC THỂ NGUỒN (S)
    if not src_node:
        issues.append(f"Thực thể nguồn ({src_id}) không tồn tại trong danh sách hoạt động.")
        src_issue_type = "out_of_catalog"
    else:
        s_kind = str(src_node.get("kind", "")).strip()
        if not s_kind:
            issues.append(f"Loại thực thể nguồn của '{src_name}' không được rỗng.")
            src_issue_type = "out_of_catalog"
        elif normal(s_kind) in type_norms:
            # Loại thực thể nguồn đã có trong danh mục chính thức -> Hợp lệ 100%!
            pass
        else:
            # Loại nguồn chưa có trong danh mục -> tìm đề xuất loại thực thể
            s_prop_candidates = [
                pid for pid in (src_pids + edge_pids)
                if proposals.get(pid, {}).get("kind") == "entity_types"
            ]
            if not s_prop_candidates:
                s_norm_key = normal(s_kind)
                if proposals_by_kind_norm is not None:
                    s_prop_candidates = list(proposals_by_kind_norm.get(("entity_types", s_norm_key), ()))
                else:
                    s_prop_candidates = [
                        pid for pid, p in proposals.items()
                        if p.get("kind") == "entity_types" and normal(p.get("name", "")) == s_norm_key
                    ]

            if s_prop_candidates:
                for pid in s_prop_candidates:
                    prop = proposals.get(pid, {})
                    p_st = prop.get("status", "pending")
                    blocking_proposal_ids.append(pid)
                    if p_st == "rejected":
                        issues.append(f"Loại thực thể nguồn '{s_kind}' ({src_name}) bị từ chối ở Phân khu 1.")
                        src_issue_type = "rejected_proposal"
                    elif p_st == "pending":
                        issues.append(f"Loại thực thể nguồn '{s_kind}' ({src_name}) đang chờ duyệt ở Phân khu 1.")
                        if src_issue_type != "rejected_proposal":
                            src_issue_type = "pending_proposal"
                    elif p_st in ("approved", "merged"):
                        if normal(prop.get("canonical_name", "")) not in type_norms:
                            issues.append(f"Mục danh mục của đề xuất loại nguồn '{s_kind}' không còn tồn tại.")
                            src_issue_type = "out_of_catalog"
            else:
                issues.append(f"Loại thực thể nguồn '{s_kind}' ({src_name}) chưa có trong danh mục đã duyệt.")
                src_issue_type = "out_of_catalog"

    # 3. KIỂM TRA LOẠI THỰC THỂ ĐÍCH (T)
    if not tgt_node:
        issues.append(f"Thực thể đích ({tgt_id}) không tồn tại trong danh sách hoạt động.")
        tgt_issue_type = "out_of_catalog"
    else:
        t_kind = str(tgt_node.get("kind", "")).strip()
        if not t_kind:
            issues.append(f"Loại thực thể đích của '{tgt_name}' không được rỗng.")
            tgt_issue_type = "out_of_catalog"
        elif normal(t_kind) in type_norms:
            # Loại thực thể đích đã có trong danh mục chính thức -> Hợp lệ 100%!
            pass
        else:
            # Loại đích chưa có trong danh mục -> tìm đề xuất loại thực thể
            t_prop_candidates = [
                pid for pid in (tgt_pids + edge_pids)
                if proposals.get(pid, {}).get("kind") == "entity_types"
            ]
            if not t_prop_candidates:
                t_norm_key = normal(t_kind)
                if proposals_by_kind_norm is not None:
                    t_prop_candidates = list(proposals_by_kind_norm.get(("entity_types", t_norm_key), ()))
                else:
                    t_prop_candidates = [
                        pid for pid, p in proposals.items()
                        if p.get("kind") == "entity_types" and normal(p.get("name", "")) == t_norm_key
                    ]

            if t_prop_candidates:
                for pid in t_prop_candidates:
                    prop = proposals.get(pid, {})
                    p_st = prop.get("status", "pending")
                    blocking_proposal_ids.append(pid)
                    if p_st == "rejected":
                        issues.append(f"Loại thực thể đích '{t_kind}' ({tgt_name}) bị từ chối ở Phân khu 1.")
                        tgt_issue_type = "rejected_proposal"
                    elif p_st == "pending":
                        issues.append(f"Loại thực thể đích '{t_kind}' ({tgt_name}) đang chờ duyệt ở Phân khu 1.")
                        if tgt_issue_type != "rejected_proposal":
                            tgt_issue_type = "pending_proposal"
                    elif p_st in ("approved", "merged"):
                        if normal(prop.get("canonical_name", "")) not in type_norms:
                            issues.append(f"Mục danh mục của đề xuất loại đích '{t_kind}' không còn tồn tại.")
                            tgt_issue_type = "out_of_catalog"
            else:
                issues.append(f"Loại thực thể đích '{t_kind}' ({tgt_name}) chưa có trong danh mục đã duyệt.")
                tgt_issue_type = "out_of_catalog"

    # 4. KẾT LUẬN TRẠNG THÁI TỔNG THỂ & BADGE HIỂN THỊ
    dedup_blocking_pids = list(dict.fromkeys(blocking_proposal_ids))
    issue_types = [t for t in (rel_issue_type, src_issue_type, tgt_issue_type) if t]

    if "rejected_proposal" in issue_types:
        status_code = "rejected_proposal"
        label = "Đề xuất bị từ chối"
        badge_label = "❌ Đề xuất bị từ chối"
    elif "pending_proposal" in issue_types:
        status_code = "pending_proposal"
        label = "Còn đề xuất chờ"
        if rel_issue_type == "pending_proposal" and not src_issue_type and not tgt_issue_type:
            badge_label = "⛔ Quan hệ chờ duyệt"
        elif src_issue_type == "pending_proposal" and not rel_issue_type and not tgt_issue_type:
            badge_label = "⛔ Loại nguồn chờ duyệt"
        elif tgt_issue_type == "pending_proposal" and not rel_issue_type and not src_issue_type:
            badge_label = "⛔ Loại đích chờ duyệt"
        else:
            badge_label = "⛔ Còn đề xuất chờ"
    elif "out_of_catalog" in issue_types:
        status_code = "out_of_catalog"
        label = "Ngoài danh mục"
        if rel_issue_type == "out_of_catalog" and not src_issue_type and not tgt_issue_type:
            badge_label = "⚠️ Quan hệ ngoài DM"
        elif src_issue_type == "out_of_catalog" and not rel_issue_type and not tgt_issue_type:
            badge_label = "⚠️ Loại nguồn ngoài DM"
        elif tgt_issue_type == "out_of_catalog" and not rel_issue_type and not src_issue_type:
            badge_label = "⚠️ Loại đích ngoài DM"
        else:
            badge_label = "⚠️ Ngoài danh mục"
    else:
        status_code = "valid"
        label = "Hợp lệ"
        badge_label = "✅ Hợp lệ"

    return {
        "status_code": status_code,
        "label": label,
        "badge_label": badge_label,
        "blocking_proposal_ids": dedup_blocking_pids,
        "issue": "; ".join(issues) if issues else "",
        "issues": issues,
        "rel_issue_type": rel_issue_type,
        "src_issue_type": src_issue_type,
        "tgt_issue_type": tgt_issue_type,
    }


def validate_edge_for_approval(
    project: dict,
    edge: dict,
    *,
    is_batch: bool = False,
    override_reason: str = "",
    self_loop_confirmed: bool = False,
    note: str = "",
    check_existing_override: bool = False,
    allow_schema_bypass: bool = False,
    precomputed: dict[str, Any] | None = None,
    include_evidence_snippets: bool = True,
) -> dict[str, Any]:
    """Validator thống nhất ở backend cho duyệt đơn, duyệt lô và kiểm tra xuất đồ thị (Trang 6)."""
    errors: list[str] = []
    warnings: list[str] = []

    if precomputed is not None and "nodes" in precomputed:
        nodes_by_id = precomputed["nodes"]
    else:
        nodes_by_id = {str(n.get("id", "")): n for n in project.get("nodes", []) if n.get("id")}
    src_id = str(edge.get("source") or "")
    tgt_id = str(edge.get("target") or "")

    if not src_id or not tgt_id:
        errors.append("Không thể duyệt quan hệ thiếu thực thể nguồn hoặc đích.")
    else:
        if src_id not in nodes_by_id:
            errors.append(f"Thực thể nguồn ({src_id}) không còn tồn tại trong danh sách hoạt động.")
        if tgt_id not in nodes_by_id:
            errors.append(f"Thực thể đích ({tgt_id}) không còn tồn tại trong danh sách hoạt động.")

    if not str(edge.get("relation") or "").strip():
        errors.append("Tên quan hệ không được rỗng.")

    doc_id = str(edge.get("doc_id", ""))
    if precomputed is not None and "docs_by_id" in precomputed:
        doc = precomputed["docs_by_id"].get(doc_id)
    else:
        doc = find_document(project, doc_id)
    if not doc or not str(doc.get("text", "")).strip():
        errors.append("Tài liệu nguồn của dữ kiện không tồn tại hoặc rỗng.")

    schema_info = inspect_edge_schema_status(project, edge, precomputed=precomputed)
    if schema_info["issue"]:
        if allow_schema_bypass:
            warnings.append(f"Cảnh báo Lược đồ (chấp nhận duyệt ngoại lệ): {schema_info['issue']}")
        else:
            errors.append(schema_info["issue"])

    is_self_loop = bool(src_id and tgt_id and src_id == tgt_id)
    if is_self_loop:
        if is_batch:
            if allow_schema_bypass:
                warnings.append("Cạnh tự nối (nguồn trùng đích) được chấp nhận theo chế độ duyệt ngoại lệ.")
            else:
                errors.append("Cạnh tự nối (nguồn trùng đích) bị loại khỏi tập duyệt hàng loạt; cần kiểm tra và xác nhận đơn lẻ.")
        else:
            already_confirmed = check_existing_override and bool(edge.get("self_loop_confirmed"))
            has_reason = bool(str(note or edge.get("review_note") or "").strip())
            if not (self_loop_confirmed or already_confirmed or allow_schema_bypass) or not (has_reason or allow_schema_bypass):
                errors.append(
                    "Cạnh tự nối (self-loop) cần tích xác nhận quan hệ có ý nghĩa tự nối và nhập lý do kiểm duyệt."
                )

    quote_str = str(edge.get("evidence") or "").strip()
    requires_override = False
    if not quote_str:
        if allow_schema_bypass:
            warnings.append("Quan hệ không có trích dẫn bằng chứng (duyệt ngoại lệ theo yêu cầu).")
            requires_override = True
        else:
            errors.append("Không thể duyệt quan hệ không có câu trích dẫn bằng chứng.")

    ev_ctx = evidence_context(
        project,
        edge,
        precomputed=precomputed,
        include_snippets=include_evidence_snippets,
    )
    if quote_str and doc:
        if not ev_ctx["found"]:
            requires_override = True
            if is_batch:
                if allow_schema_bypass:
                    warnings.append("Không tìm thấy trích dẫn nguyên văn trong tài liệu nguồn (duyệt ngoại lệ theo yêu cầu).")
                else:
                    errors.append("Không tìm thấy trích dẫn trong tài liệu nguồn (bản đầu không cho duyệt ngoại lệ hàng loạt).")
            else:
                eff_override = str(override_reason or "").strip() or (
                    str(edge.get("override_reason") or edge.get("review_note") or "").strip()
                    if (check_existing_override and edge.get("override"))
                    else ""
                )
                if not eff_override:
                    if allow_schema_bypass:
                        warnings.append("Bằng chứng không khớp nguyên văn (chấp nhận ngoại lệ theo yêu cầu).")
                    else:
                        errors.append(
                            "Bằng chứng không khớp nguyên văn tài liệu. Cần sửa bằng chứng hoặc nhập lý do xác nhận ngoại lệ trước khi duyệt."
                        )
        elif ev_ctx.get("ambiguous"):
            warnings.append("Câu trích dẫn xuất hiện ở nhiều vị trí trong tài liệu; nên chọn vị trí xác minh cụ thể.")

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "evidence_ctx": ev_ctx,
        "schema_info": schema_info,
        "requires_override": requires_override,
        "is_self_loop": is_self_loop,
    }


def is_edge_exportable(
    project: dict,
    edge: dict,
    *,
    precomputed: dict[str, Any] | None = None,
) -> bool:
    """Điều kiện đủ để một cạnh được xuất sang Trang 6 / JSON / CSV / Neo4j."""
    if edge.get("status") != STATUS_APPROVED:
        return False
    check = validate_edge_for_approval(
        project,
        edge,
        is_batch=False,
        check_existing_override=True,
        precomputed=precomputed,
        include_evidence_snippets=False,
    )
    return bool(check["ok"])


def approvable_edges(project: dict) -> list[str]:
    result: list[str] = []
    edges = project.get("edges", [])
    if not edges:
        return result
    ctx = build_curation_validation_context(project)
    for edge in edges:
        if edge.get("status") not in (STATUS_PENDING, STATUS_CHECK):
            continue
        val = validate_edge_for_approval(
            project,
            edge,
            is_batch=True,
            precomputed=ctx,
            include_evidence_snippets=False,
        )
        if val["ok"]:
            result.append(str(edge["id"]))
    return result

