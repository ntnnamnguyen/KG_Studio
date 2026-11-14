"""Đóng gói và sinh Bộ dữ liệu Huấn luyện Chuẩn G-Retriever 5 tệp (KGQA Bundle).

Xuất 5 tệp chuẩn:
- nodes.csv (UTF-8 BOM): node_id, canonical_name, type, normalized_key, aliases
- edges.csv (UTF-8 BOM): edge_id, source_id, source_name, relation, target_id, target_name, confidence, sources, evidence_ids
- evidence.csv (UTF-8 BOM): evidence_id, text, source, doc_title, chunk_uid
- questions.csv (UTF-8 BOM): question_id, question, question_type, answer_text, answers, answer_entity_ids,
  topic_entity_ids, relation_path, traversal_directions, gold_edge_ids, gold_paths, evidence_edges, evidence, review_status
- schema_contract.json: giữ nguyên tên loại thực thể (entity_types) và loại quan hệ (relations) của dự án.

Module thuần domain (không import integrations/repositories).
"""
from __future__ import annotations

import ast
import collections
import copy
import io
import json
import re
import unicodedata
import zipfile
from typing import Any

from backend.domain.graph.qa_generator import (
    _clean_natural_question_text,
    _format_predicate_question,
    _infer_entity_natural_label,
    clean_rel_name,
    synthesize_1hop_inverse_question,
    synthesize_1hop_natural_question,
    synthesize_2hop_bridge_question,
)
from shared.constants import STATUS_APPROVED
from shared.text_utils import normal

NODES_CSV_HEADERS = ["node_id", "canonical_name", "type", "normalized_key", "aliases"]
EDGES_CSV_HEADERS = [
    "edge_id",
    "source_id",
    "source_name",
    "relation",
    "target_id",
    "target_name",
    "confidence",
    "sources",
    "evidence_ids",
]
EVIDENCE_CSV_HEADERS = ["evidence_id", "text", "source", "doc_title", "chunk_uid"]
QUESTIONS_CSV_HEADERS = [
    "question_id",
    "question",
    "question_type",
    "answer_text",
    "answers",
    "answer_entity_ids",
    "topic_entity_ids",
    "relation_path",
    "traversal_directions",
    "gold_edge_ids",
    "gold_paths",
    "evidence_edges",
    "evidence",
    "review_status",
]

_BANNED_QA_FRAGMENTS = (
    "theo đồ thị tri thức",
    "có mối quan hệ",
    "đối tượng hay thông tin nào",
    "thực thể hay đối tượng nào",
)

_PLACEHOLDER_GENERIC_NOUNS = frozenset({
    "huyện",
    "nhà nước",
    "phường",
    "quận",
    "thành phố",
    "trung ương",
    "xã",
    "không rõ",
    "chưa rõ",
})

_KIND_LIST_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("person", "nhân vật", "vua", "danh nhân", "tác giả", "sư"), "nhân vật"),
    (("place", "địa danh", "location", "admin", "quận", "huyện", "phường", "vị trí"), "địa danh"),
    (("event", "sự kiện"), "sự kiện"),
    (("group", "org", "tổ chức", "triều", "đơn vị"), "tổ chức hoặc đơn vị"),
    (("time", "thời gian", "năm", "niên đại"), "mốc thời gian"),
    (("object", "di tích", "công trình", "chùa", "đền", "hiện vật"), "công trình hoặc di tích"),
)


def normalize_ascii_snake_key(text: str) -> str:
    """Chuẩn hóa chuỗi tiếng Việt thành khóa ASCII snake_case (hỗ trợ đ/Đ -> d)."""
    raw = unicodedata.normalize("NFC", str(text or "").strip())
    raw = raw.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFKD", raw)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-zA-Z0-9]+", "_", stripped).strip("_").lower()


def _make_kind_prefix_map(kinds: list[str]) -> dict[str, str]:
    """Tạo tiền tố node_id ngắn, đọc được và không trùng giữa các loại thực thể khác nhau."""
    prefix_map: dict[str, str] = {}
    used: set[str] = set()
    for kind in sorted({str(k or "").strip() for k in kinds}, key=lambda x: (normal(x), x)):
        ascii_key = normalize_ascii_snake_key(kind)
        trimmed = re.sub(r"^e\d+_", "", ascii_key)
        candidate_raw = (trimmed if len(trimmed) >= 3 else ascii_key).replace("_", "").upper()
        base = candidate_raw[:8] or "ENTITY"
        prefix = base
        idx = 2
        while prefix in used:
            suffix = str(idx)
            prefix = f"{base[: max(1, 8 - len(suffix))]}{suffix}"
            idx += 1
        used.add(prefix)
        prefix_map[kind] = prefix
    return prefix_map


def _clean_node_aliases(
    raw_aliases: Any,
    canonical_name: str,
    *,
    kind: str = "",
    gazetteer: dict[str, Any] | None = None,
) -> list[str]:
    """Gom và khử trùng bí danh từ node và domain_gazetteer (bảo toàn ranh giới đồng âm theo kind)."""
    canon_norm = normal(canonical_name)
    kind_norm = normal(kind)
    seen: set[str] = {canon_norm} if canon_norm else set()
    out: list[str] = []

    candidates: list[str] = []
    if isinstance(raw_aliases, (list, tuple, set)):
        candidates.extend(str(a or "").strip() for a in raw_aliases)
    elif isinstance(raw_aliases, str) and raw_aliases.strip():
        candidates.extend(p.strip() for p in re.split(r"[|;\n]+", raw_aliases) if p.strip())

    if isinstance(gazetteer, dict) and canon_norm:
        for g_val in gazetteer.values():
            if not isinstance(g_val, dict):
                continue
            g_canon = normal(str(g_val.get("canonical_name", "")))
            g_kind = normal(str(g_val.get("kind", "")))
            if g_canon != canon_norm:
                continue
            if kind_norm and g_kind and g_kind != kind_norm:
                continue
            alias_text = str(g_val.get("alias", "")).strip()
            if alias_text:
                candidates.append(alias_text)

    for cand in candidates:
        c_norm = normal(cand)
        if not c_norm or c_norm in seen:
            continue
        seen.add(c_norm)
        out.append(cand)
    return out


