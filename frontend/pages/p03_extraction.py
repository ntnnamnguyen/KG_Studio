"""Màn hình 03: Bảng điều khiển Trích xuất Tri thức & Nhật ký từng bước (Step Traces).

Tuân thủ kiến trúc luồng 5 bước quy chuẩn theo layout-pipeline-proposal.md.
"""
from __future__ import annotations

import streamlit as st

from backend.facade import get_facade
from backend.integrations.llm import LLMGateway
from frontend.components.pipeline_banner import render_step_next_action
from frontend.components.step_traces_viewer import render_step_traces
from frontend.composition import get_ui_composition
from frontend.state.session import (
    navigate_to_step,
    sync_keyed_choice,
    sync_keyed_int,
    sync_keyed_value,
)
from shared.config_loader import CONFIG
from shared.constants import MODE_FREE_TRIPLES
from shared.secrets_manager import get_api_key


def _extraction_result_summary(stats: dict, mode: str) -> str:
    if mode == MODE_FREE_TRIPLES:
        return (
            f"Bộ ba trích xuất: {stats.get('extracted_triples', 0)}, "
            f"không hợp lệ: {stats.get('invalid_triples', 0)}, "
            f"bằng chứng không khớp: {stats.get('evidence_mismatch', 0)}. "
            "Không thêm thực thể hoặc cạnh vào đồ thị."
        )
    return f"Thực thể thêm: {stats.get('added_nodes', 0)}, Quan hệ thêm: {stats.get('added_edges', 0)}."


