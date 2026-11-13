"""Khởi tạo Session State và tính toán mức độ sẵn sàng quy trình 5 bước."""
from __future__ import annotations

from typing import Any

import streamlit as st

from backend.facade import get_facade
from backend.integrations.llm import LLMGateway
from shared.config_loader import CONFIG
from shared.constants import MODE_FREE_TRIPLES, STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING
from shared.secrets_manager import get_api_key
from .core import PAGE_LABELS, get_active_step, navigate_to_step, normalize_page_label
from .curation_state import reset_curation_state_if_project_changed
from .edc_state import reset_edc_state_if_project_changed


def compute_pipeline_readiness(project: dict) -> dict[str, Any]:
    """Đánh giá điều kiện sẵn sàng, tiến độ và hành động gợi ý tiếp theo cho quy trình 5 bước."""
    docs = project.get("documents", [])
    runs = project.get("runs", [])
    nodes = project.get("nodes", [])
    edges = project.get("edges", [])
    proposals = project.get("schema_proposals", [])
    errors = project.get("chunk_errors", {})
    baseline = project.get("extraction_mode") == MODE_FREE_TRIPLES
    if baseline:
        runs = [run for run in runs if run.get("extraction_mode") == MODE_FREE_TRIPLES]
        errors = {str(run.get("run_id", index)): run for index, run in enumerate(runs) if run.get("status") == "error"}
        nodes, edges, proposals = [], [], []

    # 1. Tài liệu
    has_docs = len(docs) > 0
    total_chars = sum(int(d.get("chars", len(d.get("text", "")))) for d in docs)
    doc_state = "ready" if has_docs else "empty"
    doc_badge = "✓" if has_docs else "○"

    # 2. Thiết lập
    has_rel_cat = bool(project.get("relations"))
    has_type_cat = bool(project.get("entity_types"))
    setup_ready = project.get("extraction_mode") == MODE_FREE_TRIPLES or (has_rel_cat and has_type_cat)
    setup_state = "ready" if setup_ready else "warning"
    setup_badge = "✓" if setup_ready else "!"

    # 3. Trích xuất
    has_runs = len(runs) > 0
    has_errors = len(errors) > 0
    if has_errors:
        ext_state = "partial_failed"
        ext_badge = "!"
    elif has_runs:
        ext_state = "done"
        ext_badge = "✓"
    else:
        ext_state = "empty"
        ext_badge = "○"

    # 4. Rà soát
    approved_count = sum(1 for e in edges if e.get("status") == STATUS_APPROVED)
    pending_edges = sum(1 for e in edges if e.get("status") == STATUS_PENDING)
    check_edges = sum(1 for e in edges if e.get("status") == STATUS_CHECK)
    pending_props = sum(1 for p in proposals if p.get("status") == "pending")
    total_needs_review = pending_edges + check_edges + pending_props

    if total_needs_review > 0:
        rev_state = "pending_work"
        rev_badge = "●"
    elif approved_count > 0:
        rev_state = "clean"
        rev_badge = "✓"
    else:
        rev_state = "empty"
        rev_badge = "○"

    # 5. Khai thác
    has_approved = approved_count > 0
    can_explore = has_approved or (baseline and any(run.get("status") == "ok" for run in runs))
    exp_state = "ready" if can_explore else "empty"
    exp_badge = "✓" if can_explore else "○"

    # Xác định hành động tiếp theo tổng thể của dự án
    if not has_docs:
        overall_next = {
            "step_id": "documents",
            "step_index": 0,
            "title": "Tải tài liệu nguồn đầu tiên",
            "reason": "Dự án chưa có tài liệu văn bản để trích xuất tri thức.",
            "button_text": "➡️ Thêm tài liệu ở Bước 1",
        }
    elif not has_runs:
        overall_next = {
            "step_id": "extraction",
            "step_index": 2,
            "title": "Bắt đầu trích xuất tri thức",
            "reason": f"Đã có {len(docs)} tài liệu sẵn sàng. Chạy trích xuất thực thể & quan hệ.",
            "button_text": "➡️ Bắt đầu trích xuất ở Bước 3",
        }
    elif has_errors:
        overall_next = {
            "step_id": "extraction",
            "step_index": 2,
            "title": f"Xử lý {len(errors)} đoạn văn bản gặp lỗi",
            "reason": "Có đoạn trích xuất gặp sự cố kết nối hoặc giới hạn token.",
            "button_text": "➡️ Xem và chạy lại đoạn lỗi ở Bước 3",
        }
    elif project.get("extraction_mode") == MODE_FREE_TRIPLES:
        overall_next = {
            "step_id": "explore", "step_index": 4,
            "title": "Dựng KG thô và đối sánh thuật toán",
            "reason": "Chọn baseline runs ở Bước 5 để dựng graph dẫn xuất, không qua duyệt schema.",
            "button_text": "➡️ Xem KG baseline ở Bước 5",
        }
    elif total_needs_review > 0:
        overall_next = {
            "step_id": "review",
            "step_index": 3,
            "title": f"Rà soát {total_needs_review} mục dữ kiện & thuật ngữ",
            "reason": f"Còn {pending_edges} quan hệ chờ duyệt và {pending_props} đề xuất danh mục.",
            "button_text": "➡️ Rà soát dữ kiện ở Bước 4",
        }
    elif has_approved:
        overall_next = {
            "step_id": "explore",
            "step_index": 4,
            "title": "Khai thác đồ thị & Xuất dữ liệu",
            "reason": f"Toàn bộ {approved_count} dữ kiện đã được duyệt hợp lệ 100%.",
            "button_text": "➡️ Khai thác & Xuất đồ thị ở Bước 5",
        }
    else:
        overall_next = {
            "step_id": "documents",
            "step_index": 0,
            "title": "Thêm tài liệu nghiên cứu mới",
            "reason": "Dự án đã hoàn tất các dữ kiện hiện có.",
            "button_text": "➡️ Thêm tài liệu mới ở Bước 1",
        }

    return {
        "documents": {
            "state": doc_state,
            "badge": doc_badge,
            "ready": has_docs,
            "count": len(docs),
            "total_chars": total_chars,
        },
        "setup": {
            "state": setup_state,
            "badge": setup_badge,
            "ready": setup_ready,
            "mode": project.get("extraction_mode", "closed"),
        },
        "extraction": {
            "state": ext_state,
            "badge": ext_badge,
            "ready": has_runs and not has_errors,
            "runs_count": len(runs),
            "errors_count": len(errors),
        },
        "review": {
            "state": rev_state,
            "badge": rev_badge,
            "ready": total_needs_review == 0 and approved_count > 0,
            "pending_edges": pending_edges,
            "check_edges": check_edges,
            "pending_props": pending_props,
            "needs_review_count": total_needs_review,
            "approved_count": approved_count,
        },
        "explore": {
            "state": exp_state,
            "badge": exp_badge,
            "ready": can_explore,
            "approved_count": approved_count,
            "nodes_count": len(nodes),
            "edges_count": len(edges),
        },
        "overall_next": overall_next,
    }


