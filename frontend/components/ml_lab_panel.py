"""Component giao diện ML Lab & Active Learning tích hợp cho người dùng."""
from __future__ import annotations

import streamlit as st

from frontend.client import get_client
from ml_lab.evaluation.benchmark import run_retriever_benchmark
from ml_lab.trainers.finetune_llm_lora import generate_lora_training_bundle
from ml_lab.trainers.train_canonicalizer import train_canonicalizer_model
from ml_lab.trainers.train_schema_retriever import train_schema_retriever_model


def render_ml_lab_panel(project: dict, save_cb, *, use_expander: bool = False) -> None:
    client = get_client()

    def _render_body() -> None:
        st.caption(
            "Khu Nghiên cứu độc lập: biến các quyết định **Duyệt quan hệ** và **Hợp nhất đề xuất EDC** thành bộ dữ liệu chuẩn "
            "để huấn luyện mô hình Schema Retriever (+R) và Target Alignment."
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("1. Xuất Dataset Active Learning", key="ml_export_btn", width="stretch"):
                report = client.export_training_datasets(project)
                st.session_state["ml_last_export"] = report
                st.success(
                    f"Đã xuất: {report['sr_triplets_count']} mẫu +R, "
                    f"{report['canonicalization_pairs_count']} cặp đồng nghĩa, "
                    f"{report['sft_records_count']} mẫu SFT."
                )

        export_info = st.session_state.get("ml_last_export")
        model_tag = st.text_input("Tên phiên bản mô hình muốn lưu vào Registry", value="sr-vi-custom", key="ml_model_tag")

        with col2:
            if st.button("2. Train Schema Retriever (+R)", key="ml_train_sr_btn", width="stretch"):
                report = export_info or client.export_training_datasets(project)
                meta = train_schema_retriever_model(report["files"]["sr_triplets"], model_name=model_tag)
                project.setdefault("edc_plus_r_settings", {})["embedder_model"] = meta["model_id"]
                save_cb(project)
                st.success(f"Đã huấn luyện & kích hoạt `{meta['model_id']}` (MRR={meta['metrics']['mrr']:.2f}).")

        with col3:
            if st.button("3. Train Target Aligner", key="ml_train_canon_btn", width="stretch"):
                report = export_info or client.export_training_datasets(project)
                meta = train_canonicalizer_model(report["files"]["canonicalization_pairs"], model_name=f"{model_tag}-aligner")
                project.setdefault("edc_plus_r_settings", {})["embedder_model"] = meta["model_id"]
                save_cb(project)
                st.success(f"Đã huấn luyện & kích hoạt `{meta['model_id']}`.")

        col4, col5 = st.columns(2)
        with col4:
            if st.button("📊 Chạy Benchmark so sánh các Model", key="ml_bench_btn", width="stretch"):
                report = export_info or client.export_training_datasets(project)
                board = run_retriever_benchmark(report["files"]["sr_triplets"])
                st.dataframe(board, width="stretch", hide_index=True)
        with col5:
            if st.button("📦 Sinh gói QLoRA Fine-tune cho LLM", key="ml_lora_btn", width="stretch"):
                report = export_info or client.export_training_datasets(project)
                bundle = generate_lora_training_bundle(report["files"]["sft_extractions"], adapter_name=f"{model_tag}-lora")
                st.info(f"Đã tạo kịch bản QLoRA tại: `{bundle['script_path']}` ({bundle['sft_samples']} mẫu).")

    if use_expander:
        with st.expander("🧪 ML Lab & Huấn luyện Mô hình (+R / Target Alignment / Active Learning)", expanded=False):
            _render_body()
    else:
        _render_body()