def render_extraction_page(project: dict) -> None:
    facade = get_facade()
    docs = project.get("documents", [])
    mode = project.get("extraction_mode", "closed")
    proj_id = str(project.get("project_id") or project.get("name") or "default")

    st.subheader(f"🚀 3. Trích xuất Tri thức (Chế độ: `{mode}`)")
    render_step_next_action("extraction", project)
    if mode == MODE_FREE_TRIPLES:
        st.info(
            "Baseline B giữ bộ ba thô và bằng chứng để đánh giá độc lập. Không cần danh mục, "
            "không sinh định nghĩa, truy xuất schema hay chuẩn hóa ngữ nghĩa. "
            "Tải kết quả gốc ở nhật ký; dựng KG thô và chạy thuật toán dùng chung tại Bước 5."
        )

    provider = st.session_state.get("llm_provider", LLMGateway.DEFAULT_PROVIDER)
    model = st.session_state.get("llm_model", LLMGateway.DEFAULT_MODELS.get(provider, "deepseek-chat"))
    base_url = st.session_state.get("llm_base_url", LLMGateway.resolve_base_url(provider))
    api_key = (st.session_state.get("llm_api_key") or "").strip()
    if not api_key:
        persisted = get_api_key(provider)
        if persisted:
            api_key = persisted
            st.session_state["llm_api_key"] = persisted
            st.session_state["sb_llm_key"] = persisted
            st.session_state["p02_llm_key"] = persisted

    in_tokens = int(st.session_state.get("llm_max_input_tokens", CONFIG["llm"].get("max_input_tokens", 16000)))
    out_tokens = int(st.session_state.get("llm_max_output_tokens", CONFIG["llm"].get("max_tokens", 16384)))
    default_chunk = int(st.session_state.get("extraction_chunk_size", CONFIG["extraction"]["chunk_size"]))
    default_overlap = int(CONFIG["extraction"]["overlap"])

    # 1. THẺ TÓM TẮT KẾT NỐI AI & PHƯƠNG PHÁP (CHỈ ĐỌC — MỘT NGUỒN SỬA Ở BƯỚC 2)
    spec = LLMGateway.provider_spec(provider)
    key_ready = (not spec.requires_api_key) or bool((api_key or "").strip())
    key_badge = "🟢 Đã cấu hình khóa" if key_ready else "🔴 Thiếu API key"
    with st.container(border=True):
        c_info, c_btn = st.columns([3.8, 1.4])
        c_info.markdown(
            f"**🤖 Kết nối AI & Phương pháp đang áp dụng:** `{mode}` · "
            f"`{provider}` / `{model}` · Input `{in_tokens:,}` / Output `{out_tokens:,}` tokens · {key_badge}"
        )
        if c_btn.button("⚙️ Đổi cấu hình ở Bước 2", key="p03_btn_goto_setup", width="stretch"):
            navigate_to_step("setup")
            st.rerun()

    if not docs:
        st.info("Chưa có tài liệu nào trong dự án. Hãy bổ sung tài liệu ở Bước 1 trước khi bắt đầu trích xuất.")
        return

    # Tính toán lượt trích xuất trước đó theo từng tài liệu
    runs_by_doc: dict[str, list[dict]] = {}
    for r in project.get("runs", []):
        if mode == MODE_FREE_TRIPLES and (
            r.get("extraction_mode") != MODE_FREE_TRIPLES or r.get("status") != "ok"
        ):
            continue
        did = r.get("doc_id")
        if did:
            runs_by_doc.setdefault(did, []).append(r)

    # Khởi tạo trạng thái chọn cho từng tài liệu nếu chưa có
    for d in docs:
        key = f"p03_doc_sel_{proj_id}_{d['id']}"
        if key not in st.session_state:
            st.session_state[key] = True

    # Danh sách tài liệu đang được đánh dấu chọn
    selected_docs = [d for d in docs if st.session_state.get(f"p03_doc_sel_{proj_id}_{d['id']}", True)]

    # 2. KHU VỰC CHỌN TÀI LIỆU TRÍCH XUẤT
    with st.container(border=True):
        st.markdown(f"##### 📑 Danh sách Chọn Tài liệu Trích xuất ({len(selected_docs)}/{len(docs)} file được chọn)")

        # Thanh công cụ: Tìm kiếm & Thao tác chọn nhanh
        tb_filter, tb_all, tb_none, tb_unextracted = st.columns([3.5, 1.4, 1.4, 2.2])
        filter_text = tb_filter.text_input(
            "Tìm tài liệu",
            placeholder="🔍 Nhập tên file để lọc nhanh...",
            key=f"p03_filter_doc_text_{proj_id}",
            label_visibility="collapsed",
        ).strip().lower()

        displayed_docs = [d for d in docs if not filter_text or filter_text in d.get("name", "").lower()]

        if tb_all.button("☑️ Chọn tất cả", key="btn_sel_all_docs", width="stretch"):
            for d in (displayed_docs if filter_text else docs):
                st.session_state[f"p03_doc_sel_{proj_id}_{d['id']}"] = True
            st.rerun()

        if tb_none.button("⬜ Bỏ chọn hết", key="btn_clear_all_docs", width="stretch"):
            for d in (displayed_docs if filter_text else docs):
                st.session_state[f"p03_doc_sel_{proj_id}_{d['id']}"] = False
            st.rerun()

        if tb_unextracted.button("⚪ Chọn file chưa trích xuất", key="btn_sel_unextracted_docs", width="stretch"):
            for d in docs:
                st.session_state[f"p03_doc_sel_{proj_id}_{d['id']}"] = (d["id"] not in runs_by_doc)
            st.rerun()

        # Bảng danh sách chọn tài liệu (tự cuộn nếu danh sách dài)
        with st.container(border=True, height=280 if len(displayed_docs) > 4 else "content"):
            h1, h2, h3 = st.columns([5.5, 2.3, 2.2])
            h1.caption("**TÊN TÀI LIỆU**")
            h2.caption("**DUNG LƯỢNG / SỐ ĐOẠN**")
            h3.caption("**TRẠNG THÁI TRÍCH XUẤT**")

            if not displayed_docs:
                st.info("Không tìm thấy tài liệu nào khớp với từ khóa tìm kiếm.")
            else:
                for doc in displayed_docs:
                    c1, c2, c3 = st.columns([5.5, 2.3, 2.2])
                    k = f"p03_doc_sel_{proj_id}_{doc['id']}"
                    c1.checkbox(
                        f"📄 **{doc['name']}**",
                        key=k,
                        help=f"ID: {doc['id']} | Phạm vi: {doc.get('place_scope', 'Chung')} | Nguồn: {doc.get('source_label', 'Không có')}",
                    )

                    chars = len(doc.get("text", ""))
                    est_chunks = max(1, len(facade.document_chunks(doc, limit=default_chunk, overlap=default_overlap))) if chars else 0
                    c2.write(f"{chars:,} ký tự (~{est_chunks} đoạn)")

                    if doc["id"] in runs_by_doc:
                        run_cnt = len(runs_by_doc[doc["id"]])
                        c3.markdown(f"🟢 **Đã trích xuất** ({run_cnt} lượt)")
                    else:
                        c3.markdown("⚪ *Chưa trích xuất*")

    # 3. PHẠM VI CHẠY & ĐIỀU KHIỂN TRÍCH XUẤT
    with st.container(border=True):
        st.markdown("##### ⚙️ Phạm vi & Điều khiển Trích xuất")
        default_workers = max(1, min(16, int(st.session_state.get("extraction_workers", 3))))
        default_extract_all = bool(st.session_state.get("p03_chk_extract_all", True))

        with st.expander("⚙️ Tùy chỉnh kỹ thuật (Phân đoạn & Đa luồng)", expanded=False):
            c1, c2, c3, c4 = st.columns([1.5, 1.2, 1.2, 1.5])
            chunk_size = c1.number_input("Kích thước đoạn (ký tự)", 500, 16000, default_chunk, 100)
            st.session_state["extraction_chunk_size"] = int(chunk_size)
            overlap = c2.number_input("Độ chồng lấp (ký tự)", 0, 1000, default_overlap, 50)

            sync_keyed_value("p03_chk_extract_all", default_extract_all, "init")
            extract_all = c3.checkbox(
                "Trích xuất tất cả",
                help="Tự động chia và trích xuất toàn bộ các đoạn của các tài liệu đã chọn.",
                key="p03_chk_extract_all",
            )
            if extract_all:
                max_chunks = 9999
                c4.caption("⚡ Sẽ xử lý **100% các đoạn** của các file đã chọn")
            else:
                max_chunks_key = f"p03_num_max_chunks_{proj_id}"
                sync_keyed_int(
                    max_chunks_key,
                    int(CONFIG["extraction"]["max_chunks_per_document"]),
                    (proj_id, "max_chunks"),
                    min_value=1,
                    max_value=200,
                )
                max_chunks = c4.number_input(
                    "Số đoạn tối đa / file",
                    min_value=1,
                    max_value=200,
                    help="Giới hạn số đoạn chạy thử nghiệm cho mỗi tài liệu.",
                    key=max_chunks_key,
                )

            st.markdown("---")
            th_col1, th_col2 = st.columns([2.2, 3.8])
            sync_keyed_int(
                "p03_slider_workers",
                default_workers,
                "init",
                min_value=1,
                max_value=16,
            )
            workers = th_col1.slider(
                "⚡ Số luồng gọi API đồng thời (Concurrent Threads)",
                min_value=1,
                max_value=16,
                step=1,
                key="p03_slider_workers",
                help="Số lượng request gọi LLM API gửi đi song song cùng lúc.",
            )
            st.session_state["extraction_workers"] = workers

            if workers == 1:
                th_col2.info("🐢 **Tuần tự (1 luồng)**: An toàn khi mạng yếu hoặc chạy local GPU nhỏ.")
            elif workers <= 5:
                th_col2.success(f"🚀 **Đa luồng khuyến nghị ({workers} luồng)**: Phù hợp DeepSeek API & OpenAI, hạn chế chạm Rate Limit.")
            elif workers <= 10:
                th_col2.warning(f"⚡ **Tốc độ cao ({workers} luồng)**: Cần hạn mức RPM/TPM cao để tránh lỗi 429.")
            else:
                th_col2.error(f"🔥 **Siêu tốc ({workers} luồng)**: Nguy cơ cao chạm Rate Limit ở tài khoản tiêu chuẩn.")

            st.caption(
                "Khuyến nghị tham khảo: DeepSeek 3–5 luồng · OpenAI Tier 2+ 4–8 luồng · Local Ollama 1–2 luồng. "
                "Hệ thống dùng khóa `RLock` trong tiến trình khi sáp nhập vào dự án."
            )

        if not selected_docs:
            st.warning("⚠️ Chưa có tài liệu nào được chọn. Vui lòng đánh dấu chọn ít nhất một file ở danh sách phía trên để bắt đầu trích xuất.")
        else:
            total_chunks = sum(
                len(facade.document_chunks(d, limit=int(chunk_size), overlap=int(overlap))[: int(max_chunks)])
                for d in selected_docs
            )
            scope_note = "100% đoạn" if extract_all else f"tối đa {int(max_chunks)} đoạn/file"
            st.info(
                f"📊 Phạm vi chạy: **{len(selected_docs)}/{len(docs)} tài liệu** · **{total_chunks} đoạn** "
                f"({scope_note}, ~{int(chunk_size)} ký tự/đoạn, chồng lấp {int(overlap)} ký tự) · "
                f"Phương pháp `{mode}` · `{workers}` luồng."
            )

        # Hàng nút thao tác: Chạy thử 1 đoạn mẫu VS Chạy toàn bộ
        btn_col_test, btn_col_run = st.columns([1.8, 2.2])
        btn_col_test.caption("⚠️ Chạy thử **vẫn gọi AI thực tế** trên 1 đoạn đầu, tốn token (nếu dùng API trả phí) và ghi vào nhật ký.")
        btn_col_run.caption("▶️ Chạy toàn bộ sẽ cập nhật tiến độ theo từng đoạn hoàn tất thực tế và lưu sau mỗi đoạn.")

        # NÚT 1: CHẠY THỬ 1 ĐOẠN MẪU (DRY-RUN)
        if btn_col_test.button(
            "🧪 Chạy thử 1 đoạn mẫu (Dry-run)",
            width="stretch",
            disabled=len(selected_docs) == 0,
            help="Chỉ trích xuất đoạn đầu tiên của tài liệu đầu tiên được chọn để kiểm tra độ chính xác của mô hình và danh mục.",
            key="btn_dry_run_one_chunk",
        ):
            spec = LLMGateway.provider_spec(provider)
            if spec.requires_api_key and not (api_key or "").strip():
                st.error(f"❌ Chưa có API key cho nhà cung cấp `{provider}`. Vui lòng nhập API Key ở thanh bên hoặc tab '2. Thiết lập' trước khi chạy.")
            else:
                target_doc = selected_docs[0]
                first_chunks = facade.document_chunks(target_doc, limit=int(chunk_size), overlap=int(overlap))
                if not first_chunks:
                    st.error("Không tìm thấy đoạn văn bản nào trong tài liệu đã chọn.")
                else:
                    target_rec = first_chunks[0]
                    with st.spinner(f"Đang chạy thử đoạn #{target_rec['chunk_number']} của '{target_doc['name']}'..."):
                        try:
                            out = facade.extract_chunk(
                                project,
                                target_doc,
                                target_rec,
                                provider=provider,
                                api_key=api_key,
                                model=model,
                                base_url=base_url,
                                max_tokens=int(st.session_state["llm_max_output_tokens"]),
                                max_input_tokens=int(st.session_state["llm_max_input_tokens"]),
                            )
                            if mode != MODE_FREE_TRIPLES:
                                facade.save_project(project)
                            st.success(
                                f"✅ Chạy thử thành công đoạn #{target_rec['chunk_number']}! "
                                + _extraction_result_summary(out.ingest_stats, mode)
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(
                                "Lượt baseline gặp lỗi. Xem metadata và trạng thái lượt chạy trong nhật ký."
                                if mode == MODE_FREE_TRIPLES
                                else f"Lỗi khi chạy thử nghiệm: {exc}"
                            )

        # NÚT 2: BẮT ĐẦU TRÍCH XUẤT TOÀN BỘ PHẦN ĐÃ CHỌN
        if btn_col_run.button(
            f"▶️ Bắt đầu trích xuất phần đã chọn ({workers} luồng)",
            type="primary",
            width="stretch",
            disabled=len(selected_docs) == 0,
            key="btn_run_full_extraction",
        ):
            spec = LLMGateway.provider_spec(provider)
            if spec.requires_api_key and not (api_key or "").strip():
                st.error(f"❌ Chưa có API key cho nhà cung cấp `{provider}`. Vui lòng nhập API Key ở thanh bên hoặc tab '2. Thiết lập' trước khi chạy.")
            else:
                all_tasks = []
                for doc in selected_docs:
                    records = facade.document_chunks(doc, limit=int(chunk_size), overlap=int(overlap))[: int(max_chunks)]
                    for rec in records:
                        all_tasks.append((doc, rec))

                progress = st.progress(0.0, text=f"Đang chuẩn bị tiến trình trích xuất ({workers} luồng)...")
                status_box = st.empty()

                def update_progress(done_idx, total_cnt, doc, rec, out, err):
                    pct = done_idx / max(1, total_cnt)
                    if err:
                        msg = f"⚠️ ({done_idx}/{total_cnt}) Lỗi tại {doc.get('name', '')} đoạn #{rec.get('chunk_number', '?')}"
                        if mode != MODE_FREE_TRIPLES:
                            msg += f": {err}"
                    else:
                        stats = getattr(out, "ingest_stats", {}) if out else {}
                        msg = (
                            f"⚡ ({done_idx}/{total_cnt}) Đã xử lý {doc.get('name', '')} đoạn #{rec.get('chunk_number', '?')} "
                            + _extraction_result_summary(stats, mode)
                        )
                    progress.progress(pct, text=f"Tiến độ: {done_idx}/{total_cnt} đoạn ({int(pct*100)}%) · {workers} luồng đang chạy...")
                    status_box.caption(msg)

                summary = facade.extract_chunks_parallel(
                    project,
                    all_tasks,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    max_tokens=int(st.session_state["llm_max_output_tokens"]),
                    max_input_tokens=int(st.session_state["llm_max_input_tokens"]),
                    max_workers=workers,
                    on_progress=update_progress,
                    save_after_chunk=True,
                )

                failed_tasks_key = f"p03_last_failed_tasks_{proj_id}"
                st.session_state[failed_tasks_key] = summary.get("failed_tasks", [])

                if summary.get("failed_tasks"):
                    st.warning(f"⚠️ Đã hoàn tất với {summary['success_count']} đoạn thành công và {len(summary['failed_tasks'])} đoạn gặp lỗi.")
                else:
                    st.success(f"🎉 Hoàn tất thành công 100% ({summary['success_count']}/{len(all_tasks)} đoạn) cho {len(selected_docs)} tài liệu!")
                st.rerun()

        # Hiển thị nút khắc phục khi có các đoạn bị lỗi
        last_failed = st.session_state.get(f"p03_last_failed_tasks_{proj_id}", [])
        if last_failed:
            st.warning(f"⚠️ Phát hiện {len(last_failed)} đoạn gặp lỗi trong phiên chạy gần nhất.")
            if st.button("🔄 Chạy lại các đoạn gặp lỗi", key="btn_retry_failed_chunks", width="stretch"):
                retry_tasks = [(item["doc"], item["rec"]) for item in last_failed if "doc" in item and "rec" in item]
                retry_progress = st.progress(0.0, text=f"Đang chạy lại {len(retry_tasks)} đoạn lỗi...")
                retry_status = st.empty()

                def update_retry_progress(done_idx, total_cnt, doc, rec, out, err):
                    pct = done_idx / max(1, total_cnt)
                    retry_progress.progress(pct, text=f"Đang thử lại: {done_idx}/{total_cnt} đoạn...")
                    if err:
                        message = f"❌ Thất bại đoạn #{rec.get('chunk_number')}"
                        if mode != MODE_FREE_TRIPLES:
                            message += f": {err}"
                        retry_status.caption(message)
                    else:
                        retry_status.caption(f"✅ Thành công đoạn #{rec.get('chunk_number')}")

                retry_summary = facade.extract_chunks_parallel(
                    project,
                    retry_tasks,
                    provider=provider,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    max_tokens=int(st.session_state["llm_max_output_tokens"]),
                    max_input_tokens=int(st.session_state["llm_max_input_tokens"]),
                    max_workers=workers,
                    on_progress=update_retry_progress,
                    save_after_chunk=True,
                )
                st.session_state[f"p03_last_failed_tasks_{proj_id}"] = retry_summary.get("failed_tasks", [])
                if retry_summary.get("failed_tasks"):
                    st.error(f"Vẫn còn {len(retry_summary['failed_tasks'])} đoạn gặp lỗi sau khi thử lại.")
                else:
                    st.success("Tất cả các đoạn lỗi đã được xử lý thành công!")
                st.rerun()

    # 4. NHẬT KÝ TRÍCH XUẤT & STEP TRACES
    runs = list(reversed(project.get("runs", [])))
    if runs:
        st.divider()
        st.subheader(f"📜 Nhật ký Trích xuất ({len(runs)} lượt gần nhất)")
        run_sel_key = f"p03_sel_run_{proj_id}"
        run_options = list(range(len(runs)))
        sync_keyed_choice(run_sel_key, run_options, 0, (proj_id, len(runs)))
        selected_idx = st.selectbox(
            "Chọn lượt xử lý để xem chi tiết & Step Traces",
            run_options,
            format_func=lambda i: f"#{len(runs) - i} · {runs[i].get('doc_name', '')} (Đoạn {runs[i].get('chunk_number', 0)}) — mode={runs[i].get('extraction_mode', '')}",
            key=run_sel_key,
        )
        run = runs[selected_idx]
        run_status = run.get("status", "unknown")
        status_icon = "🟢 Thành công" if run_status == "ok" else ("🔴 Lỗi" if run_status == "error" else f"⚪ {run_status}")
        run_mode = run.get("extraction_mode", "")
        with st.container(border=True):
            s1, s2, s3 = st.columns([1.6, 2.2, 2.2])
            s1.markdown(f"**Trạng thái:** {status_icon}")
            s2.markdown(f"**Tài liệu:** `{run.get('doc_name', '')}` · Đoạn `{run.get('chunk_number', 0)}`")
            s3.markdown(f"**Token:** In `{int(run.get('input_tokens', 0) or 0):,}` · Out `{int(run.get('output_tokens', 0) or 0):,}`")
            stats_summary = _extraction_result_summary(run.get("ingest_stats") or run, run_mode)
            st.caption(f"Phương pháp: `{run_mode}` | {stats_summary}")
            if run_status == "error" and (run.get("error") or run.get("error_kind")):
                st.warning(f"Chi tiết lỗi ({run.get('error_kind', 'error')}): {run.get('error', '')}")

        if run_mode == MODE_FREE_TRIPLES:
            st.caption("Kết quả baseline độc lập; các số liệu dưới đây không phải số cạnh đồ thị đã duyệt.")
            if run_status == "error":
                st.warning("Lượt baseline gặp lỗi. Metadata bên dưới giúp đối chiếu request; lượt lỗi vẫn được giữ trong bản xuất đánh giá.")

        with st.expander("🔧 Chi tiết kỹ thuật & Nhật ký Engine", expanded=False):
            render_step_traces(run, use_expander=False)
            if run_mode == MODE_FREE_TRIPLES:
                payload = run.get("extraction_payload")
                report = run.get("validation_report")
                if isinstance(payload, dict):
                    st.markdown("##### Bộ ba thô")
                    st.json(payload)
                if isinstance(report, dict):
                    st.markdown("##### Chẩn đoán cấu trúc và bằng chứng")
                    st.json(report)
                st.markdown("##### Metadata đối chứng baseline")
                st.json({
                    key: run.get(key, "")
                    for key in (
                        "run_id", "doc_id", "chunk_number", "chunk_hash", "status",
                        "provider", "model", "prompt_version_id", "prompt_content_hash",
                        "prepared_request_hash", "input_tokens", "output_tokens",
                    )
                })
            st.markdown("##### Phản hồi JSON gốc từ LLM")
            st.code(run.get("raw_response", ""), language="json")
        if any(r.get("extraction_mode") == MODE_FREE_TRIPLES for r in runs):
            baseline_data = get_ui_composition().extraction_service.export_free_triples_results(project)
            st.download_button(
                "⬇️ Tải toàn bộ kết quả baseline B (JSON)",
                data=baseline_data,
                file_name="free_triples_baseline.json",
                mime="application/json",
                key="p03_download_free_triples_results",
                help="Gồm kết quả thô, chẩn đoán và provenance của các lượt baseline; không lọc theo trạng thái duyệt schema.",
            )

    # 5. ĐIỀU HƯỚNG SANG BƯỚC TIẾP THEO
    st.divider()
    with st.container(border=True):
        col_msg, col_btn = st.columns([3.5, 1.5])
        if mode == MODE_FREE_TRIPLES:
            col_msg.markdown(
                "Kết quả baseline B được tải trực tiếp ở nhật ký, không qua bước duyệt hoặc chuẩn hóa schema. "
                "Chuyển sang Bước 5 để chọn runs, dựng KG thô và đối sánh thuật toán."
            )
            if col_btn.button("➡️ Xem KG baseline ở Bước 5", type="primary", width="stretch", key="p03_btn_baseline_graph"):
                navigate_to_step("explore")
                st.rerun()
            if col_btn.button("➡️ Về Bước 2: Thiết lập", width="stretch", key="p03_btn_baseline_setup"):
                navigate_to_step("setup")
                st.rerun()
        else:
            col_msg.markdown(
                "➡️ **Sẵn sàng chuẩn hóa dữ liệu?** "
                "Chuyển sang Bước 4 để duyệt các quan hệ, kiểm tra bằng chứng, và giải quyết trùng lặp thực thể."
            )
            if col_btn.button("➡️ Chuyển sang Bước 4: Rà soát & Chuẩn hóa", type="primary", width="stretch", key="p03_btn_goto_review"):
                navigate_to_step("review")
                st.rerun()
