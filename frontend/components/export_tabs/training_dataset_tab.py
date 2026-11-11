"""Component Tab 3 của Trang Khai thác: Sinh Dữ liệu Huấn luyện G-Retriever (Training QA Studio)."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st

from backend.domain.graph.service import csv_bytes


def render_training_dataset_tab(facade: Any, active_graph_project: dict, proj_id: str) -> None:
    """Tab 3: Phòng Sinh Bộ Dữ liệu Huấn luyện & Đánh giá G-Retriever Quy mô lớn (Training QA Studio)."""
    st.markdown("#### 🧬 Sinh Bộ Dữ liệu Huấn luyện G-Retriever Quy mô lớn (Human-like Natural Language QA)")
    st.caption(
        "Tự động khai phá cấu trúc đồ thị để sinh hàng nghìn mẫu câu hỏi - đáp án tiếng Việt **tự nhiên chuẩn văn phong con người**, "
        "loại bỏ hoàn toàn các mẫu câu máy móc. Bao phủ **6 nhóm cấu trúc suy luận đồ thị** (*2-Hop Bridge*, *2-Hop Intersection*, "
        "*Multi-Attribute Star*, *Explainable Path*, *1-Hop Factoid*, *1-Hop Inverse*) kèm ánh xạ chỉ số nguyên PyG và ngữ cảnh con `textualized_subgraph`."
    )

    edges = active_graph_project.get("edges", [])
    nodes = active_graph_project.get("nodes", [])
    if not edges:
        st.info("ℹ️ Cần có ít nhất một quan hệ ở trạng thái 'Đã duyệt' để sinh bộ dữ liệu huấn luyện.")
        return

    c_cfg1, c_cfg2, c_cfg3 = st.columns([1.5, 1.2, 1.3], vertical_alignment="bottom")
    qa_max_samples = int(
        c_cfg1.slider(
            "Số lượng mẫu huấn luyện cần sinh (Dataset Size)",
            min_value=200,
            max_value=5000,
            value=2000,
            step=100,
            key=f"_p06_train_ds_samples_{proj_id}",
            help="Hệ thống sẽ khai phá toàn bộ các đường đi đa bước và phân bổ đều vào 6 nhóm cấu trúc đồ thị.",
        )
    )
    train_pct = int(
        c_cfg2.slider(
            "Tỷ lệ phân chia Train (%)",
            min_value=60,
            max_value=90,
            value=80,
            step=5,
            key=f"_p06_train_pct_{proj_id}",
            help="Tỷ lệ dành cho tập Train. Phần còn lại chia đều cho Validation và Test.",
        )
    )
    run_gen_btn = c_cfg3.button(
        "⚡ 1. Khai phá & Sinh Bộ Dữ liệu Tự nhiên (~40ms)",
        type="primary",
        width="stretch",
        key=f"_p06_btn_gen_natural_qa_{proj_id}",
    )

    gen_ds_key = f"_p06_generated_train_ds_{proj_id}"
    train_ratio = train_pct / 100.0
    val_ratio = round((1.0 - train_ratio) / 2.0, 3)

    if run_gen_btn or gen_ds_key not in st.session_state:
        with st.spinner(f"Đang phân tích đồ thị và sinh {qa_max_samples} câu hỏi tiếng Việt tự nhiên..."):
            st.session_state[gen_ds_key] = facade.generate_training_qa_dataset(
                active_graph_project,
                max_samples=qa_max_samples,
                train_ratio=train_ratio,
                val_ratio=val_ratio,
                approved_only=True,
            )

    ds_data = st.session_state.get(gen_ds_key)
    if not ds_data:
        return

    all_samples: list[dict[str, Any]] = ds_data.get("all_samples") or []
    train_samples: list[dict[str, Any]] = ds_data.get("train_samples") or []
    val_samples: list[dict[str, Any]] = ds_data.get("val_samples") or []
    test_samples: list[dict[str, Any]] = ds_data.get("test_samples") or []

    st.divider()
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Tổng số mẫu QA", ds_data.get("total_samples", 0))
    m2.metric("Tập Train", f"{len(train_samples)} ({train_pct}%)")
    m3.metric("Tập Val", f"{len(val_samples)} ({round(val_ratio * 100)}%)")
    m4.metric("Tập Test", f"{len(test_samples)} ({round(val_ratio * 100)}%)")
    m5.metric("Cấu trúc suy luận", f"{len(ds_data.get('category_counts', {}))} Nhóm")

    col_cat, col_ai = st.columns([1.3, 1.0])
    with col_cat:
        with st.container(border=True):
            st.markdown("##### 📊 Phân bố 6 Nhóm Cấu trúc Suy luận Đồ thị (Graph Topologies)")
            cat_rows = [
                {"Nhóm Cấu trúc Suy luận": k, "Số lượng mẫu": v, "Tỷ lệ (%)": f"{round(v / max(1, len(all_samples)) * 100, 1)}%"}
                for k, v in (ds_data.get("category_counts") or {}).items()
            ]
            st.dataframe(cat_rows, width="stretch", hide_index=True)

    with col_ai:
        with st.container(border=True):
            st.markdown("##### 🤖 Tinh chỉnh / Paraphrase bằng AI (Tùy chọn)")
            st.caption(
                "Sử dụng LLM (DeepSeek / OpenAI) để diễn đạt lại một nhóm câu hỏi mẫu thành văn phong hỏi đáp đời thường 100%."
            )
            provider = str(st.session_state.get("llm_provider", "DeepSeek"))
            model = str(st.session_state.get("llm_model", "deepseek-chat"))
            st.write(f"Đang kết nối: `{provider}` (`{model}`)")
            if st.button("✨ Tinh chỉnh 15 câu hỏi mẫu bằng LLM", width="stretch", key=f"_p06_btn_paraphrase_{proj_id}"):
                with st.spinner(f"Đang gọi {provider} để paraphrase 15 câu hỏi mẫu..."):
                    top_sample = all_samples[:15]
                    paraphrased = facade.paraphrase_qa_questions_with_llm(
                        top_sample,
                        provider=provider,
                        model=model,
                    )
                    st.session_state[f"_p06_paraphrased_preview_{proj_id}"] = paraphrased
                    st.success("✅ Đã hoàn tất tinh chỉnh câu hỏi tự nhiên bằng LLM!")

            para_preview = st.session_state.get(f"_p06_paraphrased_preview_{proj_id}")
            if para_preview:
                with st.expander("👁️ So sánh Câu hỏi Trước và Sau khi AI Viết lại", expanded=True):
                    para_rows = [
                        {
                            "Gốc (Rule-based Tự nhiên)": it.get("original_question", it["question"]),
                            "Sau khi AI Paraphrase": it["question"],
                        }
                        for it in para_preview[:8]
                    ]
                    st.dataframe(para_rows, width="stretch", hide_index=True)

    with st.container(border=True):
        st.markdown("##### 🔍 Xem trước Dữ liệu Huấn luyện & Đánh giá (Preview Data Records)")
        filter_split = st.segmented_control(
            "Lọc theo tập dữ liệu:",
            ["Tất cả (All)", "train", "val", "test"],
            default="Tất cả (All)",
            key=f"_p06_sel_split_{proj_id}",
        )
        filtered_items = (
            all_samples
            if filter_split == "Tất cả (All)"
            else [x for x in all_samples if x.get("split") == filter_split]
        )
        sample_rows = [
            {
                "Mã": it["id"],
                "Split": it["split"],
                "Nhóm cấu trúc": it["category"],
                "Câu hỏi tiếng Việt tự nhiên": it["question"],
                "Đáp án ngắn": it["short_answer"],
                "Chuỗi suy luận trên đồ thị": it["gold_answer"],
            }
            for it in filtered_items[:40]
        ]
        st.dataframe(sample_rows, width="stretch", hide_index=True)

    st.markdown("##### ⬇️ Tải Xuất Dữ liệu Độc lập (Phục vụ Huấn luyện trên Colab / Server GPU)")
    dl_c1, dl_c2, dl_c3 = st.columns(3)
    train_bytes = "\n".join(json.dumps(x, ensure_ascii=False) for x in train_samples).encode("utf-8")
    val_bytes = "\n".join(json.dumps(x, ensure_ascii=False) for x in val_samples).encode("utf-8")
    test_bytes = "\n".join(json.dumps(x, ensure_ascii=False) for x in test_samples).encode("utf-8")

    dl_c1.download_button(
        f"⬇️ Tải train.jsonl ({len(train_samples)} mẫu)",
        data=train_bytes,
        file_name="train.jsonl",
        mime="application/x-ndjson",
        width="stretch",
        key=f"_p06_dl_train_{proj_id}",
    )
    dl_c2.download_button(
        f"⬇️ Tải val.jsonl ({len(val_samples)} mẫu)",
        data=val_bytes,
        file_name="val.jsonl",
        mime="application/x-ndjson",
        width="stretch",
        key=f"_p06_dl_val_{proj_id}",
    )
    dl_c3.download_button(
        f"⬇️ Tải test.jsonl ({len(test_samples)} mẫu)",
        data=test_bytes,
        file_name="test.jsonl",
        mime="application/x-ndjson",
        width="stretch",
        key=f"_p06_dl_test_{proj_id}",
    )

    dl_g1, dl_g2 = st.columns(2)
    node_idx_map = {n["id"]: idx for idx, n in enumerate(nodes)}
    pyg_nodes = [
        {
            "node_id": idx,
            "orig_id": n.get("id", ""),
            "node_attr": f"{n.get('name', '')} ({n.get('kind', '')}): {n.get('description', '')}".strip(),
        }
        for idx, n in enumerate(nodes)
    ]
    pyg_edges = [
        {
            "src": node_idx_map[e["source"]],
            "edge_attr": f"{e.get('relation', '')} | Bằng chứng: {e.get('evidence', '')}".strip(),
            "dst": node_idx_map[e["target"]],
            "orig_edge_id": e.get("id", ""),
        }
        for e in edges
        if e.get("source") in node_idx_map and e.get("target") in node_idx_map
    ]

    pyg_nodes_csv = csv_bytes(pyg_nodes, ["node_id", "orig_id", "node_attr"])
    pyg_edges_csv = csv_bytes(pyg_edges, ["src", "edge_attr", "dst", "orig_edge_id"])

    dl_g1.download_button(
        f"⬇️ Tải pyg_nodes.csv ({len(pyg_nodes)} đỉnh PyG)",
        data=pyg_nodes_csv,
        file_name="pyg_nodes.csv",
        mime="text/csv",
        width="stretch",
        key=f"_p06_dl_pyg_nodes_{proj_id}",
    )
    dl_g2.download_button(
        f"⬇️ Tải pyg_edges.csv ({len(pyg_edges)} cạnh PyG)",
        data=pyg_edges_csv,
        file_name="pyg_edges.csv",
        mime="text/csv",
        width="stretch",
        key=f"_p06_dl_pyg_edges_{proj_id}",
    )