def ensure_session_state() -> dict:
    """Bảo đảm st.session_state chứa project đang mở, cấu hình LLM và trạng thái bảng."""
    facade = get_facade()
    if "active_project_name" not in st.session_state:
        projects = facade.list_projects()
        default_name = projects[0] if projects else CONFIG["app"]["default_project_name"]
        st.session_state["active_project_name"] = default_name

    curr_proj = st.session_state.get("project")
    needs_reload = (
        curr_proj is None
        or not isinstance(curr_proj, dict)
        or not curr_proj.get("name")
        or st.session_state.get("_loaded_name") != st.session_state["active_project_name"]
    )
    if needs_reload:
        proj = facade.load_project(st.session_state["active_project_name"])
        st.session_state["project"] = proj
        st.session_state["_loaded_name"] = proj.get("name", st.session_state["active_project_name"])
        reset_edc_state_if_project_changed(proj, st.session_state)
        reset_curation_state_if_project_changed(proj, st.session_state)
    else:
        reset_edc_state_if_project_changed(st.session_state["project"], st.session_state)
        reset_curation_state_if_project_changed(st.session_state["project"], st.session_state)

    st.session_state.setdefault("active_page", PAGE_LABELS[0])
    cur_provider = st.session_state.setdefault("llm_provider", LLMGateway.DEFAULT_PROVIDER)
    st.session_state.setdefault("llm_model", LLMGateway.DEFAULT_MODELS.get(cur_provider, "deepseek-chat"))
    st.session_state.setdefault("llm_base_url", LLMGateway.resolve_base_url(cur_provider))

    # Nạp API key an toàn từ secrets manager nếu chưa có
    if "llm_api_key" not in st.session_state or not st.session_state["llm_api_key"]:
        persisted_key = get_api_key(cur_provider)
        st.session_state["llm_api_key"] = persisted_key
    else:
        st.session_state.setdefault("llm_api_key", "")

    rec_tok = LLMGateway.recommend_token_limits(
        st.session_state["llm_provider"],
        st.session_state["llm_model"],
    )
    st.session_state.setdefault("llm_max_input_tokens", int(CONFIG.get("llm", {}).get("max_input_tokens", rec_tok["max_input_tokens"])))
    st.session_state.setdefault("llm_max_output_tokens", int(CONFIG.get("llm", {}).get("max_tokens", rec_tok["max_output_tokens"])))
    st.session_state.setdefault("extraction_chunk_size", int(CONFIG.get("extraction", {}).get("chunk_size", rec_tok["recommended_chunk_size"])))

    # Khởi tạo giá trị ban đầu cho các widget keys để tránh lỗi rỗng
    for k, v in [
        ("sb_llm_provider", cur_provider),
        ("p02_llm_prov", cur_provider),
        ("sb_llm_key", st.session_state["llm_api_key"]),
        ("p02_llm_key", st.session_state["llm_api_key"]),
        ("sb_llm_model", st.session_state["llm_model"]),
        ("p02_llm_model", st.session_state["llm_model"]),
        ("sb_llm_url", st.session_state["llm_base_url"]),
        ("p02_llm_url", st.session_state["llm_base_url"]),
        ("sb_llm_max_in", st.session_state["llm_max_input_tokens"]),
        ("p02_llm_max_in", st.session_state["llm_max_input_tokens"]),
        ("sb_llm_max_out", st.session_state["llm_max_output_tokens"]),
        ("p02_llm_max_out", st.session_state["llm_max_output_tokens"]),
    ]:
        st.session_state.setdefault(k, v)

    return st.session_state["project"]


__all__ = [
    "compute_pipeline_readiness",
    "ensure_session_state",
    "get_active_step",
    "navigate_to_step",
    "normalize_page_label",
]
