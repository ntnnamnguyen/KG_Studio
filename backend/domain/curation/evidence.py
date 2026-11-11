"""Đối chiếu câu trích dẫn bằng chứng trên văn bản tài liệu gốc và định vị span ký tự."""
from __future__ import annotations

import copy
import re
from typing import Any

from backend.domain.documents.processor import count_chunks, page_at
from shared.text_utils import normal, now_iso, uid

from .common import (
    clean_display_text,
    doc_fingerprint,
    find_document,
    find_edge,
    find_node,
    resolve_active_node_id,
)


def evidence_in_chunk(quote: str, chunk: str) -> bool:
    q = normal(quote or "")
    return bool(q) and q in normal(chunk or "")


def find_all_quote_spans(text: str, quote: str) -> list[tuple[int, int, str]]:
    """Tìm tất cả các vị trí xuất hiện của quote trong text; trả về danh sách (start, end, match_method)."""
    clean_q = (quote or "").strip()
    if not clean_q or not text:
        return []

    spans: list[tuple[int, int, str]] = []
    start_idx = 0
    while True:
        pos = text.find(clean_q, start_idx)
        if pos < 0:
            break
        spans.append((pos, pos + len(clean_q), "exact"))
        start_idx = pos + max(1, len(clean_q))

    if spans:
        return spans

    tokens = [re.escape(t) for t in clean_q.split() if t]
    if not tokens:
        return []
    pattern = re.compile(r"\s+".join(tokens), re.IGNORECASE | re.UNICODE)
    for match in pattern.finditer(text):
        spans.append((match.start(), match.end(), "normalized"))
    return spans


def find_quote_span(text: str, quote: str) -> tuple[int, int] | None:
    spans = find_all_quote_spans(text, quote)
    if not spans:
        return None
    return spans[0][0], spans[0][1]