def _kind_semantic_hint(raw_kind: str) -> str:
    """Bổ sung gợi ý tiếng Việt cho tag tiếng Anh/CIDOC (chỉ dùng nội bộ để chia câu hỏi tự nhiên)."""
    raw = str(raw_kind or "").strip()
    k = normal(raw)
    if any(t in k for t in ("person", "actor", "author", "creator", "nhân vật")):
        return f"{raw} nhân vật"
    if any(t in k for t in ("place", "location", "admin", "địa danh", "địa điểm")):
        return f"{raw} địa danh"
    if any(t in k for t in ("event", "sự kiện")):
        return f"{raw} sự kiện lịch sử"
    if any(t in k for t in ("group", "org", "dynasty", "tổ chức", "triều")):
        return f"{raw} tổ chức"
    if any(t in k for t in ("time", "date", "year", "thời gian", "năm")):
        return f"{raw} thời gian"
    if any(t in k for t in ("object", "monument", "building", "công trình", "di tích")):
        return f"{raw} công trình di tích"
    return raw


def _natural_predicate_tail(rel: str, target_kind: str) -> str:
    """Sinh cụm hỏi vị ngữ tự nhiên, ưu tiên ngữ nghĩa đích (ví dụ dưới triều + Nhân vật)."""
    rel_c = clean_rel_name(rel) or rel
    r_norm = normal(rel_c)
    tk_hint = _kind_semantic_hint(target_kind)
    tk_norm = normal(tk_hint)
    if any(x in r_norm for x in ("dưới triều", "dưới thời", "triều vua", "đời vua")) and "nhân vật" in tk_norm:
        return f"được {rel_c} ai?" if not rel_c.startswith("được") else f"{rel_c} ai?"
    if any(x in r_norm for x in ("dưới triều", "dưới thời", "triều")) and "tổ chức" in tk_norm:
        return f"gắn với triều đại hay {rel_c} nào?"
    return _format_predicate_question(rel, tk_hint)


def _infer_plural_noun_from_kind(kinds: list[str]) -> str:
    joined = " ".join(normal(k) for k in kinds if str(k or "").strip())
    for keywords, hint in _KIND_LIST_HINTS:
        if any(kw in joined for kw in keywords):
            return hint
    return "đối tượng"


def synthesize_2hop_rev_fwd_question(
    u_name: str,
    u_kind: str,
    r1: str,
    b_name: str,
    b_kind: str,
    r2: str,
    c_name: str,
    c_kind: str,
    idx_seed: int = 0,
) -> str:
    """Sinh câu hỏi 2-hop dạng reverse -> forward: bridge -[r1]-> topic(u) & bridge -[r2]-> answer(c)."""
    b_label = _infer_entity_natural_label(b_name, _kind_semantic_hint(b_kind), outgoing_rel=r1)
    r1_c = clean_rel_name(r1) or r1
    pred_tail = _natural_predicate_tail(r2, c_kind)
    pred_body = pred_tail.rstrip("?").strip()

    templates = [
        f"{b_label} {r1_c} {u_name} {pred_body}?",
        f"Cho biết {b_label.lower()} {r1_c} {u_name} {pred_body}?",
        f"{b_label} nào {r1_c} {u_name} và {pred_body}?",
    ]
    chosen = templates[idx_seed % len(templates)]
    return _clean_natural_question_text(chosen)


def synthesize_list_question(
    topic_name: str,
    rel: str,
    direction: str,
    answer_kinds: list[str],
    idx_seed: int = 0,
) -> str:
    """Sinh câu hỏi liệt kê nhiều đáp án (question_type='list') tự nhiên bằng tiếng Việt."""
    noun_hint = _infer_plural_noun_from_kind(answer_kinds)
    rel_c = clean_rel_name(rel) or rel
    r_norm = normal(rel_c)

    if direction == "reverse":
        if any(k in r_norm for k in ("tọa lạc", "nằm ở", "nằm tại", "thuộc")):
            variants = [
                f"Những {noun_hint} nào {rel_c} {topic_name}?",
                f"Hãy liệt kê các {noun_hint} {rel_c} {topic_name}?",
                f"Kể tên những {noun_hint} {rel_c} {topic_name}?",
            ]
        else:
            variants = [
                f"Những {noun_hint} nào {rel_c} {topic_name}?",
                f"Hãy liệt kê các {noun_hint} {rel_c} {topic_name}?",
                f"Có những {noun_hint} nào {rel_c} {topic_name}?",
            ]
        return _clean_natural_question_text(variants[idx_seed % len(variants)])

    # direction == "forward"
    if any(k in r_norm for k in ("thờ",)):
        variants = [
            f"{topic_name} thờ những nhân vật hay danh nhân nào?",
            f"Hãy liệt kê các nhân vật được thờ phụng tại {topic_name}?",
        ]
    elif any(k in r_norm for k in ("bao gồm", "chứa", "trưng bày", "lưu giữ")):
        variants = [
            f"{topic_name} {rel_c} những {noun_hint} nào?",
            f"Hãy liệt kê các {noun_hint} được {topic_name} {rel_c}?",
        ]
    else:
        variants = [
            f"{topic_name} {rel_c} những {noun_hint} nào?",
            f"Hãy liệt kê tất cả {noun_hint} mà {topic_name} {rel_c}?",
        ]
    return _clean_natural_question_text(variants[idx_seed % len(variants)])


