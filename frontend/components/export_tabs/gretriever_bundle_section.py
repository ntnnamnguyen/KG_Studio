"""Thành phần UI tách biệt cho Tab 5: Sinh và xuất đúng Bộ 5 tệp Chuẩn G-Retriever."""
from __future__ import annotations

from typing import Any
import streamlit as st

from frontend.state.session import get_session_llm_params, sync_keyed_int, sync_keyed_value


def gretriever_bundle_cache_key(proj_id: str, fingerprint: str, *, approved_only: bool) -> str:
    """Khóa cache bộ 5 tệp gắn chặt với project_id, fingerprint đồ thị và nguồn approved/snapshot."""
    scope = "approved" if approved_only else "snapshot"
    fp_short = str(fingerprint or "none")[:16]
    return f"_kgqa_gretriever_bundle_{proj_id}_{scope}_{fp_short}"


def _build_question_preview_rows(records: list[dict[str, Any]], limit: int = 50) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for rec in records[:limit]:
        rows.append(
            {
                "question_id": str(rec.get("question_id", "")),
                "question_type": str(rec.get("question_type", "")),
                "directions": " -> ".join(str(d) for d in (rec.get("traversal_directions") or [])),
                "question": str(rec.get("question", "")),
                "answer_text": str(rec.get("answer_text", "")),
                "paths": str(len(rec.get("gold_paths") or [])),
                "review_status": str(rec.get("review_status", "auto_generated")),
            }
        )
    return rows


def render_gretriever_bundle_studio(
    graph_service: Any,
    target_project: dict[str, Any],
    *,
    proj_id: str,
    fingerprint: str,
    approved_only: bool = True,
) -> None:
    """Giao diện độc lập tạo và xuất đúng 5 tệp chuẩn G-Retriever (.ZIP)."""
    cache_key = gretriever_bundle_cache_key(proj_id, fingerprint, approved_only=approved_only)
    kp = f"p05_gret_studio_{proj_id}"

    with st.container(border=True):
        st.markdown("#### 🎯 Xuất Bộ Dữ liệu Huấn luyện Chuẩn G-Retriever (Đúng 5 Tệp)")
        st.caption(
            "Phiên bản tách biệt hoàn toàn với bộ QA Studio cũ. Xuất gọn đúng 5 tệp cần thiết cho huấn luyện G-Retriever: "
            "`nodes.csv`, `edges.csv`, `evidence.csv`, `questions.csv`, `schema_contract.json` (UTF-8 BOM), "
            "giữ nguyên tên loại thực thể & quan hệ gốc của dự án."
        )

        max_samples_key = f"{kp}_max_samples"
        use_para_key = f"{kp}_use_paraphrase"
        sync_keyed_int(max_samples_key, 500, (proj_id, approved_only), min_value=10, max_value=5000)
        sync_keyed_value(use_para_key, False, (proj_id, approved_only))

        c_num, c_opt, c_btn = st.columns([1.4, 2.0, 1.8], vertical_alignment="bottom")
        max_samples = c_num.number_input(
            "Số câu hỏi tối đa",
            min_value=10,
            max_value=5000,
            step=50,
            key=max_samples_key,
        )
        use_paraphrase = c_opt.checkbox(
            "✨ Kèm Paraphrase bằng LLM cho tự nhiên hơn",
            key=use_para_key,
            help="Dùng cấu hình LLM ở Sidebar/Bước 2 để viết lại câu hỏi tự nhiên hơn (tự giữ thực thể & chặn lộ đáp án).",
        )

        if c_btn.button(
            "⚡ Tạo Gói 5 Tệp G-Retriever",
            type="primary",
            width="stretch",
            key=f"{kp}_btn_build",
        ):
            with st.spinner("Đang tổng hợp nodes, edges, evidence, questions & schema_contract..."):
                bundle = graph_service.build_kgqa_training_bundle(
                    target_project,
                    approved_only=approved_only,
                    max_samples=int(max_samples),
                )
            st.session_state.pop(f"{cache_key}_pstats", None)
            st.session_state.pop(f"{cache_key}_para_warn", None)

            if use_paraphrase:
                llm_params = get_session_llm_params()
                if not llm_params:
                    st.session_state[f"{cache_key}_para_warn"] = (
                        "⚠️ Chưa cấu hình nhà cung cấp LLM / API key ở Sidebar hoặc Trang 2. "
                        "Đã giữ nguyên bộ 5 tệp với câu hỏi sinh tự động gốc."
                    )
                else:
                    with st.spinner("Đang paraphrase câu hỏi bằng LLM và hậu kiểm thực thể..."):
                        bundle, pstats = graph_service.paraphrase_kgqa_training_bundle(
                            bundle,
                            provider=llm_params["provider"],
                            api_key=llm_params["api_key"],
                            model=llm_params["model"],
                            base_url=llm_params["base_url"],
                            batch_size=12,
                            only_unparaphrased=True,
                        )
                        st.session_state[f"{cache_key}_pstats"] = pstats

            st.session_state[cache_key] = bundle

        para_warn = st.session_state.get(f"{cache_key}_para_warn")
        if para_warn:
            st.warning(para_warn)

        bundle: dict[str, Any] | None = st.session_state.get(cache_key)
        if not bundle:
            st.info("Nhấn **⚡ Tạo Gói 5 Tệp G-Retriever** để đóng gói bộ 5 tệp chuẩn sẵn sàng tải xuống.")
            return

        stats = bundle["stats"]
        pstats = st.session_state.get(f"{cache_key}_pstats")
        if pstats:
            st.success(
                f"✅ Đã paraphrase {pstats['accepted']}/{pstats['attempted']} câu "
                f"(chặn rơi thực thể: {pstats['rejected_entity_drop']}, chặn lộ đáp án: {pstats['rejected_answer_leak']})."
            )

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Nodes", f"{stats['nodes_count']:,}")
        m2.metric("Edges", f"{stats['edges_count']:,}")
        m3.metric("Evidence", f"{stats['evidence_count']:,}")
        m4.metric(
            "Questions",
            f"{stats['questions_count']:,}",
            help=(
                f"single_hop: {stats.get('single_hop_count', 0)} · "
                f"multi_hop: {stats.get('multi_hop_count', 0)} · "
                f"list: {stats.get('list_count', 0)}"
            ),
        )
        m5.metric("LLM Paraphrased", f"{stats.get('llm_paraphrased_count', 0):,}")

        st.download_button(
            "⬇️ Tải Bộ 5 Tệp Chuẩn G-Retriever (.ZIP)",
            data=bundle["zip_bytes"],
            file_name=f"gretriever_5files_{proj_id}.zip",
            mime="application/zip",
            type="primary",
            width="stretch",
            key=f"{kp}_dl_zip",
        )
        st.caption(
            "Bên trong tệp `.zip` gồm đúng 5 tệp: `nodes.csv`, `edges.csv`, `evidence.csv`, `questions.csv` và `schema_contract.json`."
        )

        with st.expander(f"📋 Xem trước questions.csv ({len(bundle['question_records']):,} câu)", expanded=False):
            st.dataframe(
                _build_question_preview_rows(bundle["question_records"], limit=50),
                width="stretch",
                hide_index=True,
            )

        with st.expander("📐 Xem schema_contract.json (loại thực thể & quan hệ dự án)", expanded=False):
            st.json(bundle["schema_contract"])