def evidence_context(
    project: dict,
    edge: dict,
    radius: int = 420,
    *,
    precomputed: dict[str, Any] | None = None,
    include_snippets: bool = True,
) -> dict[str, Any]:
    """Đối chiếu bằng chứng trên văn bản gốc hiện tại:
    - Ưu tiên vị trí đã xác minh / đã lưu nếu fingerprint tài liệu còn khớp.
    - Giới hạn trong phạm vi đoạn (start_char..end_char) nếu có.
    - Nếu có nhiều vị trí khớp mà chưa xác định được vị trí duy nhất, báo ambiguous=True ("Nhiều vị trí phù hợp").
    - Không tự bịa số trang nếu tài liệu không có thông tin phân trang.
    """
    doc_id = str(edge.get("doc_id", ""))
    if precomputed is not None and "docs_by_id" in precomputed:
        doc = precomputed["docs_by_id"].get(doc_id)
    else:
        doc = find_document(project, doc_id)
    if not doc or not str(doc.get("text", "")):
        return {
            "found": False,
            "match_method": "missing_doc",
            "match_label": "Thiếu nguồn",
            "text": "",
            "quote": "",
            "before_text": "",
            "after_text": "",
            "page": None,
            "start_char": None,
            "end_char": None,
            "doc_fingerprint": "",
            "ambiguous": False,
            "candidates": [],
            "reason": "Không tìm thấy tài liệu gốc",
        }

    text = str(doc.get("text", ""))
    if precomputed is not None and "doc_fingerprints" in precomputed:
        cur_fp = precomputed["doc_fingerprints"].get(doc_id) or doc_fingerprint(doc)
    else:
        cur_fp = doc_fingerprint(doc)
    saved_fp = str(edge.get("doc_fingerprint") or "")
    fp_valid = (not saved_fp) or (saved_fp == cur_fp)
    has_pages = bool(doc.get("pages"))

    quote_str = str(edge.get("evidence") or "").strip()
    if not quote_str:
        is_override = bool(edge.get("override"))
        return {
            "found": False,
            "match_method": "override" if is_override else "not_found",
            "match_label": "Ngoại lệ bằng chứng" if is_override else "Không có bằng chứng",
            "text": "",
            "quote": "",
            "before_text": "",
            "after_text": "",
            "page": None,
            "start_char": None,
            "end_char": None,
            "doc_fingerprint": cur_fp,
            "ambiguous": False,
            "candidates": [],
            "reason": "Cạnh không có câu trích dẫn bằng chứng",
        }

    selected_span: tuple[int, int, str] | None = None
    all_spans: list[tuple[int, int, str]] | None = None
    candidate_spans: list[tuple[int, int, str]] = []
    ambiguous = False

    # ĐƯỜNG NHANH 1: So sánh trực tiếp lát cắt hoặc tìm trong phạm vi đoạn (chunk) nếu fingerprint còn hiệu lực
    if fp_valid:
        v_start = edge.get("verified_start_char")
        v_end = edge.get("verified_end_char")
        if v_start is not None and v_end is not None:
            vs, ve = int(v_start), int(v_end)
            if 0 <= vs < ve <= len(text):
                slice_text = text[vs:ve]
                if slice_text == quote_str:
                    selected_span = (vs, ve, "exact")
                    candidate_spans = [selected_span]
                elif abs((ve - vs) - len(quote_str)) <= max(64, len(quote_str)) and normal(slice_text) == normal(quote_str):
                    selected_span = (vs, ve, "normalized")
                    candidate_spans = [selected_span]

        if selected_span is None:
            s_char = edge.get("start_char")
            e_char = edge.get("end_char")
            if s_char is not None and e_char is not None:
                s_int, e_int = int(s_char), int(e_char)
                if 0 <= s_int < e_int <= len(text):
                    span_len = e_int - s_int
                    q_len = len(quote_str)
                    if span_len == q_len and text[s_int:e_int] == quote_str:
                        selected_span = (s_int, e_int, "exact")
                        candidate_spans = [selected_span]
                    elif span_len >= max(1, q_len // 2):
                        chunk_matches = find_all_quote_spans(text[s_int:e_int], quote_str)
                        if chunk_matches:
                            in_chunk = [(s_int + cs, s_int + ce, cm) for cs, ce, cm in chunk_matches]
                            if len(in_chunk) == 1:
                                selected_span = in_chunk[0]
                                candidate_spans = in_chunk
                            else:
                                selected_span = in_chunk[0]
                                candidate_spans = in_chunk
                                ambiguous = True

    # ĐƯỜNG CHẬM: Chỉ quét toàn văn tài liệu khi không tìm thấy trong lát cắt/đoạn đã lưu
    if selected_span is None:
        all_spans = find_all_quote_spans(text, quote_str)
        if not all_spans:
            is_override = bool(edge.get("override"))
            return {
                "found": False,
                "match_method": "override" if is_override else "not_found",
                "match_label": "Ngoại lệ bằng chứng" if is_override else "Không tìm thấy",
                "text": "",
                "quote": "",
                "before_text": "",
                "after_text": "",
                "page": page_at(doc.get("pages"), int(edge["start_char"])) if (has_pages and edge.get("start_char") is not None) else None,
                "start_char": None,
                "end_char": None,
                "doc_fingerprint": cur_fp,
                "ambiguous": False,
                "candidates": [],
                "reason": "Trích dẫn không xuất hiện nguyên văn trong tài liệu",
            }
        candidate_spans = list(all_spans)
        if fp_valid:
            s_char = edge.get("start_char")
            e_char = edge.get("end_char")
            if s_char is not None and e_char is not None:
                s_int, e_int = int(s_char), int(e_char)
                in_chunk = [sp for sp in all_spans if s_int <= sp[0] and sp[1] <= e_int]
                if len(in_chunk) == 1:
                    selected_span = in_chunk[0]
                elif len(in_chunk) > 1:
                    candidate_spans = in_chunk
                    ambiguous = True

        if selected_span is None:
            if len(candidate_spans) == 1:
                selected_span = candidate_spans[0]
            else:
                ambiguous = True
                selected_span = candidate_spans[0]
    elif not candidate_spans:
        candidate_spans = [selected_span]

    start, end, method = selected_span
    page_val = page_at(doc.get("pages"), start) if has_pages else None

    if ambiguous:
        match_label = f"Nhiều vị trí phù hợp ({len(candidate_spans)})"
    elif method == "exact":
        match_label = "Khớp nguyên văn"
    else:
        match_label = "Khớp sau chuẩn hóa"

    if not include_snippets:
        return {
            "found": True,
            "match_method": method,
            "match_label": match_label,
            "text": "",
            "before_text": "",
            "quote": "",
            "after_text": "",
            "page": page_val,
            "chunk_number": edge.get("chunk_number"),
            "doc_name": doc.get("name", edge.get("doc_name", "")),
            "start_char": start,
            "end_char": end,
            "doc_fingerprint": cur_fp,
            "fingerprint_valid": fp_valid,
            "ambiguous": ambiguous,
            "candidates": [],
            "reason": "Có nhiều vị trí khớp câu trích dẫn trong tài liệu; hãy chọn vị trí đúng." if ambiguous else "",
        }

    left = max(0, start - radius)
    right = min(len(text), end + radius)

    candidates_out: list[dict[str, Any]] = []
    for idx, (cs, ce, cm) in enumerate(candidate_spans, 1):
        c_left = max(0, cs - 120)
        c_right = min(len(text), ce + 120)
        candidates_out.append(
            {
                "index": idx,
                "start_char": cs,
                "end_char": ce,
                "match_method": cm,
                "page": page_at(doc.get("pages"), cs) if has_pages else None,
                "before_text": text[c_left:cs],
                "quote": text[cs:ce],
                "after_text": text[ce:c_right],
                "snippet": text[c_left:c_right],
            }
        )

    return {
        "found": True,
        "match_method": method,
        "match_label": match_label,
        "text": text[left:right],
        "before_text": text[left:start],
        "quote": text[start:end],
        "after_text": text[end:right],
        "page": page_val,
        "chunk_number": edge.get("chunk_number"),
        "doc_name": doc.get("name", edge.get("doc_name", "")),
        "start_char": start,
        "end_char": end,
        "doc_fingerprint": cur_fp,
        "fingerprint_valid": fp_valid,
        "ambiguous": ambiguous,
        "candidates": candidates_out,
        "reason": "Có nhiều vị trí khớp câu trích dẫn trong tài liệu; hãy chọn vị trí đúng." if ambiguous else "",
    }


def select_edge_evidence_span(
    project: dict,
    edge_id: str,
    start_char: int,
    end_char: int,
    *,
    actor: str = "human_reviewer",
) -> dict[str, Any]:
    """Xác nhận vị trí ký tự (start_char, end_char) cụ thể khi câu dẫn chứng xuất hiện nhiều lần."""
    edge = find_edge(project, edge_id)
    if not edge:
        raise ValueError("Không tìm thấy quan hệ")
    doc = find_document(project, str(edge.get("doc_id", "")))
    if not doc or not str(doc.get("text", "")):
        raise ValueError("Không tìm thấy tài liệu nguồn của quan hệ")
    text = str(doc["text"])
    s_int, e_int = int(start_char), int(end_char)
    if s_int < 0 or e_int > len(text) or s_int >= e_int:
        raise ValueError("Vị trí ký tự không hợp lệ trên tài liệu hiện tại")
    spans = find_all_quote_spans(text, str(edge.get("evidence", "")))
    matched = next((sp for sp in spans if sp[0] == s_int and sp[1] == e_int), None)
    if matched is None:
        raise ValueError("Vị trí được chọn không khớp với câu trích dẫn của dữ kiện")

    before_state = copy.deepcopy(edge)
    cur_fp = doc_fingerprint(doc)
    edge["verified_start_char"] = s_int
    edge["verified_end_char"] = e_int
    edge["start_char"] = s_int
    edge["end_char"] = e_int
    edge["doc_fingerprint"] = cur_fp
    edge["match_method"] = matched[2]
    edge["evidence_found"] = True
    if doc.get("pages"):
        edge["page"] = page_at(doc.get("pages"), s_int)

    project.setdefault("curation_history", []).append(
        {
            "id": uid(),
            "at": now_iso(),
            "actor": actor,
            "action": "select_evidence_span",
            "target_id": edge_id,
            "before": before_state,
            "after": copy.deepcopy(edge),
            "note": f"Chọn vị trí bằng chứng [{s_int}:{e_int}]",
        }
    )
    return evidence_context(project, edge)


def recheck_edge_evidence(project: dict, edge: dict) -> bool:
    ctx = evidence_context(project, edge)
    verified = bool(ctx["found"])
    edge["evidence_found"] = verified
    if verified:
        edge["match_method"] = ctx.get("match_method", "exact")
        edge["doc_fingerprint"] = ctx.get("doc_fingerprint", "")
    return verified

