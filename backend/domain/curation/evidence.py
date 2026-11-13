"""Đối chiếu câu trích dẫn bằng chứng trên văn bản tài liệu gốc và định vị span ký tự."""
from __future__ import annotations

import copy
import math
import re
import unicodedata
from collections import Counter
from typing import Any

from backend.domain.documents.processor import count_chunks, page_at
from shared.text_utils import normal, now_iso, tokenize_vn, uid

from .common import (
    clean_display_text,
    doc_fingerprint,
    find_document,
    find_edge,
    find_node,
    resolve_active_node_id,
)

_WORD_TOKEN_RE = re.compile(r"[0-9a-zA-ZÀ-ỹ]+")
_NON_WORD_GAP = r"[^0-9a-zA-ZÀ-ỹ]+"
_ELLIPSIS_MAX_GAP = 600
_SUGGESTION_MIN_COSINE = 0.40

_MATCH_LABELS: dict[str, str] = {
    "exact": "Khớp nguyên văn",
    "normalized": "Khớp sau chuẩn hóa",
    "near_verbatim": "Khớp gần nguyên văn",
    "ellipsis_match": "Khớp có lược (...)",
}


def _map_nfc_spans(
    raw_text: str,
    nfc_text: str,
    spans: list[tuple[int, int, str]],
) -> list[tuple[int, int, str]]:
    """Ánh xạ offset từ chuỗi đã chuẩn hóa NFC về đúng vị trí ký tự trên raw_text (bảo toàn tài liệu NFD)."""
    if not spans or len(nfc_text) == len(raw_text):
        return spans
    nfc_to_raw: list[tuple[int, int]] = []
    idx = 0
    total = len(raw_text)
    while idx < total:
        end = idx + 1
        while end < total and unicodedata.category(raw_text[end]).startswith("M"):
            end += 1
        for _ in unicodedata.normalize("NFC", raw_text[idx:end]):
            nfc_to_raw.append((idx, end))
        idx = end
    if len(nfc_to_raw) != len(nfc_text):
        return []
    mapped: list[tuple[int, int, str]] = []
    for s, e, method in spans:
        if 0 <= s < e <= len(nfc_to_raw):
            mapped.append((nfc_to_raw[s][0], nfc_to_raw[e - 1][1], method))
    return mapped


def _compile_word_gap(words: list[str]) -> re.Pattern[str]:
    return re.compile(_NON_WORD_GAP.join(map(re.escape, words)), re.IGNORECASE)


