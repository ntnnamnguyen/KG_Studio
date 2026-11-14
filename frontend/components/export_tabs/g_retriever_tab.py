"""Component Tab 1 của Trang Khai thác: Hỏi đáp Đồ thị (G-Retriever PCST • HippoRAG • Naive)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from frontend.state.session import sync_keyed_int, sync_keyed_value
from shared.secrets_manager import get_api_key


def build_subgraph_dot(result: dict[str, Any]) -> str:
    """Sinh mã DOT Graphviz phân màu rõ rệt cho Hạt giống (Seed), Cầu nối Steiner (Bridge) và Đỉnh mở rộng (Leaf)."""
    nodes = result.get("subgraph_nodes") or []
    edges = result.get("subgraph_edges") or []
    seed_set = set(result.get("seed_node_ids") or [])
    bridge_set = set(result.get("steiner_bridge_ids") or [])
    leaf_set = set(result.get("expanded_leaf_ids") or [])
    node_prizes = result.get("node_prizes") or {}
    edge_prizes = result.get("edge_prizes") or {}

    nodes_by_id: dict[str, dict[str, Any]] = {str(n["id"]): n for n in nodes}
    lines = [
        "digraph GRetrieverSubgraph {",
        '  rankdir="LR";',
        '  graph [pad="0.25", nodesep="0.35", ranksep="0.65", fontname="sans-serif"];',
        '  node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=11, margin="0.14,0.08"];',
        '  edge [fontname="sans-serif", fontsize=10];',
    ]

    for n in nodes:
        nid = str(n["id"])
        name = str(n.get("name", nid)).replace('"', '\\"')
        kind = str(n.get("kind") or n.get("type") or "Thực thể").replace('"', '\\"')
        prize = node_prizes.get(nid, 0.0)
        if nid in seed_set:
            fill = "#fef3c7"
            border = "#d97706"
            role_tag = "★ Seed"
            penwidth = "2.2"
        elif nid in bridge_set:
            fill = "#dcfce7"
            border = "#16a34a"
            role_tag = "◆ Steiner Bridge"
            penwidth = "2.0"
        elif nid in leaf_set:
            fill = "#f3e8ff"
            border = "#9333ea"
            role_tag = "✦ 1-Hop Attr"
            penwidth = "1.3"
        else:
            fill = "#eef6ff"
            border = "#3b82f6"
            role_tag = "● Node"
            penwidth = "1.4"

        prize_str = f" | p={prize:.2f}" if prize > 0 else ""
        label = f"{name}\\n({kind} • {role_tag}{prize_str})"
        lines.append(
            f'  "{nid}" [label="{label}", fillcolor="{fill}", color="{border}", penwidth={penwidth}];'
        )

    for idx, e in enumerate(edges, start=1):
        eid = str(e.get("id", f"e_{idx}"))
        u = str(e.get("source", ""))
        v = str(e.get("target", ""))
        if u not in nodes_by_id or v not in nodes_by_id:
            continue
        rel = str(e.get("relation", "")).replace('"', '\\"')
        eprize = edge_prizes.get(eid, 0.0)
        is_core = (u in seed_set or u in bridge_set) and (v in seed_set or v in bridge_set)
        edge_color = "#dc2626" if is_core and eprize >= 0.4 else ("#2563eb" if eprize > 0 else "#64748b")
        edge_width = "2.0" if is_core else "1.2"
        label = f"[E{idx}] {rel}"
        lines.append(
            f'  "{u}" -> "{v}" [label="{label}", color="{edge_color}", fontcolor="{edge_color}", penwidth={edge_width}];'
        )

    lines.append("}")
    return "\n".join(lines)


def _read_llm_runtime_params() -> tuple[str, str, str, str, int, int]:
    """Đọc tham số runtime LLM hiện hành từ session state hoặc key lưu trữ."""
    provider = str(st.session_state.get("llm_provider", "DeepSeek"))
    api_key = str(st.session_state.get("llm_api_key") or get_api_key(provider) or "")
    model = str(st.session_state.get("llm_model", "deepseek-chat"))
    base_url = str(st.session_state.get("llm_base_url", ""))
    max_in = int(st.session_state.get("llm_max_input_tokens", 16000))
    max_out = int(st.session_state.get("llm_max_output_tokens", 4096))
    return provider, api_key, model, base_url, max_in, max_out


def _render_sample_questions_and_query_input(
    facade: Any, active_graph_project: dict, proj_id: str
) -> str:
    """Hiển thị bộ chọn câu hỏi mẫu tự sinh và ô nhập câu hỏi tiếng Việt."""
    sample_cache_key = f"_gret_sample_questions_{proj_id}_{len(active_graph_project.get('edges', []))}"
    if sample_cache_key not in st.session_state:
        st.session_state[sample_cache_key] = facade.generate_qa_benchmark(active_graph_project, num_questions=12)
    sample_questions: list[dict[str, Any]] = st.session_state[sample_cache_key]

    q_state_key = f"_gret_query_input_{proj_id}"
    if q_state_key not in st.session_state:
        default_q = (
            sample_questions[0]["question"]
            if sample_questions
            else "Những sự kiện, địa danh hoặc thông tin lịch sử nào liên quan đến Hà Nội?"
        )
        st.session_state[q_state_key] = default_q
        if sample_questions:
            st.session_state[f"_gret_selected_gold_{proj_id}"] = sample_questions[0]

    if sample_questions:
        col_sel, col_apply = st.columns([4, 1], vertical_alignment="bottom")
        option_labels = [
            f"[{idx + 1} • {q.get('category', 'QA')}] {q['question']}"
            for idx, q in enumerate(sample_questions)
        ]
        chosen_idx = col_sel.selectbox(
            "💡 Chọn nhanh câu hỏi mẫu đa bước (tự động trích từ đồ thị hiện tại để Demo 1-Click):",
            range(len(option_labels)),
            format_func=lambda i: option_labels[i],
            key=f"_gret_sample_sel_{proj_id}",
        )
        if col_apply.button("📥 Nạp câu hỏi mẫu", width="stretch", key=f"_gret_btn_load_sample_{proj_id}"):
            st.session_state[q_state_key] = sample_questions[chosen_idx]["question"]
            st.session_state[f"_gret_selected_gold_{proj_id}"] = sample_questions[chosen_idx]
            st.rerun()

    return st.text_input(
        "❓ Nhập câu hỏi tiếng Việt cần truy vấn trên Đồ thị Tri thức:",
        key=q_state_key,
        placeholder="Ví dụ: Thực thể có quan hệ 'tọa lạc tại' với '...' có quan hệ '...' với thực thể nào?",
    )


def _render_retrieval_params_expander(proj_id: str) -> tuple[str, int, float, bool]:
    """Hiển thị expander tham số thuật toán và chế độ đối sánh phương pháp."""
    method_options = {
        "pcst": "🏆 1. G-Retriever (Hub-Penalized PCST + 1-Hop Expansion — Khuyên dùng)",
        "ppr": "⚡ 2. HippoRAG (Relation-Aware Personalized PageRank)",
        "naive_topk": "📏 3. Baseline (Naive Top-K Isolated Triples)",
        "compare_all": "⚖️ 4. Đối sánh Song song cả 3 Phương pháp trên cùng câu hỏi (Side-by-Side)",
    }
    adv_expanded = st.session_state.get(f"_gret_method_{proj_id}") == "compare_all"
    with st.expander("🔬 Tham số thuật toán & Chế độ đối sánh (Nghiên cứu)", expanded=adv_expanded):
        cfg_c1, cfg_c2, cfg_c3, cfg_c4 = st.columns([2.3, 1.05, 1.05, 1.1])
        selected_method = cfg_c1.selectbox(
            "Chế độ / Phương pháp Truy xuất Đồ thị con",
            list(method_options.keys()),
            format_func=lambda k: method_options[k],
            key=f"_gret_method_{proj_id}",
        )
        max_edges_key = f"_gret_max_edges_{proj_id}"
        hub_alpha_key = f"_gret_hub_alpha_{proj_id}"
        expand_leaf_key = f"_gret_expand_leaf_{proj_id}"
        sync_keyed_int(max_edges_key, 15, (proj_id, "max_edges"), min_value=5, max_value=40)
        sync_keyed_value(hub_alpha_key, 0.22, (proj_id, "hub_alpha"))
        sync_keyed_value(expand_leaf_key, True, (proj_id, "expand_leaf"))

        max_edges = int(
            cfg_c2.slider(
                "Số cạnh tối đa (Subgraph Budget)",
                min_value=5,
                max_value=40,
                step=1,
                key=max_edges_key,
            )
        )
        hub_alpha = float(
            cfg_c3.slider(
                "Hệ số phạt đỉnh Hub (α)",
                min_value=0.0,
                max_value=0.60,
                step=0.02,
                key=hub_alpha_key,
                help="Phạt chi phí đường đi qua các siêu đỉnh bậc cao (như 'Hà Nội', 'Việt Nam') để tránh lối tắt giả.",
            )
        )
        expand_leaf = bool(
            cfg_c4.checkbox(
                "Mở rộng 1-Hop Thuộc tính",
                key=expand_leaf_key,
                help="Tự động đính kèm các cạnh thuộc tính/định danh xung quanh hạt giống sau khi giải cây Steiner.",
            )
        )
    return selected_method, max_edges, hub_alpha, expand_leaf


def _render_compare_all_methods_panel(
    facade: Any,
    active_graph_project: dict,
    query_text: str,
    max_edges: int,
    hub_alpha: float,
    expand_leaf: bool,
    gold_info: dict[str, Any] | None,
    run_llm_answer: bool,
) -> None:
    """Hiển thị chế độ đối sánh trực quan 3 phương pháp truy xuất song song."""
    if not query_text.strip() or not active_graph_project.get("edges"):
        st.info("Hãy nhập câu hỏi để đối sánh 3 phương pháp.")
        return

    st.divider()
    st.markdown("##### ⚖️ Đối sánh Trực quan 3 Phương pháp Truy xuất trên cùng câu hỏi")
    three_methods = [
        ("naive_topk", "📏 1. Baseline (Naive Top-K)"),
        ("ppr", "⚡ 2. HippoRAG (PageRank - PPR)"),
        ("pcst", "🏆 3. G-Retriever (PCST + 1-Hop)"),
    ]
    cols = st.columns(3)
    for col, (m_code, m_title) in zip(cols, three_methods):
        m_res = facade.retrieve_subgraph(
            active_graph_project,
            query_text.strip(),
            method=m_code,
            approved_only=True,
            max_edges=max_edges,
            hub_penalty_alpha=hub_alpha,
            expand_leaf_attributes=expand_leaf,
        )
        m_nodes = m_res.get("subgraph_nodes") or []
        m_edges = m_res.get("subgraph_edges") or []
        m_paths = m_res.get("reasoning_paths") or []
        with col:
            with st.container(border=True):
                st.markdown(f"**{m_title}**")
                st.caption(
                    f"⏱️ `{m_res.get('elapsed_ms', 0.0):.2f} ms` • "
                    f"Đỉnh: **{len(m_nodes)}** • Cạnh: **{len(m_edges)}** • "
                    f"Liên thông LCC: **{m_res.get('largest_component_ratio', 0.0) * 100:.1f}%**"
                )
                if gold_info and gold_info.get("question") == query_text.strip():
                    retrieved_ids = {str(n["id"]) for n in m_nodes}
                    target_id = str(gold_info.get("target_node_id", ""))
                    bridge_id = str(gold_info.get("bridge_node_id", ""))
                    hit_target = target_id in retrieved_ids
                    hit_bridge = (not bridge_id) or (bridge_id in retrieved_ids)
                    if hit_target and hit_bridge:
                        st.success(f"✅ Thu hồi đúng đích: `{gold_info.get('expected_answer_name')}`")
                    else:
                        st.error(f"❌ Bỏ sót đỉnh đích: `{gold_info.get('expected_answer_name')}`")

                if m_edges:
                    st.graphviz_chart(build_subgraph_dot(m_res))
                if m_paths:
                    st.markdown("**Chuỗi suy luận:**")
                    for p_s in m_paths[:3]:
                        st.markdown(f"- `{p_s}`")
                with st.expander("📌 Bằng chứng trích xuất", expanded=False):
                    st.markdown(m_res.get("extractive_summary", ""))

    if run_llm_answer:
        provider, api_key, model, base_url, max_in, max_out = _read_llm_runtime_params()
        st.markdown("##### 🤖 Đối sánh Câu trả lời Sinh từ LLM giữa 3 Phương pháp")
        llm_cols = st.columns(3)
        for l_col, (m_code, m_title) in zip(llm_cols, three_methods):
            with l_col:
                with st.spinner(f"Đang gọi LLM cho {m_title}..."):
                    qa_m = facade.answer_question_with_graph(
                        active_graph_project,
                        query_text.strip(),
                        method=m_code,
                        approved_only=True,
                        max_edges=max_edges,
                        provider=provider,
                        api_key=api_key,
                        model=model,
                        base_url=base_url,
                        max_input_tokens=max_in,
                        max_output_tokens=max_out,
                    )
                with st.container(border=True):
                    st.markdown(f"**🤖 {m_title}**")
                    st.markdown(qa_m.get("answer", ""))


def _render_single_method_qa_result(saved_qa: dict[str, Any], proj_id: str) -> None:
    """Hiển thị kết quả truy xuất, trực quan hóa đồ thị con, câu trả lời và node prizes."""
    ret: dict[str, Any] = saved_qa["retrieval"]
    sub_nodes = ret.get("subgraph_nodes") or []
    sub_edges = ret.get("subgraph_edges") or []
    seed_ids = ret.get("seed_node_ids") or []
    bridge_ids = ret.get("steiner_bridge_ids") or []
    leaf_ids = ret.get("expanded_leaf_ids") or []

    st.divider()
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(
        "Đỉnh trong Subgraph",
        len(sub_nodes),
        delta=f"{len(seed_ids)} Seed • {len(bridge_ids)} Bridge • {len(leaf_ids)} Leaf",
    )
    k2.metric("Cạnh được chọn", len(sub_edges), delta=f"Phương pháp: {ret.get('method', '').upper()}")
    k3.metric(
        "Độ liên thông LCC",
        f"{ret.get('largest_component_ratio', 0.0) * 100:.1f}%",
        delta=f"{ret.get('connected_components', 0)} thành phần",
    )
    k4.metric("Thời gian truy xuất", f"{ret.get('elapsed_ms', 0.0):.2f} ms")
    k5.metric("Ngữ cảnh Đồ thị", f"~{ret.get('estimated_tokens', 0)} tokens")

    col_viz, col_ans = st.columns([1.25, 1.0])
    with col_viz:
        with st.container(border=True):
            st.markdown("##### 🕸️ Đồ thị Con Tối ưu (Steiner Tree Subgraph)")
            st.caption(
                "🟨 **Vàng (`★ Seed`)**: Đỉnh hạt giống khớp câu hỏi | "
                "🟩 **Xanh lá (`◆ Steiner Bridge`)**: Đỉnh trung gian cầu nối đa bước | "
                "🟪 **Tím (`✦ 1-Hop Attr`)**: Đỉnh thuộc tính mở rộng | "
                "🟥 **Cạnh đỏ đậm**: Mạch suy luận chính"
            )
            if sub_edges:
                st.graphviz_chart(build_subgraph_dot(ret))
            else:
                st.info("Không tìm thấy cạnh phù hợp cho truy vấn này.")

            reasoning_paths = ret.get("reasoning_paths") or []
            if reasoning_paths:
                st.markdown("**🔗 Chuỗi suy luận đa bước phát hiện tự động trên đồ thị:**")
                for p_str in reasoning_paths[:6]:
                    st.markdown(f"- `{p_str}`")

    with col_ans:
        with st.container(border=True):
            if saved_qa.get("used_llm"):
                st.markdown("##### 🤖 Câu trả lời Tổng hợp từ LLM (Có kiểm chứng Bằng chứng `[E#]`)")
            else:
                st.markdown("##### 📌 Bản tổng hợp Bằng chứng Trực tiếp từ Đồ thị Con (Extractive Grounding)")
                if saved_qa.get("llm_error"):
                    st.warning(f"⚠️ Lưu ý kết nối LLM: {saved_qa['llm_error']}")
                else:
                    st.caption("💡 Bấm nút **'🤖 2. Truy xuất & Sinh Câu trả lời bằng LLM'** phía trên để mô hình ngôn ngữ diễn giải chi tiết.")

            st.markdown(saved_qa.get("answer") or ret.get("extractive_summary", ""))

            gold_info = st.session_state.get(f"_gret_selected_gold_{proj_id}")
            if gold_info and gold_info.get("question") == ret.get("query"):
                retrieved_node_ids = {str(n["id"]) for n in sub_nodes}
                target_id = str(gold_info.get("target_node_id", ""))
                hit = target_id in retrieved_node_ids
                badge = "✅ ĐÃ THU HỒI ĐÚNG ĐỈNH ĐÍCH" if hit else "❌ CHƯA THU HỒI ĐỈNH ĐÍCH"
                st.info(
                    f"🎯 **Kiểm chứng Đáp án Chuẩn (Ground-Truth):** `{gold_info.get('expected_answer_name')}` "
                    f"( Trung gian: `{gold_info.get('bridge_node_name') or 'Trực tiếp 1-Hop'}` ) — **{badge}**"
                )

    with st.expander("📄 Xem Ngữ cảnh Đồ thị Văn bản hóa (Textualized Graph Prompt chuẩn G-Retriever) & Điểm Prize", expanded=False):
        p_col1, p_col2 = st.columns([1.4, 1.0])
        with p_col1:
            st.markdown("**Ngữ cảnh Đồ thị Văn bản hóa gửi vào LLM (`Nodes` + `Edges` kèm bằng chứng):**")
            st.code(ret.get("textualized_prompt", ""), language="markdown")
        with p_col2:
            st.markdown("**Bảng Điểm Giải thưởng Đỉnh (`node_prizes`) & Cạnh (`edge_prizes`):**")
            nodes_lookup = {str(n["id"]): str(n.get("name", n["id"])) for n in sub_nodes}
            node_prize_rows = [
                {
                    "ID Đỉnh": nid,
                    "Tên Thực thể": nodes_lookup.get(nid, nid),
                    "Vai trò": "★ Seed" if nid in seed_ids else ("◆ Bridge" if nid in bridge_ids else "✦ Leaf"),
                    "Điểm Prize": score,
                }
                for nid, score in (ret.get("node_prizes") or {}).items()
            ]
            if node_prize_rows:
                st.dataframe(node_prize_rows, width="stretch", hide_index=True)


def render_g_retriever_qa_tab(facade: Any, active_graph_project: dict, proj_id: str) -> None:
    """Tab 1: Hỏi đáp Đa bước & Trực quan hóa Đồ thị con bằng cả 3 phương pháp."""
    st.markdown("#### 🧠 Hỏi đáp Đa bước & Trực quan hóa Đồ thị Con (G-Retriever PCST • HippoRAG PPR • Naive Top-K)")
    st.caption(
        "Hỗ trợ hỏi đáp trực tiếp bằng **cả 3 phương pháp** (**G-Retriever PCST**, **HippoRAG PPR**, **Baseline Naive Top-K**) "
        "hoặc bật chế độ **⚖️ Đối sánh Trực quan 3 Phương pháp Song song (Side-by-Side)** trên cùng một câu hỏi."
    )

    query_text = _render_sample_questions_and_query_input(facade, active_graph_project, proj_id)
    selected_method, max_edges, hub_alpha, expand_leaf = _render_retrieval_params_expander(proj_id)

    btn_c1, btn_c2 = st.columns(2)
    run_retrieve_only = btn_c1.button(
        "🔍 1. Truy xuất Đồ thị Con & Chuỗi Suy luận (Tức thì ~25ms)",
        width="stretch",
        key=f"_gret_btn_retrieve_{proj_id}",
    )
    run_llm_answer = btn_c2.button(
        "🤖 2. Truy xuất & Sinh Câu trả lời bằng LLM (Trích dẫn [E#])",
        type="primary",
        width="stretch",
        key=f"_gret_btn_llm_qa_{proj_id}",
    )

    gold_info = st.session_state.get(f"_gret_selected_gold_{proj_id}")

    if selected_method == "compare_all":
        _render_compare_all_methods_panel(
            facade,
            active_graph_project,
            query_text,
            max_edges,
            hub_alpha,
            expand_leaf,
            gold_info,
            run_llm_answer,
        )
        return

    result_state_key = f"_gret_last_result_{proj_id}"
    cached_qa = st.session_state.get(result_state_key)
    cached_sig = cached_qa.get("_sig") if isinstance(cached_qa, dict) else None
    current_sig = (query_text.strip(), selected_method, max_edges, round(hub_alpha, 3), expand_leaf)

    if (run_retrieve_only or cached_sig != current_sig) and query_text.strip() and active_graph_project.get("edges"):
        res = facade.retrieve_subgraph(
            active_graph_project,
            query_text.strip(),
            method=selected_method,
            approved_only=True,
            max_edges=max_edges,
            hub_penalty_alpha=hub_alpha,
            expand_leaf_attributes=expand_leaf,
        )
        st.session_state[result_state_key] = {
            "_sig": current_sig,
            "retrieval": res,
            "answer": res.get("extractive_summary", ""),
            "used_llm": False,
            "llm_error": "",
        }

    if run_llm_answer and query_text.strip():
        provider, api_key, model, base_url, max_in, max_out = _read_llm_runtime_params()
        with st.spinner(f"Đang truy xuất ({selected_method.upper()}) và tổng hợp câu trả lời qua {provider} ({model})..."):
            qa_out = facade.answer_question_with_graph(
                active_graph_project,
                query_text.strip(),
                method=selected_method,
                approved_only=True,
                max_edges=max_edges,
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
                max_input_tokens=max_in,
                max_output_tokens=max_out,
            )
            qa_out["_sig"] = current_sig
            st.session_state[result_state_key] = qa_out

    saved_qa = st.session_state.get(result_state_key)
    if saved_qa:
        _render_single_method_qa_result(saved_qa, proj_id)
