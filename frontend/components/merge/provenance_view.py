"""Thành phần UI đối chiếu Ngữ cảnh Văn bản Gốc & Đoạn trích (Provenance & Chunk Context).

Cung cấp khả năng truy vết nguồn gốc (Data Lineage / Provenance) phục vụ kiểm duyệt
và gộp thực thể / quan hệ:
- Hiển thị tên tài liệu gốc (doc_name), mã tài liệu (doc_id), số đoạn (chunk_number), trang (page).
- Trích xuất đoạn văn bản gốc (chunk text) từ tài liệu nguồn mà không nhân bản dữ liệu.
- Tô sáng (highlight) an toàn tên thực thể hoặc câu trích dẫn bằng chứng trong văn bản gốc.
"""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from backend.domain.curation.service import find_document, find_edge, find_node
from backend.domain.documents.processor import document_chunks
from shared.text_utils import normal


def highlight_text_html(
    full_text: str,
    targets: list[str],
    *,
    background: str = "#fde047",
    color: str = "#1e293b",
    max_chars: int = 1500,
) -> str:
    """Tạo chuỗi HTML an toàn, tự động tô sáng các từ khóa/câu trích dẫn trong đoạn văn bản.

    - Thoát mã độc HTML bằng html.escape() để ngăn chặn XSS.
    - Cắt tỉa độ dài thông minh nếu chunk quá dài, ưu tiên vùng xuất hiện từ khóa.
    """
    clean_text = str(full_text or "").strip()
    if not clean_text:
        return "<div style='color:#94a3b8;font-style:italic;'>Không có nội dung văn bản.</div>"

    clean_targets = [str(t).strip() for t in targets if str(t).strip()]
    if not clean_targets:
        escaped_preview = html.escape(clean_text[:max_chars]) + ("..." if len(clean_text) > max_chars else "")
        return (
            "<div style='padding:10px 14px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;"
            "line-height:1.65;font-size:0.92rem;white-space:pre-wrap;color:#334155;'>"
            f"{escaped_preview}"
            "</div>"
        )

    # Tìm vị trí xuất hiện đầu tiên của bất kỳ target nào để căn khung nhìn (view window)
    first_pos = -1
    best_target = clean_targets[0]
    for tgt in clean_targets:
        pos = clean_text.lower().find(tgt.lower())
        if pos != -1 and (first_pos == -1 or pos < first_pos):
            first_pos = pos
            best_target = tgt

    # Nếu văn bản dài hơn max_chars, cắt vùng bao quanh target
    if len(clean_text) > max_chars and first_pos != -1:
        start_idx = max(0, first_pos - int(max_chars * 0.3))
        end_idx = min(len(clean_text), start_idx + max_chars)
        snippet = clean_text[start_idx:end_idx]
        prefix = "..." if start_idx > 0 else ""
        suffix = "..." if end_idx < len(clean_text) else ""
        display_text = prefix + snippet + suffix
    else:
        display_text = clean_text[:max_chars] + ("..." if len(clean_text) > max_chars else "")

    # Thoát toàn bộ HTML trước khi chèn thẻ <mark>
    escaped_display = html.escape(display_text)

    # Tô sáng từng target theo thứ tự độ dài giảm dần (tránh match lồng nhau)
    sorted_targets = sorted(clean_targets, key=len, reverse=True)
    for tgt in sorted_targets:
        escaped_tgt = html.escape(tgt)
        if not escaped_tgt:
            continue
        # Thay thế case-insensitive an toàn
        import re
        pattern = re.compile(re.escape(escaped_tgt), re.IGNORECASE)
        escaped_display = pattern.sub(
            f"<mark style='background:{background};color:{color};padding:2px 5px;border-radius:3px;font-weight:600;'>\\g<0></mark>",
            escaped_display,
        )

    return (
        "<div style='padding:12px 14px;border:1px solid #cbd5e1;border-radius:6px;background:#f8fafc;"
        "line-height:1.65;font-size:0.92rem;white-space:pre-wrap;color:#1e293b;max-height:360px;overflow-y:auto;'>"
        f"{escaped_display}"
        "</div>"
    )