def build_kgqa_schema_contract(
    project: dict[str, Any],
    export_nodes: list[dict[str, Any]],
    export_edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Tạo schema_contract.json giữ nguyên vẹn 100% entity_types và relations của dự án."""
    entity_type_notes: dict[str, dict[str, str]] = {}
    for item in project.get("entity_types") or []:
        if isinstance(item, dict):
            t_name = str(item.get("name", "")).strip()
            if t_name:
                label = str(item.get("definition") or item.get("description") or t_name).strip()
                entity_type_notes[t_name] = {"type": t_name, "label_vi": label or t_name}
        elif isinstance(item, str) and item.strip():
            t_name = item.strip()
            entity_type_notes[t_name] = {"type": t_name, "label_vi": t_name}

    for node in export_nodes:
        t_name = str(node.get("type", "")).strip()
        if t_name and t_name not in entity_type_notes:
            entity_type_notes[t_name] = {"type": t_name, "label_vi": t_name}

    node_types = {k: entity_type_notes[k] for k in sorted(entity_type_notes, key=lambda x: (normal(x), x))}

    rel_notes_raw = project.get("relation_notes") or {}
    relation_specs: dict[str, dict[str, str]] = {}

    def _register_relation(rel_name: str) -> None:
        r_name = str(rel_name or "").strip()
        if not r_name or r_name in relation_specs:
            return
        note = rel_notes_raw.get(r_name) if isinstance(rel_notes_raw, dict) else {}
        label = ""
        if isinstance(note, dict):
            label = str(note.get("definition") or note.get("description") or "").strip()
        phrase = clean_rel_name(r_name) or r_name
        relation_specs[r_name] = {
            "relation": r_name,
            "label_vi": label or phrase,
            "template": f"{{head}} {phrase} {{tail}}",
        }

    for r in project.get("relations") or []:
        if isinstance(r, dict):
            _register_relation(str(r.get("name", "")))
        else:
            _register_relation(str(r))

    for edge in export_edges:
        _register_relation(str(edge.get("relation", "")))

    relation_types = {k: relation_specs[k] for k in sorted(relation_specs, key=lambda x: (normal(x), x))}

    return {
        "version": "2.1",
        "domain": str(project.get("name") or project.get("project_id") or "KG Studio Knowledge Graph").strip(),
        "schema_policy": "preserve_project_entity_types_and_relations",
        "review_status_policy": "auto_generated_until_human_verified",
        "node_types": node_types,
        "relation_types": relation_types,
    }


def _collect_edge_confidence(grouped_raw_edges: list[dict[str, Any]]) -> float:
    """Tính confidence tường minh dựa trên trường numeric sẵn có hoặc trạng thái duyệt curation."""
    explicit_scores: list[float] = []
    for edge in grouped_raw_edges:
        val = edge.get("confidence")
        if isinstance(val, (int, float)) and not isinstance(val, bool) and 0.0 <= float(val) <= 1.0:
            explicit_scores.append(float(val))
    if explicit_scores:
        return round(sum(explicit_scores) / len(explicit_scores), 4)
    if grouped_raw_edges and all(str(e.get("status", "")) == STATUS_APPROVED for e in grouped_raw_edges):
        return 1.0
    if any(str(e.get("status", "")) == STATUS_APPROVED for e in grouped_raw_edges):
        return 0.9
    return 0.7


def _extract_tables(
    project: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[
    list[dict[str, str]],
    list[dict[str, Any]],
    list[dict[str, str]],
    dict[str, str],
    dict[str, dict[str, str]],
    dict[str, dict[str, Any]],
]:
    """Chuyển đổi nodes/edges/documents dự án thành 3 bảng chuẩn (nodes, edges, evidence)."""
    gazetteer = project.get("domain_gazetteer") if isinstance(project.get("domain_gazetteer"), dict) else {}
    docs_by_id = {
        str(d.get("id", "")): d
        for d in (project.get("documents") or [])
        if isinstance(d, dict) and str(d.get("id", "")).strip()
    }
    run_chunk_hashes: dict[tuple[str, int], str] = {}
    for run in project.get("runs") or []:
        if not isinstance(run, dict):
            continue
        did = str(run.get("doc_id", "")).strip()
        c_hash = str(run.get("chunk_hash", "")).strip()
        c_num = run.get("chunk_number")
        if did and c_hash and c_num is not None:
            try:
                run_chunk_hashes[(did, int(c_num))] = c_hash
            except (TypeError, ValueError):
                pass

    # 1. NODES
    valid_nodes = [n for n in nodes if isinstance(n, dict) and str(n.get("id", "")).strip()]
    kinds = [str(n.get("kind") or "Entity").strip() for n in valid_nodes]
    prefix_map = _make_kind_prefix_map(kinds)
    prefix_counters: collections.Counter[str] = collections.Counter()

    sorted_raw_nodes = sorted(
        valid_nodes,
        key=lambda n: (
            str(n.get("kind") or "Entity").strip(),
            normal(str(n.get("name", ""))),
            str(n.get("name", "")).strip(),
            str(n.get("id", "")).strip(),
        ),
    )
    export_nodes: list[dict[str, str]] = []
    orig_to_export_nid: dict[str, str] = {}
    export_nodes_by_id: dict[str, dict[str, str]] = {}

    for raw_n in sorted_raw_nodes:
        orig_id = str(raw_n.get("id", "")).strip()
        canon_name = str(raw_n.get("name", "")).strip() or orig_id
        kind = str(raw_n.get("kind") or "Entity").strip() or "Entity"
        prefix = prefix_map[kind]
        prefix_counters[prefix] += 1
        node_id = f"{prefix}_{prefix_counters[prefix]:06d}"

        aliases = _clean_node_aliases(raw_n.get("aliases"), canon_name, kind=kind, gazetteer=gazetteer)
        row = {
            "node_id": node_id,
            "canonical_name": canon_name,
            "type": kind,
            "normalized_key": normalize_ascii_snake_key(canon_name),
            "aliases": "|".join(aliases),
        }
        export_nodes.append(row)
        orig_to_export_nid[orig_id] = node_id
        export_nodes_by_id[node_id] = row

    # 2. EVIDENCE & EDGES (khử trùng cạnh theo bộ ba chuẩn (source_id, relation, target_id))
    grouped_edges: dict[tuple[str, str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for raw_e in edges:
        if not isinstance(raw_e, dict):
            continue
        s_orig = str(raw_e.get("source", "")).strip()
        t_orig = str(raw_e.get("target", "")).strip()
        rel = str(raw_e.get("relation", "")).strip()
        if not rel or s_orig not in orig_to_export_nid or t_orig not in orig_to_export_nid:
            continue
        s_id = orig_to_export_nid[s_orig]
        t_id = orig_to_export_nid[t_orig]
        grouped_edges[(s_id, rel, t_id)].append(raw_e)

    ev_key_to_record: dict[tuple[str, str, str, str], dict[str, str]] = {}
    default_mode = str(project.get("extraction_mode") or "chunk_extraction").strip() or "chunk_extraction"

    def _register_evidence(
        ev_text: str,
        *,
        doc_id: str,
        doc_name: str,
        chunk_number: Any,
        chunk_hash: str,
        extraction_mode: str,
        explicit_source_label: str = "",
    ) -> tuple[str, tuple[str, str, str, str]]:
        text_clean = re.sub(r"\s+", " ", str(ev_text or "").strip())
        doc = docs_by_id.get(doc_id, {})
        source_label = (
            str(explicit_source_label or doc.get("source_label") or extraction_mode or default_mode).strip()
            or "chunk_extraction"
        )
        doc_title = str(doc_name or doc.get("name") or "").strip()

        resolved_hash = str(chunk_hash or "").strip()
        if not resolved_hash and doc_id and chunk_number is not None:
            try:
                resolved_hash = run_chunk_hashes.get((doc_id, int(chunk_number)), "")
            except (TypeError, ValueError):
                resolved_hash = ""
        chunk_uid = f"CHK_{resolved_hash[:16]}" if resolved_hash else ""
        ev_key = (normal(text_clean), source_label, doc_title, chunk_uid)
        if ev_key not in ev_key_to_record:
            ev_key_to_record[ev_key] = {
                "evidence_id": "",
                "text": text_clean,
                "source": source_label,
                "doc_title": doc_title,
                "chunk_uid": chunk_uid,
            }
        return source_label, ev_key

    # Gom cặp (edge_key -> (sources, ev_keys)) trước để gán EVD_000001.. theo thứ tự xác định
    edge_meta_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for triple_key in sorted(grouped_edges.keys()):
        raw_list = grouped_edges[triple_key]
        src_labels: list[str] = []
        ev_keys: list[tuple[str, str, str, str]] = []
        seen_ev_keys: set[tuple[str, str, str, str]] = set()

        for raw_e in raw_list:
            e_doc_id = str(raw_e.get("doc_id", "")).strip()
            e_doc_name = str(raw_e.get("doc_name", "")).strip()
            e_chunk_num = raw_e.get("chunk_number")
            e_chunk_hash = str(raw_e.get("chunk_hash", "")).strip()
            e_mode = str(raw_e.get("extraction_mode", "")).strip()
            e_doc = docs_by_id.get(e_doc_id, {})
            top_src = str(e_doc.get("source_label") or e_mode or default_mode).strip() or "chunk_extraction"
            if top_src not in src_labels:
                src_labels.append(top_src)

            sub_evs = raw_e.get("evidences") if isinstance(raw_e.get("evidences"), list) else []
            matched_any = False
            for sub in sub_evs:
                if not isinstance(sub, dict):
                    continue
                sub_text = str(sub.get("evidence", "")).strip()
                if not sub_text:
                    continue
                matched_any = True
                sub_did = str(sub.get("doc_id") or e_doc_id).strip()
                sub_dname = str(sub.get("doc_name") or e_doc_name).strip()
                sub_cnum = sub.get("chunk_number", e_chunk_num)
                sub_chash = str(sub.get("chunk_hash") or (e_chunk_hash if sub_did == e_doc_id and sub_cnum == e_chunk_num else "")).strip()
                sub_mode = str(sub.get("extraction_mode") or e_mode).strip()
                sub_src_lbl = str(sub.get("source_label") or "").strip()
                src_lbl, ev_k = _register_evidence(
                    sub_text,
                    doc_id=sub_did,
                    doc_name=sub_dname,
                    chunk_number=sub_cnum,
                    chunk_hash=sub_chash,
                    extraction_mode=sub_mode,
                    explicit_source_label=sub_src_lbl,
                )
                if src_lbl not in src_labels:
                    src_labels.append(src_lbl)
                if ev_k not in seen_ev_keys:
                    seen_ev_keys.add(ev_k)
                    ev_keys.append(ev_k)

            top_text = str(raw_e.get("evidence", "")).strip()
            if top_text and not matched_any:
                src_lbl, ev_k = _register_evidence(
                    top_text,
                    doc_id=e_doc_id,
                    doc_name=e_doc_name,
                    chunk_number=e_chunk_num,
                    chunk_hash=e_chunk_hash,
                    extraction_mode=e_mode,
                    explicit_source_label=str(raw_e.get("source_label") or "").strip(),
                )
                if src_lbl not in src_labels:
                    src_labels.append(src_lbl)
                if ev_k not in seen_ev_keys:
                    seen_ev_keys.add(ev_k)
                    ev_keys.append(ev_k)

        edge_meta_by_key[triple_key] = {
            "raw_list": raw_list,
            "sources": src_labels,
            "ev_keys": ev_keys,
        }

    # Gán ID xác định EVD_000001...
    sorted_ev_keys = sorted(
        ev_key_to_record.keys(),
        key=lambda k: (k[2], k[3], k[1], k[0]),
    )
    export_evidence: list[dict[str, str]] = []
    evidence_by_id: dict[str, dict[str, str]] = {}
    for idx, ev_k in enumerate(sorted_ev_keys, 1):
        evd_id = f"EVD_{idx:06d}"
        rec = dict(ev_key_to_record[ev_k])
        rec["evidence_id"] = evd_id
        ev_key_to_record[ev_k] = rec
        export_evidence.append(rec)
        evidence_by_id[evd_id] = rec

    # Gán ID xác định EDGE_000001...
    export_edges: list[dict[str, Any]] = []
    export_edges_by_id: dict[str, dict[str, Any]] = {}
    for idx, triple_key in enumerate(sorted(edge_meta_by_key.keys()), 1):
        s_id, rel, t_id = triple_key
        meta = edge_meta_by_key[triple_key]
        edge_id = f"EDGE_{idx:06d}"
        ev_ids = [ev_key_to_record[k]["evidence_id"] for k in meta["ev_keys"]]
        s_name = export_nodes_by_id[s_id]["canonical_name"]
        t_name = export_nodes_by_id[t_id]["canonical_name"]
        edge_row: dict[str, Any] = {
            "edge_id": edge_id,
            "source_id": s_id,
            "source_name": s_name,
            "relation": rel,
            "target_id": t_id,
            "target_name": t_name,
            "confidence": _collect_edge_confidence(meta["raw_list"]),
            "sources": "|".join(meta["sources"]),
            "evidence_ids": "|".join(ev_ids),
            "_evidence_id_list": ev_ids,
        }
        export_edges.append(edge_row)
        export_edges_by_id[edge_id] = edge_row

    return (
        export_nodes,
        export_edges,
        export_evidence,
        orig_to_export_nid,
        export_nodes_by_id,
        export_edges_by_id,
    )


def _is_valid_entity_name(name: str, *, allow_short_value: bool = False) -> bool:
    cleaned = str(name or "").strip()
    if not cleaned:
        return False
    if normal(cleaned) in _PLACEHOLDER_GENERIC_NOUNS:
        return False
    if not allow_short_value and len(cleaned) < 2:
        return False
    return True


def _no_answer_leak(question: str, topic_names: list[str], answers: list[str]) -> bool:
    """Đảm bảo câu hỏi chứa đúng thực thể hạt giống và không tự làm lộ đáp án mới."""
    q_norm = normal(question)
    if not q_norm or any(ban in q_norm for ban in _BANNED_QA_FRAGMENTS):
        return False
    topic_norms = [normal(t) for t in topic_names if normal(t)]
    if not topic_norms or not all(tn in q_norm for tn in topic_norms):
        return False
    for ans in answers:
        a_norm = normal(ans)
        if len(a_norm) < 2:
            continue
        if any(a_norm in tn or tn in a_norm for tn in topic_norms):
            continue
        if re.search(rf"(?<![0-9a-zà-ỹ]){re.escape(a_norm)}(?![0-9a-zà-ỹ])", q_norm):
            return False
    return True


def _materialize_question_evidence(
    gold_paths: list[list[str]],
    export_edges_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, str]],
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, str]]]:
    """Thu thập đầy đủ gold_edge_ids, evidence_edges và evidence objects gắn với đường đi chuẩn."""
    gold_edge_ids: list[str] = []
    seen_eids: set[str] = set()
    for path in gold_paths:
        for eid in path:
            if eid not in seen_eids and eid in export_edges_by_id:
                seen_eids.add(eid)
                gold_edge_ids.append(eid)

    ev_edges: list[dict[str, Any]] = []
    ev_items: list[dict[str, str]] = []
    seen_ev_ids: set[str] = set()
    for eid in gold_edge_ids:
        e_row = export_edges_by_id[eid]
        e_ev_ids = list(e_row.get("_evidence_id_list") or [])
        ev_edges.append(
            {
                "edge_id": eid,
                "source_id": e_row["source_id"],
                "source_name": e_row["source_name"],
                "relation": e_row["relation"],
                "target_id": e_row["target_id"],
                "target_name": e_row["target_name"],
                "evidence_ids": e_ev_ids,
            }
        )
        for evd_id in e_ev_ids:
            if evd_id in seen_ev_ids or evd_id not in evidence_by_id:
                continue
            seen_ev_ids.add(evd_id)
            ev_obj = evidence_by_id[evd_id]
            ev_items.append(
                {
                    "evidence_id": evd_id,
                    "text": ev_obj["text"],
                    "doc_title": ev_obj["doc_title"],
                    "chunk_uid": ev_obj["chunk_uid"],
                }
            )
    return gold_edge_ids, ev_edges, ev_items


def generate_gretriever_kgqa_questions(
    export_nodes_by_id: dict[str, dict[str, str]],
    export_edges: list[dict[str, Any]],
    evidence_by_id: dict[str, dict[str, str]],
    *,
    max_samples: int = 500,
) -> list[dict[str, Any]]:
    """Sinh các câu hỏi chuẩn G-Retriever gồm single_hop, multi_hop (fwd+fwd & rev+fwd) và list."""
    max_samples = max(1, int(max_samples))
    out_by_node: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    in_by_node: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    degree: collections.Counter[str] = collections.Counter()
    out_by_node_rel: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    in_by_node_rel: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)

    for e in export_edges:
        s_id = e["source_id"]
        t_id = e["target_id"]
        rel = e["relation"]
        if s_id == t_id:
            continue
        out_by_node[s_id].append(e)
        in_by_node[t_id].append(e)
        degree[s_id] += 1
        degree[t_id] += 1
        out_by_node_rel[(s_id, rel)].append(e)
        in_by_node_rel[(t_id, rel)].append(e)

    export_edges_by_id = {e["edge_id"]: e for e in export_edges}

    single_hop_candidates: list[dict[str, Any]] = []
    list_candidates: list[dict[str, Any]] = []
    multi_hop_candidates: list[dict[str, Any]] = []

    seen_signatures: set[tuple[Any, ...]] = set()
    seed_ctr = 0

    def _build_record(
        *,
        question: str,
        question_type: str,
        topic_ids: list[str],
        answer_ids: list[str],
        relation_path: list[str],
        traversal_directions: list[str],
        gold_paths: list[list[str]],
    ) -> dict[str, Any] | None:
        answers = [export_nodes_by_id[aid]["canonical_name"] for aid in answer_ids if aid in export_nodes_by_id]
        topic_names = [export_nodes_by_id[tid]["canonical_name"] for tid in topic_ids if tid in export_nodes_by_id]
        if not answers or not topic_names:
            return None
        q_clean = _clean_natural_question_text(question)
        if not _no_answer_leak(q_clean, topic_names, answers):
            return None
        sig = (question_type, tuple(topic_ids), tuple(relation_path), tuple(traversal_directions))
        if sig in seen_signatures:
            return None
        seen_signatures.add(sig)
        gold_eids, ev_edges, ev_items = _materialize_question_evidence(
            gold_paths, export_edges_by_id, evidence_by_id
        )
        if not gold_eids:
            return None
        return {
            "question_id": "",
            "question": q_clean,
            "original_question": q_clean,
            "question_type": question_type,
            "answer_text": "; ".join(answers),
            "answers": answers,
            "answer_entity_ids": answer_ids,
            "topic_entity_ids": topic_ids,
            "topic_names": topic_names,
            "relation_path": relation_path,
            "traversal_directions": traversal_directions,
            "gold_edge_ids": gold_eids,
            "gold_paths": gold_paths,
            "evidence_edges": ev_edges,
            "evidence": ev_items,
            "review_status": "auto_generated",
        }

    # 1. SINGLE_HOP & LIST (Forward + Reverse từ các nhóm (node, relation))
    for (u_id, rel) in sorted(out_by_node_rel.keys()):
        u_node = export_nodes_by_id.get(u_id, {})
        u_name = u_node.get("canonical_name", "")
        if not _is_valid_entity_name(u_name) or degree[u_id] > 40:
            continue
        group_edges = sorted(out_by_node_rel[(u_id, rel)], key=lambda x: x["edge_id"])
        ans_pairs: list[tuple[str, str]] = []
        seen_ans: set[str] = set()
        for e in group_edges:
            t_id = e["target_id"]
            t_name = export_nodes_by_id.get(t_id, {}).get("canonical_name", "")
            if t_id not in seen_ans and _is_valid_entity_name(t_name, allow_short_value=True):
                seen_ans.add(t_id)
                ans_pairs.append((t_id, e["edge_id"]))
        if not ans_pairs:
            continue
        seed_ctr += 1
        if len(ans_pairs) == 1:
            t_id, e_id = ans_pairs[0]
            t_node = export_nodes_by_id[t_id]
            t_hint = _kind_semantic_hint(t_node["type"])
            rel_norm = normal(clean_rel_name(rel) or rel)
            if any(x in rel_norm for x in ("dưới triều", "dưới thời", "triều vua", "đời vua")) and "nhân vật" in normal(t_hint):
                q_txt = f"{u_name} {_natural_predicate_tail(rel, t_node['type'])}"
            else:
                q_txt = synthesize_1hop_natural_question(
                    u_name, rel, t_node["canonical_name"], t_hint, idx_seed=seed_ctr
                )
            if not _no_answer_leak(q_txt, [u_name], [t_node["canonical_name"]]):
                q_txt = f"{u_name} {_natural_predicate_tail(rel, t_node['type'])}"
            rec = _build_record(
                question=q_txt,
                question_type="single_hop",
                topic_ids=[u_id],
                answer_ids=[t_id],
                relation_path=[rel],
                traversal_directions=["forward"],
                gold_paths=[[e_id]],
            )
            if rec:
                single_hop_candidates.append(rec)
        elif 2 <= len(ans_pairs) <= 12:
            ans_ids = [p[0] for p in ans_pairs]
            ans_kinds = [_kind_semantic_hint(export_nodes_by_id[aid]["type"]) for aid in ans_ids]
            q_txt = synthesize_list_question(u_name, rel, "forward", ans_kinds, idx_seed=seed_ctr)
            rec = _build_record(
                question=q_txt,
                question_type="list",
                topic_ids=[u_id],
                answer_ids=ans_ids,
                relation_path=[rel],
                traversal_directions=["forward"],
                gold_paths=[[p[1]] for p in ans_pairs],
            )
            if rec:
                list_candidates.append(rec)

    for (v_id, rel) in sorted(in_by_node_rel.keys()):
        v_node = export_nodes_by_id.get(v_id, {})
        v_name = v_node.get("canonical_name", "")
        if not _is_valid_entity_name(v_name) or degree[v_id] > 40:
            continue
        group_edges = sorted(in_by_node_rel[(v_id, rel)], key=lambda x: x["edge_id"])
        src_pairs: list[tuple[str, str]] = []
        seen_src: set[str] = set()
        for e in group_edges:
            s_id = e["source_id"]
            s_name = export_nodes_by_id.get(s_id, {}).get("canonical_name", "")
            if s_id not in seen_src and _is_valid_entity_name(s_name):
                seen_src.add(s_id)
                src_pairs.append((s_id, e["edge_id"]))
        if not src_pairs:
            continue
        seed_ctr += 1
        if len(src_pairs) == 1:
            s_id, e_id = src_pairs[0]
            s_node = export_nodes_by_id[s_id]
            s_hint = _kind_semantic_hint(s_node["type"])
            q_txt = synthesize_1hop_inverse_question(
                s_node["canonical_name"], rel, v_name, s_hint, idx_seed=seed_ctr
            )
            if not _no_answer_leak(q_txt, [v_name], [s_node["canonical_name"]]):
                noun_hint = _infer_plural_noun_from_kind([s_hint])
                rel_c = clean_rel_name(rel) or rel
                q_txt = f"Những {noun_hint} nào {rel_c} {v_name}?"
            rec = _build_record(
                question=q_txt,
                question_type="single_hop",
                topic_ids=[v_id],
                answer_ids=[s_id],
                relation_path=[rel],
                traversal_directions=["reverse"],
                gold_paths=[[e_id]],
            )
            if rec:
                single_hop_candidates.append(rec)
        elif 2 <= len(src_pairs) <= 12:
            ans_ids = [p[0] for p in src_pairs]
            ans_kinds = [_kind_semantic_hint(export_nodes_by_id[aid]["type"]) for aid in ans_ids]
            q_txt = synthesize_list_question(v_name, rel, "reverse", ans_kinds, idx_seed=seed_ctr)
            rec = _build_record(
                question=q_txt,
                question_type="list",
                topic_ids=[v_id],
                answer_ids=ans_ids,
                relation_path=[rel],
                traversal_directions=["reverse"],
                gold_paths=[[p[1]] for p in src_pairs],
            )
            if rec:
                list_candidates.append(rec)

    # 2. MULTI_HOP: ["forward", "forward"] & ["reverse", "forward"]
    fwd_fwd_groups: dict[tuple[str, str, str], list[tuple[str, str, str, str]]] = collections.defaultdict(list)
    for e1 in export_edges:
        u_id, b_id, r1 = e1["source_id"], e1["target_id"], e1["relation"]
        if u_id == b_id or degree[b_id] > 25 or degree[u_id] > 35:
            continue
        u_name = export_nodes_by_id[u_id]["canonical_name"]
        b_node = export_nodes_by_id[b_id]
        if not _is_valid_entity_name(u_name) or not _is_valid_entity_name(b_node["canonical_name"]):
            continue
        for e2 in out_by_node.get(b_id, ()):
            c_id, r2 = e2["target_id"], e2["relation"]
            if c_id in (u_id, b_id) or r1 == r2:
                continue
            c_name = export_nodes_by_id[c_id]["canonical_name"]
            if not _is_valid_entity_name(c_name, allow_short_value=True):
                continue
            fwd_fwd_groups[(u_id, r1, r2)].append((b_id, c_id, e1["edge_id"], e2["edge_id"]))

    rev_fwd_groups: dict[tuple[str, str, str], list[tuple[str, str, str, str]]] = collections.defaultdict(list)
    for e1 in export_edges:
        # bridge -[r1]-> topic(u) (duyệt reverse từ u qua r1 tới b) & bridge -[r2]-> c
        b_id, u_id, r1 = e1["source_id"], e1["target_id"], e1["relation"]
        if u_id == b_id or degree[b_id] > 25 or degree[u_id] > 35:
            continue
        u_name = export_nodes_by_id[u_id]["canonical_name"]
        b_node = export_nodes_by_id[b_id]
        if not _is_valid_entity_name(u_name) or not _is_valid_entity_name(b_node["canonical_name"]):
            continue
        for e2 in out_by_node.get(b_id, ()):
            c_id, r2 = e2["target_id"], e2["relation"]
            if c_id in (u_id, b_id) or r1 == r2 or e2["edge_id"] == e1["edge_id"]:
                continue
            c_name = export_nodes_by_id[c_id]["canonical_name"]
            if not _is_valid_entity_name(c_name, allow_short_value=True):
                continue
            rev_fwd_groups[(u_id, r1, r2)].append((b_id, c_id, e1["edge_id"], e2["edge_id"]))

    def _emit_2hop_group(
        group_key: tuple[str, str, str],
        matches: list[tuple[str, str, str, str]],
        direction_mode: str,
    ) -> dict[str, Any] | None:
        nonlocal seed_ctr
        u_id, r1, r2 = group_key
        unique_ans_ids: list[str] = []
        seen_c: set[str] = set()
        gold_paths: list[list[str]] = []
        for _b_id, c_id, eid1, eid2 in sorted(matches, key=lambda x: (x[2], x[3])):
            if c_id not in seen_c:
                seen_c.add(c_id)
                unique_ans_ids.append(c_id)
            gold_paths.append([eid1, eid2])
        if not unique_ans_ids or len(unique_ans_ids) > 4:
            return None
        b_rep, c_rep, _, _ = matches[0]
        u_node = export_nodes_by_id[u_id]
        b_node = export_nodes_by_id[b_rep]
        c_node = export_nodes_by_id[c_rep]
        seed_ctr += 1
        if direction_mode == "fwd_fwd":
            q_txt = synthesize_2hop_bridge_question(
                u_node["canonical_name"],
                r1,
                b_node["canonical_name"],
                _kind_semantic_hint(b_node["type"]),
                r2,
                c_node["canonical_name"],
                _kind_semantic_hint(c_node["type"]),
                idx_seed=seed_ctr,
            )
            dirs = ["forward", "forward"]
        else:
            q_txt = synthesize_2hop_rev_fwd_question(
                u_node["canonical_name"],
                u_node["type"],
                r1,
                b_node["canonical_name"],
                b_node["type"],
                r2,
                c_node["canonical_name"],
                c_node["type"],
                idx_seed=seed_ctr,
            )
            dirs = ["reverse", "forward"]
        return _build_record(
            question=q_txt,
            question_type="multi_hop",
            topic_ids=[u_id],
            answer_ids=unique_ans_ids,
            relation_path=[r1, r2],
            traversal_directions=dirs,
            gold_paths=gold_paths,
        )

    # Ưu tiên câu 2-hop 1 đáp án duy nhất trước rồi xen kẽ fwd+fwd và rev+fwd
    fwd_items = sorted(fwd_fwd_groups.items(), key=lambda kv: (len({m[1] for m in kv[1]}), kv[0]))
    rev_items = sorted(rev_fwd_groups.items(), key=lambda kv: (len({m[1] for m in kv[1]}), kv[0]))
    for idx in range(max(len(fwd_items), len(rev_items))):
        if idx < len(fwd_items):
            rec = _emit_2hop_group(fwd_items[idx][0], fwd_items[idx][1], "fwd_fwd")
            if rec:
                multi_hop_candidates.append(rec)
        if idx < len(rev_items):
            rec = _emit_2hop_group(rev_items[idx][0], rev_items[idx][1], "rev_fwd")
            if rec:
                multi_hop_candidates.append(rec)

    # 3. Cân bằng tỷ lệ (~45% single_hop, ~35% multi_hop, ~20% list) + bù thiếu xác định
    q_multi = max(1 if multi_hop_candidates else 0, round(max_samples * 0.35))
    q_list = max(1 if list_candidates else 0, round(max_samples * 0.20))
    q_single = max(0, max_samples - q_multi - q_list)

    selected: list[dict[str, Any]] = []
    seen_q_texts: set[str] = set()

    def _take(pool: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for item in pool:
            if len(kept) >= limit:
                break
            qn = normal(item["question"])
            if qn in seen_q_texts:
                continue
            seen_q_texts.add(qn)
            kept.append(item)
        return kept

    selected.extend(_take(single_hop_candidates, q_single))
    selected.extend(_take(multi_hop_candidates, q_multi))
    selected.extend(_take(list_candidates, q_list))

    if len(selected) < max_samples:
        for pool in (single_hop_candidates, multi_hop_candidates, list_candidates):
            if len(selected) >= max_samples:
                break
            selected.extend(_take(pool, max_samples - len(selected)))

    for idx, rec in enumerate(selected, 1):
        rec["question_id"] = f"Q_{idx:06d}"
    return selected


def _csv_bom_bytes(rows: list[dict[str, Any]], fieldnames: list[str]) -> bytes:
    import csv

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _serialize_question_row(rec: dict[str, Any]) -> dict[str, str]:
    """Chuyển bản ghi câu hỏi nội bộ thành đúng 14 cột chuỗi/JSON cho questions.csv."""
    return {
        "question_id": str(rec["question_id"]),
        "question": str(rec["question"]),
        "question_type": str(rec["question_type"]),
        "answer_text": str(rec["answer_text"]),
        "answers": json.dumps(rec["answers"], ensure_ascii=False),
        "answer_entity_ids": json.dumps(rec["answer_entity_ids"], ensure_ascii=False),
        "topic_entity_ids": json.dumps(rec["topic_entity_ids"], ensure_ascii=False),
        "relation_path": json.dumps(rec["relation_path"], ensure_ascii=False),
        "traversal_directions": json.dumps(rec["traversal_directions"], ensure_ascii=False),
        "gold_edge_ids": json.dumps(rec["gold_edge_ids"], ensure_ascii=False),
        "gold_paths": json.dumps(rec["gold_paths"], ensure_ascii=False),
        "evidence_edges": json.dumps(rec["evidence_edges"], ensure_ascii=False),
        "evidence": json.dumps(rec["evidence"], ensure_ascii=False),
        "review_status": str(rec.get("review_status") or "auto_generated"),
    }


def _pack_5_file_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in ("nodes.csv", "edges.csv", "evidence.csv", "questions.csv", "schema_contract.json"):
            if fname in files:
                zf.writestr(fname, files[fname])
    return buf.getvalue()


def rebuild_kgqa_bundle_files(bundle: dict[str, Any]) -> dict[str, Any]:
    """Tái tạo bytes của questions.csv, file ZIP 5 tệp và stats từ question_records hiện tại."""
    records = list(bundle.get("question_records") or [])
    q_rows = [_serialize_question_row(r) for r in records]
    files = dict(bundle.get("files") or {})
    files["questions.csv"] = _csv_bom_bytes(q_rows, QUESTIONS_CSV_HEADERS)

    counts = collections.Counter(str(r.get("question_type", "")) for r in records)
    paraphrased_count = sum(1 for r in records if str(r.get("review_status", "")) == "llm_paraphrased")
    stats = dict(bundle.get("stats") or {})
    stats.update(
        {
            "questions_count": len(records),
            "single_hop_count": int(counts.get("single_hop", 0)),
            "multi_hop_count": int(counts.get("multi_hop", 0)),
            "list_count": int(counts.get("list", 0)),
            "llm_paraphrased_count": paraphrased_count,
        }
    )

    out = dict(bundle)
    out["questions"] = q_rows
    out["files"] = files
    out["zip_bytes"] = _pack_5_file_zip(files)
    out["stats"] = stats
    return out


def _extract_paraphrase_text(raw_val: Any) -> str:
    """Bóc chuỗi câu hỏi sạch kể cả khi LLM trả về dict hoặc chuỗi đại diện của dict."""
    if isinstance(raw_val, dict):
        return str(raw_val.get("question") or raw_val.get("text") or "").strip()
    text = str(raw_val or "").strip()
    if text.startswith("{") and text.endswith("}"):
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(text)
                if isinstance(parsed, dict) and parsed.get("question"):
                    return str(parsed["question"]).strip()
            except Exception:
                continue
    return text


def apply_paraphrased_kgqa_results(
    bundle: dict[str, Any],
    paraphrased_items: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Áp dụng câu hỏi đã paraphrase sau khi hậu kiểm giữ thực thể hạt giống và chống lộ đáp án."""
    records = copy.deepcopy(list(bundle.get("question_records") or []))
    by_qid = {str(item.get("question_id") or item.get("id") or ""): item for item in paraphrased_items if isinstance(item, dict)}

    stats = {
        "attempted": 0,
        "accepted": 0,
        "rejected_entity_drop": 0,
        "rejected_answer_leak": 0,
        "rejected_robotic": 0,
        "rejected_unchanged": 0,
        "rejected_duplicate": 0,
    }
    seen_texts: set[str] = {normal(r["question"]) for r in records}

    for rec in records:
        qid = str(rec["question_id"])
        cand_item = by_qid.get(qid)
        if not cand_item:
            continue
        stats["attempted"] += 1
        orig_q = str(rec.get("original_question") or rec["question"])
        raw_cand = _extract_paraphrase_text(cand_item.get("question", ""))
        cand_q = _clean_natural_question_text(raw_cand)

        if not cand_q or normal(cand_q) == normal(orig_q):
            stats["rejected_unchanged"] += 1
            continue

        cand_norm = normal(cand_q)
        orig_norm = normal(orig_q)
        if any(ban in cand_norm for ban in _BANNED_QA_FRAGMENTS):
            stats["rejected_robotic"] += 1
            continue

        topic_names = list(rec.get("topic_names") or [])
        if not all(normal(tn) in cand_norm for tn in topic_names if normal(tn) and normal(tn) in orig_norm):
            stats["rejected_entity_drop"] += 1
            continue

        if not _no_answer_leak(cand_q, topic_names, list(rec.get("answers") or [])):
            stats["rejected_answer_leak"] += 1
            continue

        if cand_norm in seen_texts:
            stats["rejected_duplicate"] += 1
            continue

        seen_texts.discard(normal(rec["question"]))
        seen_texts.add(cand_norm)
        rec["question"] = cand_q
        rec["original_question"] = orig_q
        rec["review_status"] = "llm_paraphrased"
        stats["accepted"] += 1

    updated = dict(bundle)
    updated["question_records"] = records
    updated = rebuild_kgqa_bundle_files(updated)
    updated["paraphrase_stats"] = stats
    return updated, stats


def build_kgqa_training_bundle(
    project: dict[str, Any],
    *,
    approved_only: bool = True,
    max_samples: int = 500,
) -> dict[str, Any]:
    """Đóng gói toàn bộ Bộ Dữ liệu Huấn luyện Chuẩn G-Retriever 5 tệp từ đồ thị dự án."""
    from backend.domain.graph.service import approved_graph

    if approved_only:
        nodes, edges = approved_graph(project)
    else:
        nodes = list(project.get("nodes") or [])
        edges = list(project.get("edges") or [])

    (
        export_nodes,
        export_edges,
        export_evidence,
        _orig_to_export_nid,
        export_nodes_by_id,
        _export_edges_by_id,
    ) = _extract_tables(project, nodes, edges)

    evidence_by_id = {row["evidence_id"]: row for row in export_evidence}
    schema_contract = build_kgqa_schema_contract(project, export_nodes, export_edges)
    question_records = generate_gretriever_kgqa_questions(
        export_nodes_by_id,
        export_edges,
        evidence_by_id,
        max_samples=max_samples,
    )

    clean_edges = [
        {k: row[k] for k in EDGES_CSV_HEADERS}
        for row in export_edges
    ]

    files: dict[str, bytes] = {
        "nodes.csv": _csv_bom_bytes(export_nodes, NODES_CSV_HEADERS),
        "edges.csv": _csv_bom_bytes(clean_edges, EDGES_CSV_HEADERS),
        "evidence.csv": _csv_bom_bytes(export_evidence, EVIDENCE_CSV_HEADERS),
        "questions.csv": b"",
        "schema_contract.json": json.dumps(schema_contract, ensure_ascii=False, indent=2).encode("utf-8"),
    }

    bundle: dict[str, Any] = {
        "nodes": export_nodes,
        "edges": clean_edges,
        "evidence": export_evidence,
        "question_records": question_records,
        "questions": [],
        "schema_contract": schema_contract,
        "files": files,
        "zip_bytes": b"",
        "stats": {
            "nodes_count": len(export_nodes),
            "edges_count": len(clean_edges),
            "evidence_count": len(export_evidence),
            "approved_only": bool(approved_only),
        },
    }
    return rebuild_kgqa_bundle_files(bundle)
