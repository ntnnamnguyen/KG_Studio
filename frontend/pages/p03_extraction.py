"""Màn hình 03: Bảng điều khiển Trích xuất Tri thức & Nhật ký từng bước (Step Traces).

Tuân thủ kiến trúc luồng 5 bước quy chuẩn theo layout-pipeline-proposal.md.
"""
from __future__ import annotations

import streamlit as st

from backend.facade import get_facade
from backend.integrations.llm import LLMGateway
from frontend.components.pipeline_banner import render_step_next_action
from frontend.components.step_traces_viewer import render_step_traces
from frontend.state.session import navigate_to_step
from shared.config_loader import CONFIG, save_llm_token_config_to_toml
from shared.secrets_manager import get_api_key, mask_api_key


def render_extraction_page(project: dict) -> None:
    facade = get_facade()
    docs = project.get("documents", [])
    mode = project.get("extraction_mode", "closed")

    st.subheader(f"🚀 3. Trích xuất Tri thức (Chế độ: `{mode}`)")
    render_step_next_action("extraction", project)

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

    # 1. KHU VỰC THIẾT LẬP KẾT NỐI & TOKEN (Gọn gàng trong Expander)
    with st.expander(
        f"🎚️ Cấu hình Token & Mô hình đang kích hoạt (`{provider}` · `{model}` | In: {in_tokens:,} · Out: {out_tokens:,})",
        expanded=False,
    ):
        t1, t2, t3, t4 = st.columns([1.8, 1.8, 1.0, 1.0])
        new_in_tokens = t1.slider(
            "📥 Lượng Token đầu vào tối đa (Input Tokens)",
            min_value=1024,
            max_value=128000,
            value=in_tokens,
            step=1024,
            key="p03_slider_in_tokens",
        )
        new_out_tokens = t2.slider(
            "📤 Lượng Token đầu ra tối đa (Output / max_tokens)",
            min_value=512,
            max_value=65536,
            value=out_tokens,
            step=512,
            key="p03_slider_out_tokens",
        )
        st.session_state["llm_max_input_tokens"] = new_in_tokens
        st.session_state["llm_max_output_tokens"] = new_out_tokens

        if t3.button("⚡ Auto theo mô hình", width="stretch", key="p03_btn_auto_tokens"):
            rec = LLMGateway.recommend_token_limits(provider, model)
            st.session_state["llm_max_input_tokens"] = rec["max_input_tokens"]
            st.session_state["llm_max_output_tokens"] = rec["max_output_tokens"]
            st.session_state["extraction_chunk_size"] = rec["recommended_chunk_size"]
            st.success(
                f"Đã tự động điều chỉnh theo `{model}`: Input = {rec['max_input_tokens']} tokens, "
                f"Output = {rec['max_output_tokens']} tokens, Kích thước đoạn = {rec['recommended_chunk_size']} ký tự."
            )
            st.rerun()

        if t4.button("💾 Lưu cấu hình", width="stretch", key="p03_btn_save_toml"):
            saved_path = save_llm_token_config_to_toml(
                provider_key=LLMGateway.provider_key(provider),
                model=model,
                base_url=base_url,
                max_input_tokens=int(st.session_state["llm_max_input_tokens"]),
                max_output_tokens=int(st.session_state["llm_max_output_tokens"]),
                chunk_size=int(st.session_state.get("extraction_chunk_size", default_chunk)),
            )
            st.success(f"Đã lưu cấu hình vào `{saved_path}`!")

    if not docs:
        st.info("Chưa có tài liệu nào trong dự án. Hãy bổ sung tài liệu ở Bước 1 trước khi bắt đầu trích xuất.")
        return

    # Tính toán lượt trích xuất trước đó theo từng tài liệu
    runs_by_doc: dict[str, list[dict]] = {}
    for r in project.get("runs", []):
        did = r.get("doc_id")
        if did:
            runs_by_doc.setdefault(did, []).append(r)

    # Khởi tạo trạng thái chọn cho từng tài liệu nếu chưa có
    for d in docs:
        key = f"p03_doc_sel_{d['id']}"
        if key not in st.session_state:
            st.session_state[key] = True

    # Danh sách tài liệu đang được đánh dấu chọn
    selected_docs = [d for d in docs if st.session_state.get(f"p03_doc_sel_{d['id']}", True)]

    # 2. KHU VỰC CHỌN TÀI LIỆU TRÍCH XUẤT
    with st.container(border=True):
        st.markdown(f"##### 📑 Danh sách Chọn Tài liệu Trích xuất ({len(selected_docs)}/{len(docs)} file được chọn)")

        # Thanh công cụ: Tìm kiếm & Thao tác chọn nhanh
        tb_filter, tb_all, tb_none, tb_unextracted = st.columns([3.5, 1.4, 1.4, 2.2])
        filter_text = tb_filter.text_input(
            "Tìm tài liệu",
            placeholder="🔍 Nhập tên file để lọc nhanh...",
            key="p03_filter_doc_text",
            label_visibility="collapsed",
        ).strip().lower()

        displayed_docs = [d for d in docs if not filter_text or filter_text in d.get("name", "").lower()]

        if tb_all.button("☑️ Chọn tất cả", key="btn_sel_all_docs", width="stretch"):
            for d in (displayed_docs if filter_text else docs):
                st.session_state[f"p03_doc_sel_{d['id']}"] = True
            st.rerun()

        if tb_none.button("⬜ Bỏ chọn hết", key="btn_clear_all_docs", width="stretch"):
            for d in (displayed_docs if filter_text else docs):
                st.session_state[f"p03_doc_sel_{d['id']}"] = False
            st.rerun()

        if tb_unextracted.button("⚪ Chọn file chưa trích xuất", key="btn_sel_unextracted_docs", width="stretch"):
            for d in docs:
                st.session_state[f"p03_doc_sel_{d['id']}"] = (d["id"] not in runs_by_doc)
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
                    k = f"p03_doc_sel_{doc['id']}"
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

    # 3. THIẾT LẬP THAM SỐ ĐOẠN & ĐIỀU KHIỂN CHẠY
    with st.container(border=True):
        st.markdown("##### ⚙️ Thiết lập Phân đoạn & Kích hoạt Trích xuất")
        c1, c2, c3, c4 = st.columns([1.5, 1.2, 1.2, 1.5])
        chunk_size = c1.number_input("Kích thước đoạn (ký tự)", 500, 16000, default_chunk, 100)
        st.session_state["extraction_chunk_size"] = int(chunk_size)
        overlap = c2.number_input("Độ chồng lấp (ký tự)", 0, 1000, default_overlap, 50)

        extract_all = c3.checkbox(
            "Trích xuất tất cả",
            value=True,
            help="Tự động chia và trích xuất toàn bộ các đoạn của các tài liệu đã chọn.",
            key="p03_chk_extract_all",
        )
        if extract_all:
            max_chunks = 9999
            c4.caption("⚡ Sẽ xử lý **100% các đoạn** của các file đã chọn")
        else:
            max_chunks = c4.number_input(
                "Số đoạn tối đa / file",
                1,
                200,
                int(CONFIG["extraction"]["max_chunks_per_document"]),
                help="Giới hạn số đoạn chạy thử nghiệm cho mỗi tài liệu.",
                key="p03_num_max_chunks",
            )

        if not selected_docs:
            st.warning("⚠️ Chưa có tài liệu nào được chọn. Vui lòng đánh dấu chọn ít nhất một file ở danh sách phía trên để bắt đầu trích xuất.")
        else:
            total_chunks = sum(
                len(facade.document_chunks(d, limit=int(chunk_size), overlap=int(overlap))[: int(max_chunks)])
                for d in selected_docs
            )
            st.info(
                f"📊 Đang chọn **{len(selected_docs)}/{len(docs)} tài liệu** $\\rightarrow$ "
                f"Tổng cộng **{total_chunks} đoạn** văn bản cần xử lý (mỗi đoạn ~{chunk_size} ký tự, chồng lấp {overlap} ký tự)."
            )

        # CẤU HÌNH ĐA LUỒNG (CONCURRENT EXTRACTION THREADS)
        st.markdown("---")
        th_col1, th_col2 = st.columns([2.2, 3.8])
        default_workers = int(st.session_state.get("extraction_workers", 3))
        workers = th_col1.slider(
            "⚡ Số luồng gọi API đồng thời (Concurrent Threads)",
            min_value=1,
            max_value=16,
            value=default_workers,
            step=1,
            key="p03_slider_workers",
            help="Số lượng request gọi LLM API gửi đi song song cùng lúc. Tăng số luồng giúp rút ngắn thời gian trích xuất gấp nhiều lần.",
        )
        st.session_state["extraction_workers"] = workers

        if workers == 1:
            th_col2.info("🐢 **Chế độ Tuần tự (1 luồng)**: Xử lý lần lượt từng đoạn. An toàn tuyệt đối, phù hợp khi mạng yếu hoặc dùng GPU local nhỏ.")
        elif workers <= 5:
            th_col2.success(f"🚀 **Chế độ Đa luồng Khuyến nghị ({workers} luồng)**: Phù hợp nhất cho DeepSeek API & OpenAI. Tốc độ tăng ~{workers}x mà không lo chạm Rate Limit.")
        elif workers <= 10:
            th_col2.warning(f"⚡ **Chế độ Tốc độ cao ({workers} luồng)**: Rất nhanh. Cần tài khoản API có hạn mức RPM/TPM cao (OpenAI Tier 2+, DeepSeek Enterprise) để tránh lỗi 429.")
        else:
            th_col2.error(f"🔥 **Chế độ Siêu tốc ({workers} luồng)**: Nguy cơ cao bị Rate Limit nếu tài khoản tiêu chuẩn. Hãy chắc chắn nhà cung cấp của bạn cho phép throughput này.")

        with st.expander("💡 Note gợi ý & Khuyến nghị thiết lập số luồng tối ưu", expanded=False):
            st.markdown(
                """
- **DeepSeek API (`deepseek-chat`)**:
  - Khuyến nghị: **3 – 5 luồng**.
  - Lý do: DeepSeek có giới hạn tiêu chuẩn khoảng 60 requests/phút (RPM). Chạy 3–5 luồng giúp trích xuất 50 đoạn văn chỉ mất ~20–30 giây thay vì 3–4 phút, vừa an toàn vừa đạt hiệu suất đỉnh.
- **OpenAI (`gpt-4o`, `gpt-4o-mini`)**:
  - Khuyến nghị: **4 – 8 luồng** (nếu tài khoản Tier 2 trở lên); **2 – 3 luồng** (nếu Tier 1).
- **Google Gemini (`gemini-1.5-flash`)**:
  - Khuyến nghị: **3 – 6 luồng**.
- **Mô hình cục bộ (Local Ollama / LM Studio)**:
  - Khuyến nghị: **1 – 2 luồng**.
  - Lý do: Chạy local tiêu tốn VRAM/RAM theo từng request song song. Để >2 luồng có thể gây nghẽn phần cứng (OOM) hoặc làm giảm tốc độ suy luận (token/s).
- 🛡️ **Đảm bảo toàn vẹn dữ liệu (Thread Safety)**:
  - Hệ thống sử dụng cơ chế khóa **Thread Lock** (`threading.RLock`). Khi nhiều luồng hoàn tất cùng lúc, các thực thể, quan hệ và đề xuất schema được xếp hàng sáp nhập tuần tự vào đồ thị, đảm bảo **100% không bị xung đột, trùng lặp hay ghi đè sai lệch dữ liệu**.
                """
            )

        # Hàng nút thao tác: Chạy thử 1 đoạn mẫu VS Chạy toàn bộ
        btn_col_test, btn_col_run = st.columns([1.8, 2.2])

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
                            facade.save_project(project)
                            st.success(
                                f"✅ Chạy thử thành công đoạn #{target_rec['chunk_number']}! "
                                f"Thực thể thêm: {out.ingest_stats.get('added_nodes', 0)}, "
                                f"Quan hệ thêm: {out.ingest_stats.get('added_edges', 0)}."
                            )
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Lỗi khi chạy thử nghiệm: {exc}")

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
                        msg = f"⚠️ ({done_idx}/{total_cnt}) Lỗi tại {doc.get('name', '')} đoạn #{rec.get('chunk_number', '?')}: {err}"
                    else:
                        stats = getattr(out, "ingest_stats", {}) if out else {}
                        msg = f"⚡ ({done_idx}/{total_cnt}) Đã xử lý {doc.get('name', '')} đoạn #{rec.get('chunk_number', '?')} [+{stats.get('added_nodes', 0)} thực thể, +{stats.get('added_edges', 0)} quan hệ]"
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

                st.session_state["p03_last_failed_tasks"] = summary.get("failed_tasks", [])

                if summary.get("failed_tasks"):
                    st.warning(f"⚠️ Đã hoàn tất với {summary['success_count']} đoạn thành công và {len(summary['failed_tasks'])} đoạn gặp lỗi.")
                else:
                    st.success(f"🎉 Hoàn tất thành công 100% ({summary['success_count']}/{len(all_tasks)} đoạn) cho {len(selected_docs)} tài liệu!")
                st.rerun()

        # Hiển thị nút khắc phục khi có các đoạn bị lỗi
        last_failed = st.session_state.get("p03_last_failed_tasks", [])
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
                        retry_status.caption(f"❌ Thất bại đoạn #{rec.get('chunk_number')}: {err}")
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
                st.session_state["p03_last_failed_tasks"] = retry_summary.get("failed_tasks", [])
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
        selected_idx = st.selectbox(
            "Chọn lượt xử lý để xem chi tiết & Step Traces",
            range(len(runs)),
            format_func=lambda i: f"#{len(runs) - i} · {runs[i].get('doc_name', '')} (Đoạn {runs[i].get('chunk_number', 0)}) — mode={runs[i].get('extraction_mode', '')}",
        )
        run = runs[selected_idx]
        render_step_traces(run)
        with st.expander("Phản hồi JSON gốc từ LLM"):
            st.code(run.get("raw_response", ""), language="json")

    # 5. ĐIỀU HƯỚNG SANG BƯỚC TIẾP THEO
    st.divider()
    with st.container(border=True):
        col_msg, col_btn = st.columns([3.5, 1.5])
        col_msg.markdown(
            "➡️ **Sẵn sàng chuẩn hóa dữ liệu?** "
            "Chuyển sang Bước 4 để duyệt các quan hệ, kiểm tra bằng chứng, và giải quyết trùng lặp thực thể."
        )
        if col_btn.button("➡️ Chuyển sang Bước 4: Rà soát & Chuẩn hóa", type="primary", width="stretch", key="p03_btn_goto_review"):
            navigate_to_step("review")
            st.rerun()