def get_chunk_info(
    project: dict,
    doc_id: str,
    chunk_number: int | None = None,
) -> dict[str, Any] | None:
    """Lấy thông tin và văn bản của một đoạn (chunk) từ tài liệu nguồn mà không nhân bản dữ liệu.

    Trả về dictionary gồm: doc_id, doc_name, chunk_number, text, page_from, page_to, start_char, end_char.
    """
    doc = find_document(project, doc_id)
    if not doc:
        return None

    doc_name = str(doc.get("name") or doc_id)
    doc_text = str(doc.get("text") or "")
    if not doc_text:
        return {
            "doc_id": doc_id,
            "doc_name": doc_name,
            "chunk_number": chunk_number or 1,
            "text": "",
            "page_from": None,
            "page_to": None,
            "start_char": 0,
            "end_char": 0,
        }

    chunks = document_chunks(doc)
    if not chunks:
        return {
            "doc_id": doc_id,
            "doc_name": doc_name,
            "chunk_number": chunk_number or 1,
            "text": doc_text[:1500],
            "page_from": None,
            "page_to": None,
            "start_char": 0,
            "end_char": min(len(doc_text), 1500),
        }

    if chunk_number is not None and chunk_number > 0:
        match_chunk = next((c for c in chunks if c.get("chunk_number") == chunk_number), None)
        if match_chunk:
            return {
                "doc_id": doc_id,
                "doc_name": doc_name,
                "chunk_number": chunk_number,
                "text": match_chunk.get("text", ""),
                "page_from": match_chunk.get("page_from"),
                "page_to": match_chunk.get("page_to"),
                "start_char": match_chunk.get("start_char", 0),
                "end_char": match_chunk.get("end_char", 0),
            }

    # Fallback chunk đầu tiên nếu không khớp số đoạn
    first_chk = chunks[0]
    return {
        "doc_id": doc_id,
        "doc_name": doc_name,
        "chunk_number": first_chk.get("chunk_number", 1),
        "text": first_chk.get("text", ""),
        "page_from": first_chk.get("page_from"),
        "page_to": first_chk.get("page_to"),
        "start_char": first_chk.get("start_char", 0),
        "end_char": first_chk.get("end_char", 0),
    }