def _bow_cosine(a: str, b: str) -> float:
    """Tính Lexical Cosine trên unigram + word bigram tiếng Việt (thuần miền, 0 phụ thuộc ngoài)."""
    ta = Counter(tokenize_vn(a))
    tb = Counter(tokenize_vn(b))
    if not ta or not tb:
        return 0.0
    common = set(ta) & set(tb)
    if not common:
        return 0.0
    dot = sum(ta[k] * tb[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in ta.values()))
    norm_b = math.sqrt(sum(v * v for v in tb.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def find_nearest_evidence_candidates(
    text: str,
    quote: str,
    *,
    base_offset: int = 0,
    pages: list[dict] | None = None,
    top_k: int = 2,
    min_score: float = _SUGGESTION_MIN_COSINE,
) -> list[dict[str, Any]]:
    """Tầng 2 (Chỉ gợi ý): Tìm 1-2 đoạn gốc gần nhất theo Lexical Cosine trên cửa sổ 1-2 câu/dòng."""
    clean_q = (quote or "").strip()
    if not clean_q or not (text or "").strip():
        return []

    segments: list[tuple[int, int]] = []
    # Tách theo dòng trước, sau đó tách tiếp câu dài theo dấu kết thúc câu (. ! ?) để vừa giữ được bullet vừa tách rõ đoạn văn xuôi
    for line_m in re.finditer(r"[^\n]+", text):
        ls, le = line_m.start(), line_m.end()
        line_str = text[ls:le]
        if not line_str.strip():
            continue
        cur = 0
        for split_m in re.finditer(r"(?<=[.!?])\s+", line_str):
            seg_raw = line_str[cur : split_m.start()]
            if seg_raw.strip():
                l_pad = len(seg_raw) - len(seg_raw.lstrip())
                r_pad = len(seg_raw.rstrip())
                segments.append((ls + cur + l_pad, ls + cur + r_pad))
            cur = split_m.end()
        tail = line_str[cur:]
        if tail.strip():
            l_pad = len(tail) - len(tail.lstrip())
            r_pad = len(tail.rstrip())
            segments.append((ls + cur + l_pad, ls + cur + r_pad))

    if not segments:
        return []

    scored: list[tuple[float, int, int]] = []
    for i in range(len(segments)):
        for span_cnt in (1, 2):
            j = i + span_cnt - 1
            if j >= len(segments):
                break
            ws, we = segments[i][0], segments[j][1]
            if we - ws > 700 or we - ws < 8:
                continue
            cand_txt = text[ws:we]
            score = _bow_cosine(clean_q, cand_txt)
            if score >= min_score:
                scored.append((score, ws, we))

    if not scored:
        return []

    # Ưu tiên điểm cao hơn; nếu bằng điểm ưu tiên đoạn gọn hơn
    scored.sort(key=lambda item: (-round(item[0], 6), item[2] - item[1], item[1]))
    chosen: list[dict[str, Any]] = []
    for score, ws, we in scored:
        gs, ge = base_offset + ws, base_offset + we
        # Tránh gợi ý trùng lặp vùng chồng lấn >50%
        overlaps = False
        for prev in chosen:
            inter = max(0, min(ge, prev["end_char"]) - max(gs, prev["start_char"]))
            if inter > 0.5 * min(ge - gs, prev["end_char"] - prev["start_char"]):
                overlaps = True
                break
        if overlaps:
            continue
        chosen.append(
            {
                "rank": len(chosen) + 1,
                "score": round(score, 4),
                "score_pct": int(round(score * 100)),
                "text": text[ws:we],
                "start_char": gs,
                "end_char": ge,
                "page": page_at(pages, gs) if pages else None,
            }
        )
        if len(chosen) >= top_k:
            break
    return chosen


def evidence_in_chunk(quote: str, chunk: str) -> bool:
    q = normal(quote or "")
    if not q or not chunk:
        return False
    if q in normal(chunk):
        return True
    return bool(find_all_quote_spans(chunk, quote))


def find_all_quote_spans(text: str, quote: str) -> list[tuple[int, int, str]]:
    """Tìm tất cả vị trí xuất hiện của quote theo Tầng 1 (4 nấc: exact -> normalized -> near_verbatim -> ellipsis_match)."""
    clean_q = (quote or "").strip()
    if not clean_q or not text:
        return []

    # Nấc 1: Khớp nguyên văn tuyệt đối
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

    # Nấc 2: Khớp bỏ qua khác biệt khoảng trắng & hoa/thường (trên NFC để tránh lệch NFD)
    ntext = unicodedata.normalize("NFC", text)
    nquote = unicodedata.normalize("NFC", clean_q)
    ws_tokens = [re.escape(t) for t in nquote.split() if t]
    if ws_tokens:
        ws_pat = re.compile(r"\s+".join(ws_tokens), re.IGNORECASE | re.UNICODE)
        ws_spans = [(m.start(), m.end(), "normalized") for m in ws_pat.finditer(ntext)]
        if ws_spans:
            return _map_nfc_spans(text, ntext, ws_spans)

    # Nấc 3: Khớp gần nguyên văn (Word-Gap Regex: dung sai dấu câu cuối, bullet, bảng, ngoặc, khoảng trắng trước dấu)
    has_ellipsis = "..." in nquote or "…" in nquote
    if not has_ellipsis:
        words = _WORD_TOKEN_RE.findall(nquote)
        if len(words) < 3:
            return []
        wg_pat = _compile_word_gap(words)
        wg_spans = [(m.start(), m.end(), "near_verbatim") for m in wg_pat.finditer(ntext)]
        return _map_nfc_spans(text, ntext, wg_spans)

    # Nấc 4: Khớp trích dẫn có lược (...) bằng Linear Anchor Chaining trong cửa sổ bounded
    segments = [_WORD_TOKEN_RE.findall(seg) for seg in re.split(r"\.\.\.|…", nquote)]
    segments = [seg for seg in segments if seg]
    if len(segments) < 2 or sum(len(seg) for seg in segments) < 5 or len(segments[0]) < 2:
        return []
    anchor_pats = [_compile_word_gap(seg) for seg in segments]
    el_spans: list[tuple[int, int, str]] = []
    text_len = len(ntext)
    for m0 in anchor_pats[0].finditer(ntext):
        cur_end = m0.end()
        matched_all = True
        for pat in anchor_pats[1:]:
            m_next = pat.search(ntext, cur_end, min(text_len, cur_end + _ELLIPSIS_MAX_GAP))
            if not m_next:
                matched_all = False
                break
            cur_end = m_next.end()
        if matched_all:
            el_spans.append((m0.start(), cur_end, "ellipsis_match"))
    return _map_nfc_spans(text, ntext, el_spans)


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
            "suggestions": [],
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
            "suggestions": [],
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
                else:
                    slice_matches = find_all_quote_spans(slice_text, quote_str)
                    if len(slice_matches) == 1 and slice_matches[0][0] == 0 and slice_matches[0][1] == len(slice_text):
                        selected_span = (vs, ve, slice_matches[0][2])
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
            suggestions: list[dict[str, Any]] = []
            if include_snippets:
                sug_text = text
                sug_base = 0
                if fp_valid and edge.get("start_char") is not None and edge.get("end_char") is not None:
                    cs_i, ce_i = int(edge["start_char"]), int(edge["end_char"])
                    if 0 <= cs_i < ce_i <= len(text):
                        sug_text = text[cs_i:ce_i]
                        sug_base = cs_i
                doc_pages = doc.get("pages") if has_pages else None
                suggestions = find_nearest_evidence_candidates(
                    sug_text,
                    quote_str,
                    base_offset=sug_base,
                    pages=doc_pages,
                )
                if not suggestions and sug_base != 0:
                    suggestions = find_nearest_evidence_candidates(
                        text,
                        quote_str,
                        base_offset=0,
                        pages=doc_pages,
                    )
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
                "suggestions": suggestions,
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
    else:
        match_label = _MATCH_LABELS.get(method, "Khớp sau chuẩn hóa")

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
            "suggestions": [],
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
        "suggestions": [],
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