def render_entity_provenance_panel(
    project: dict,
    member_node_ids: list[str],
    *,
    max_observations_per_node: int = 4,
    max_edges_per_node: int = 4,
) -> None:
    """Hiển thị Khung đối chiếu Ngữ cảnh Văn bản Gốc (Provenance Context) cho danh sách thực thể cần so sánh / gộp."""
    if not member_node_ids:
        st.info("Chưa có thực thể nào được chọn để đối chiếu ngữ cảnh nguồn.")
        return

    nodes_by_id = {str(n["id"]): n for n in project.get("nodes", [])}
    docs_by_id = {str(d["id"]): d for d in project.get("documents", [])}
    edges = project.get("edges", [])

    st.markdown("##### 🔍 Đối chiếu Ngữ cảnh Văn bản & Đoạn trích Gốc (Data Provenance)")
    st.caption(
        "Truy vết nguồn gốc thực địa của từng thực thể từ tệp gốc và số đoạn trích xuất. "
        "Giúp người duyệt kiểm chứng xem hai thực thể có thực sự là cùng một đối tượng hay chỉ trùng tên ngẫu nhiên trước khi gộp."
    )

    # Hiển thị từng thực thể theo dạng Tabs nếu có từ 2 thực thể trở lên
    node_labels = [
        f"{nodes_by_id.get(nid, {}).get('name', nid)} [{nodes_by_id.get(nid, {}).get('kind', '?')}]"
        for nid in member_node_ids
    ]
    tabs = st.tabs(node_labels)

    for idx, nid in enumerate(member_node_ids):
        node = nodes_by_id.get(nid)
        with tabs[idx]:
            if not node:
                st.warning(f"Không tìm thấy thực thể ID `{nid}` trong dự án.")
                continue

            node_name = str(node.get("name", ""))
            node_kind = str(node.get("kind", ""))
            aliases = [str(a) for a in node.get("aliases", []) if a]
            all_search_terms = [node_name] + aliases

            # Header thông tin thực thể
            st.markdown(
                f"- **Tên thực thể:** `{node_name}` &nbsp;|&nbsp; "
                f"**Loại:** `{node_kind}` &nbsp;|&nbsp; "
                f"**Bí danh:** {', '.join(f'`{a}`' for a in aliases) if aliases else '*Không có*'} &nbsp;|&nbsp; "
                f"**ID:** `{nid}`"
            )
            if node.get("description"):
                st.markdown(f"> *Mô tả tổng hợp:* {node['description']}")

            # 1. Các đoạn quan sát EDC (EDC Observations)
            obs_list = node.get("edc_observations") or []
            col_left, col_right = st.columns([1.2, 1.0])

            with col_left:
                st.markdown(f"###### 📄 Đoạn trích xuất gốc ({len(obs_list)} lần ghi nhận)")
                if obs_list:
                    for o_idx, obs in enumerate(obs_list[:max_observations_per_node], 1):
                        doc_id = str(obs.get("doc_id", ""))
                        chunk_num = obs.get("chunk_number")
                        doc_obj = docs_by_id.get(doc_id)
                        doc_name = doc_obj.get("name") if doc_obj else (doc_id or "Không rõ")

                        chunk_info = get_chunk_info(project, doc_id, chunk_num)
                        page_str = ""
                        if chunk_info and chunk_info.get("page_from") is not None:
                            page_str = f" · Trang {chunk_info['page_from']}"

                        with st.container(border=True):
                            st.markdown(
                                f"**Lần #{o_idx}:** Tệp `{doc_name}` · Đoạn **{chunk_num or 1}**{page_str}"
                            )
                            if obs.get("description"):
                                st.caption(f"📝 *Mô tả khi trích xuất:* {obs['description']}")

                            if chunk_info and chunk_info.get("text"):
                                highlighted = highlight_text_html(
                                    chunk_info["text"],
                                    all_search_terms,
                                    background="#fde047",
                                )
                                st.markdown(highlighted, unsafe_allow_html=True)
                            else:
                                st.info("Không tải được nội dung đoạn văn bản gốc.")
                    if len(obs_list) > max_observations_per_node:
                        st.caption(f"*Và {len(obs_list) - max_observations_per_node} đoạn quan sát khác...*")
                else:
                    # Nếu không có EDC observations (ví dụ trích xuất kín), tìm tài liệu từ node.documents
                    doc_ids = node.get("documents") or []
                    if doc_ids:
                        for d_idx, d_id in enumerate(doc_ids[:max_observations_per_node], 1):
                            doc_obj = docs_by_id.get(d_id)
                            doc_name = doc_obj.get("name") if doc_obj else d_id
                            chunk_info = get_chunk_info(project, d_id, 1)
                            with st.container(border=True):
                                st.markdown(f"**Tài liệu #{d_idx}:** `{doc_name}`")
                                if chunk_info and chunk_info.get("text"):
                                    highlighted = highlight_text_html(
                                        chunk_info["text"],
                                        all_search_terms,
                                        background="#fde047",
                                    )
                                    st.markdown(highlighted, unsafe_allow_html=True)
                    else:
                        st.info("Thực thể chưa có liên kết tài liệu nguồn trực tiếp.")

            # 2. Các quan hệ (cạnh) liên quan & Bằng chứng ngữ cảnh
            with col_right:
                related_edges = [
                    e for e in edges
                    if str(e.get("source")) == nid or str(e.get("target")) == nid
                ]
                st.markdown(f"###### 🔗 Quan hệ & Bằng chứng thực địa ({len(related_edges)} cạnh)")
                if related_edges:
                    for e_idx, edge in enumerate(related_edges[:max_edges_per_node], 1):
                        is_src = str(edge.get("source")) == nid
                        other_id = str(edge.get("target") if is_src else edge.get("source"))
                        other_node = nodes_by_id.get(other_id, {})
                        other_name = other_node.get("name", other_id)
                        rel_name = edge.get("relation", "")
                        evidence = str(edge.get("evidence") or "").strip()
                        e_doc = edge.get("doc_name") or docs_by_id.get(str(edge.get("doc_id", "")), {}).get("name", "")
                        e_chunk = edge.get("chunk_number")
                        e_page = edge.get("page")

                        arrow = f"`{node_name}` ──[{rel_name}]──► `{other_name}`" if is_src else f"`{other_name}` ──[{rel_name}]──► `{node_name}`"

                        with st.container(border=True):
                            st.markdown(f"**Cạnh #{e_idx}:** {arrow}")
                            meta_bits = []
                            if e_doc:
                                meta_bits.append(f"Tệp: `{e_doc}`")
                            if e_chunk is not None:
                                meta_bits.append(f"Đoạn {e_chunk}")
                            if e_page is not None:
                                meta_bits.append(f"Trang {e_page}")
                            if meta_bits:
                                st.caption(" · ".join(meta_bits))

                            if evidence:
                                st.markdown(
                                    f"<div style='font-size:0.88rem;padding:6px 10px;background:#fffbeb;"
                                    f"border-left:3px solid #f59e0b;border-radius:4px;color:#92400e;'>"
                                    f"💬 <em>&ldquo;{html.escape(evidence)}&rdquo;</em>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.caption("*Không có câu trích dẫn bằng chứng riêng.*")
                    if len(related_edges) > max_edges_per_node:
                        st.caption(f"*Và {len(related_edges) - max_edges_per_node} quan hệ khác...*")
                else:
                    st.info("Thực thể chưa có cạnh kết nối nào trong đồ thị.")


def render_relation_provenance_panel(
    project: dict,
    relation_names: list[str],
    *,
    max_edges_per_relation: int = 5,
) -> None:
    """Hiển thị Khung đối chiếu Ngữ cảnh Văn bản Gốc (Provenance Context) cho các Quan hệ cần so sánh / gộp."""
    clean_rels = [str(r).strip() for r in relation_names if str(r).strip()]
    if not clean_rels:
        st.info("Chưa có quan hệ nào được chọn để đối chiếu ngữ cảnh.")
        return

    nodes_by_id = {str(n["id"]): n for n in project.get("nodes", [])}
    docs_by_id = {str(d["id"]): d for d in project.get("documents", [])}
    all_edges = project.get("edges", [])

    st.markdown("##### 🔍 Đối chiếu Ngữ cảnh Văn bản của Quan hệ (Relation Provenance)")
    st.caption(
        "Xem trực tiếp các câu trích dẫn bằng chứng và đoạn văn bản gốc chứa các quan hệ đang được xem xét gộp. "
        "Giúp phân biệt chính xác quan hệ đồng nghĩa thực sự với quan hệ có ngữ nghĩa khác biệt."
    )

    r_tabs = st.tabs([f"Quan hệ: `{r}`" for r in clean_rels])
    for idx, rel_name in enumerate(clean_rels):
        norm_r = normal(rel_name)
        matching_edges = [
            e for e in all_edges
            if normal(str(e.get("relation", ""))) == norm_r
        ]

        with r_tabs[idx]:
            st.markdown(
                f"- **Quan hệ đang xem:** `{rel_name}` &nbsp;|&nbsp; "
                f"**Tổng số cạnh trong đồ thị:** `{len(matching_edges)}` cạnh"
            )

            if not matching_edges:
                st.info(f"Không tìm thấy cạnh nào trong đồ thị đang sử dụng quan hệ `{rel_name}`.")
                continue

            for e_idx, edge in enumerate(matching_edges[:max_edges_per_relation], 1):
                src_node = nodes_by_id.get(str(edge.get("source", "")), {})
                tgt_node = nodes_by_id.get(str(edge.get("target", "")), {})
                src_name = src_node.get("name", edge.get("source", "?"))
                tgt_name = tgt_node.get("name", edge.get("target", "?"))
                doc_id = str(edge.get("doc_id", ""))
                doc_obj = docs_by_id.get(doc_id)
                doc_name = edge.get("doc_name") or (doc_obj.get("name") if doc_obj else doc_id or "Không rõ")
                chunk_num = edge.get("chunk_number")
                page = edge.get("page")
                evidence = str(edge.get("evidence") or "").strip()

                with st.container(border=True):
                    c_title, c_meta = st.columns([2.0, 1.5])
                    with c_title:
                        st.markdown(f"**Cạnh #{e_idx}:** `{src_name}` ──[{rel_name}]──► `{tgt_name}`")
                    with c_meta:
                        meta_parts = [f"Tệp: `{doc_name}`"]
                        if chunk_num is not None:
                            meta_parts.append(f"Đoạn {chunk_num}")
                        if page is not None:
                            meta_parts.append(f"Trang {page}")
                        st.caption(" · ".join(meta_parts))

                    chunk_info = get_chunk_info(project, doc_id, chunk_num)
                    if chunk_info and chunk_info.get("text"):
                        # Tô sáng câu bằng chứng hoặc các thực thể tham gia quan hệ
                        highlight_targets = [evidence] if evidence else [src_name, tgt_name]
                        rendered_html = highlight_text_html(
                            chunk_info["text"],
                            highlight_targets,
                            background="#fed7aa" if evidence else "#fde047",
                        )
                        st.markdown(rendered_html, unsafe_allow_html=True)
                    elif evidence:
                        st.markdown(
                            f"<div style='padding:8px 12px;background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px;color:#92400e;'>"
                            f"💬 <em>&ldquo;{html.escape(evidence)}&rdquo;</em>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

            if len(matching_edges) > max_edges_per_relation:
                st.caption(f"*Và {len(matching_edges) - max_edges_per_relation} cạnh khác sử dụng quan hệ này...*")
