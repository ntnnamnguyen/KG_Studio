"""Module Semantic Clustering: Quét và gom cụm ngữ nghĩa thông minh bằng LLM (DeepSeek) cho Quan hệ và Kiểu Thực thể."""
from __future__ import annotations

import copy
from collections import Counter
from typing import Any

from backend.domain.curation.merge import (
    bulk_apply_relation_merges,
    clear_duplicate_suggestions_cache,
    clear_relation_duplicate_suggestions_cache,
    collapse_duplicate_edges,
)
from backend.domain.curation.merge_core import (
    _clone_project_for_merge_mutation,
    flatten_redirects,
    remap_graph_edges_endpoints,
)
from shared.constants import STATUS_REJECTED
from backend.domain.catalogs.service import compute_project_revision
from backend.integrations.llm import LLMGateway, providers
from backend.integrations.llm.clients import make_adapter
from shared.text_utils import clean_relation_name


def canonical_key(text: str) -> str:
    """Tạo khóa chuẩn hóa không phân biệt hoa thường, không dấu tiếng Việt, quy đổi dấu gạch dưới/nối thành khoảng trắng."""
    import re
    import unicodedata

    t = str(text or "")
    t = t.replace("đ", "d").replace("Đ", "d")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[_\-\s]+", " ", t).strip().lower()
    return t


def _parse_clusters_json(text: str) -> dict:
    """Parse JSON kết quả gom cụm từ LLM an toàn, hỗ trợ markdown fences, JSON trailing commas, và regex trích xuất cụm khi JSON bị cắt cụt (truncated)."""
    import json
    import re

    raw = (text or "").strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.IGNORECASE)
    cleaned = fence_match.group(1).strip() if fence_match else raw

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and "clusters" in data:
            return data
        if isinstance(data, list):
            return {"clusters": data}
    except Exception:
        pass

    start_brace = cleaned.find("{")
    end_brace = cleaned.rfind("}")
    if start_brace >= 0 and end_brace > start_brace:
        snippet = cleaned[start_brace : end_brace + 1]
        try:
            fixed = re.sub(r",\s*([\]}])", r"\1", snippet)
            data = json.loads(fixed)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    extracted_clusters: list[dict] = []
    obj_pattern = re.compile(
        r'\{\s*"canonical_name"\s*:\s*"([^"]+)"\s*,\s*"synonyms"\s*:\s*\[([^\]]*)\](?:\s*,\s*"reason"\s*:\s*"([^"]*)")?\s*\}',
        re.DOTALL,
    )
    for m in obj_pattern.finditer(cleaned):
        canon = m.group(1).strip()
        syn_raw = m.group(2)
        reason = (m.group(3) or "").strip()
        syns = [
            s.strip().strip('"').strip("'")
            for s in syn_raw.split(",")
            if s.strip().strip('"').strip("'")
        ]
        if canon and syns:
            extracted_clusters.append(
                {
                    "canonical_name": canon,
                    "synonyms": syns,
                    "reason": reason or "Tương đương ngữ nghĩa trong tiếng Việt",
                }
            )

    if extracted_clusters:
        return {"clusters": extracted_clusters}

    return {"clusters": []}
from shared.catalog_utils import relation_catalog
from shared.constants import STATUS_REJECTED
from shared.schemas.curation import CurationResultDTO
from shared.text_utils import normal, now_iso, uid


def collect_cluster_items(
    project: dict,
    kind: str = "relations",
    scope: str = "all",
) -> list[dict[str, Any]]:
    """Thu thập toàn bộ các mục quan hệ hoặc loại thực thể hiện có trên đồ thị và danh mục kèm ngữ cảnh."""
    items: list[dict[str, Any]] = []

    if kind == "relations":
        edges = project.get("edges", [])
        edge_counts = Counter(
            str(e.get("relation", "")).strip()
            for e in edges
            if e.get("relation") and e.get("status") != STATUS_REJECTED
        )
        sample_evidences: dict[str, list[str]] = {}
        sample_triples: dict[str, list[str]] = {}
        for e in edges:
            r = str(e.get("relation", "")).strip()
            if not r or e.get("status") == STATUS_REJECTED:
                continue
            ev = str(e.get("evidence") or "").strip()
            if ev and len(sample_evidences.setdefault(r, [])) < 2 and ev not in sample_evidences[r]:
                sample_evidences[r].append(ev)
            s, t = str(e.get("source", "")).strip(), str(e.get("target", "")).strip()
            if s and t and len(sample_triples.setdefault(r, [])) < 2:
                trip_str = f"({s} -> {r} -> {t})"
                if trip_str not in sample_triples[r]:
                    sample_triples[r].append(trip_str)

        catalog_entries = {
            str(r.get("name", "")).strip(): r
            for r in relation_catalog(project)
            if r.get("name")
        }

        all_names = sorted(set(edge_counts.keys()) | set(catalog_entries.keys()))
        redirects = project.get("relation_redirects", {})
        active_names = [n for n in all_names if n and n not in redirects]

        for name in active_names:
            cat_item = catalog_entries.get(name, {})
            defn = str(cat_item.get("definition") or cat_item.get("description") or "").strip()
            aliases = list(cat_item.get("aliases") or project.get("relation_aliases", {}).get(name, []))
            items.append(
                {
                    "name": name,
                    "count": edge_counts.get(name, 0),
                    "in_catalog": name in catalog_entries,
                    "definition": defn,
                    "aliases": aliases,
                    "sample_evidences": sample_evidences.get(name, []),
                    "sample_triples": sample_triples.get(name, []),
                }
            )
        items.sort(key=lambda x: (-x["count"], not x["in_catalog"], x["name"]))

    elif kind == "entity_types":
        nodes = project.get("nodes", [])
        kind_counts = Counter(
            str(n.get("kind", "")).strip()
            for n in nodes
            if n.get("kind")
        )
        sample_nodes: dict[str, list[str]] = {}
        for n in nodes:
            k = str(n.get("kind", "")).strip()
            name = str(n.get("name", "")).strip()
            if k and name and len(sample_nodes.setdefault(k, [])) < 4 and name not in sample_nodes[k]:
                sample_nodes[k].append(name)

        catalog_entries = {
            str(t.get("name", "")).strip(): t
            for t in project.get("entity_types", [])
            if isinstance(t, dict) and t.get("name")
        }

        all_kinds = sorted(set(kind_counts.keys()) | set(catalog_entries.keys()))
        for k in all_kinds:
            if not k:
                continue
            cat_item = catalog_entries.get(k, {})
            defn = str(cat_item.get("definition") or cat_item.get("description") or "").strip()
            aliases = list(cat_item.get("aliases") or project.get("entity_type_aliases", {}).get(k, []))
            items.append(
                {
                    "name": k,
                    "count": kind_counts.get(k, 0),
                    "in_catalog": k in catalog_entries,
                    "definition": defn,
                    "aliases": aliases,
                    "sample_nodes": sample_nodes.get(k, []),
                }
            )
        items.sort(key=lambda x: (-x["count"], not x["in_catalog"], x["name"]))

    if scope == "top_50":
        items = items[:50]
    elif scope == "top_60":
        items = items[:60]
    elif scope == "top_100":
        items = items[:100]
    elif scope == "freq_ge_2":
        items = [it for it in items if it["count"] >= 2 or it.get("in_catalog")]

    return items


def build_clustering_prompt(
    items: list[dict[str, Any]],
    kind: str = "relations",
    custom_instructions: str = "",
) -> str:
    """Tạo prompt chuẩn hóa Ontology cho LLM DeepSeek với hướng dẫn tiếng Việt chuyên sâu và chỉ dẫn tùy chỉnh."""
    lines: list[str] = []
    kind_label = "quan hệ" if kind == "relations" else "loại thực thể"
    is_compact = len(items) > 30

    if kind == "relations":
        for idx, it in enumerate(items, 1):
            cat_tag = " [ĐÃ CÓ TRONG LƯỢC ĐỒ CHUẨN]" if it.get("in_catalog") else ""
            line = f"{idx}. '{it['name']}' ({it['count']} cạnh){cat_tag}"
            if it.get("definition"):
                line += f"\n   - Định nghĩa: {it['definition']}"
            if it.get("aliases"):
                line += f"\n   - Biến thể/Aliases đã biết: {', '.join(it['aliases'])}"
            if it.get("sample_triples"):
                line += f"\n   - Bộ ba mẫu: {it['sample_triples'][0]}"
            if not is_compact and it.get("sample_evidences"):
                ev = it["sample_evidences"][0]
                if len(ev) > 120:
                    ev = ev[:117] + "..."
                line += f"\n   - Đoạn văn mẫu: \"{ev}\""
            lines.append(line)
    else:
        for idx, it in enumerate(items, 1):
            cat_tag = " [ĐÃ CÓ TRONG LƯỢC ĐỒ CHUẨN]" if it.get("in_catalog") else ""
            line = f"{idx}. '{it['name']}' ({it['count']} thực thể){cat_tag}"
            if it.get("definition"):
                line += f"\n   - Định nghĩa: {it['definition']}"
            if it.get("sample_nodes"):
                line += f"\n   - Thực thể tiêu biểu: {', '.join(it['sample_nodes'][:3])}"
            lines.append(line)

    items_block = "\n".join(lines)

    custom_block = ""
    if custom_instructions and custom_instructions.strip():
        custom_block = f"""
CHỈ DẪN & QUY TẮC ĐẶC BIỆT CỦA CHUYÊN GIA (Ưu tiên tuân thủ nghiêm ngặt):
{custom_instructions.strip()}
"""

    return f"""Bạn là một chuyên gia chuẩn hóa Ontology và Đồ thị Tri thức (Knowledge Graph Canonicalization) tiếng Việt hàng đầu.
Dưới đây là danh sách các {kind_label} đang có trong dữ liệu đồ thị tri thức kèm tần suất và ngữ cảnh:

{items_block}

NHIỆM VỤ CỦA BẠN:
1. Phân tích ngữ nghĩa ngữ cảnh tiếng Việt để phát hiện các nhóm {kind_label} mang ý nghĩa tương đương nhau, từ đồng nghĩa hoặc các cách diễn đạt biến thể của cùng một khái niệm (ví dụ: 'tọa lạc tại', 'nằm ở', 'thuộc địa phận' -> tương đương 'nằm tại'; hoặc 'di tích lịch sử', 'di tích văn hóa' -> 'di tích').
2. Đối với mỗi nhóm tìm thấy:
   - "canonical_name": Chọn 1 tên chuẩn hóa đại diện duy nhất.
     * QUY TẮC: Ưu tiên chọn mục có đánh dấu [ĐÃ CÓ TRONG LƯỢC ĐỒ CHUẨN] nếu phù hợp. Nếu không, chọn tên ngắn gọn, chuẩn mực, viết bằng tiếng Việt tự nhiên có dấu, dùng khoảng trắng, chữ thường. TUYỆT ĐỐI KHÔNG dùng dấu gạch dưới (_), không dùng từ nối/giới từ rườm rà ở cuối (như "của", "về", "là", "cho"). Ví dụ: chọn "cần sự đồng ý" thay vì "cần_sự_đồng_ý_của"; "giới thiệu" thay vì "giới_thiệu_về".
   - "synonyms": Danh sách các tên biến thể/từ đồng nghĩa cần gộp về canonical_name.
     * QUY TẮC: CHỈ được lấy các tên có mặt trong danh sách đánh số ở trên. KHÔNG tự bịa tên mới. KHÔNG đưa canonical_name vào danh sách synonyms này.
   - "reason": Nêu lý do ngữ nghĩa ngắn gọn (tối đa 1-2 câu) giải thích vì sao các mục này tương đương ngữ nghĩa trong tiếng Việt.
3. Các {kind_label} độc lập (không có biến thể nào tương đương trong danh sách) thì TUYỆT ĐỐI KHÔNG đưa vào kết quả.
{custom_block}
YÊU CẦU ĐẦU RA:
- CHỈ trả về duy nhất một chuỗi JSON hợp lệ, không có markdown phụ họa ngoài JSON, theo đúng cấu trúc sau:
{{
  "clusters": [
    {{
      "canonical_name": "tên_chuẩn",
      "synonyms": ["tên_biến_thể_1", "tên_biến_thể_2"],
      "reason": "Lý giải ngắn gọn tính tương đương ngữ nghĩa"
    }}
  ]
}}"""


def preview_clustering_prompt(
    project: dict,
    kind: str = "relations",
    custom_instructions: str = "",
    scope: str = "top_60",
) -> str:
    """Tạo bản xem trước toàn bộ Prompt sẽ gửi tới LLM cho người dùng kiểm tra hoặc tinh chỉnh."""
    items = collect_cluster_items(project, kind, scope=scope)
    return build_clustering_prompt(items, kind=kind, custom_instructions=custom_instructions)


def scan_semantic_clusters(
    project: dict,
    kind: str = "relations",
    *,
    scope: str = "top_60",
    provider: str = "DeepSeek",
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    client: Any = None,
    custom_instructions: str = "",
    prompt_override: str = "",
) -> dict[str, Any]:
    """Quét và gợi ý gom cụm ngữ nghĩa thông minh qua LLM (DeepSeek / provider cấu hình)."""
    items = collect_cluster_items(project, kind, scope=scope)
    if len(items) < 2:
        return {
            "kind": kind,
            "scope": scope,
            "scanned_items_count": len(items),
            "clusters_count": 0,
            "clusters": [],
            "used_prompt": "",
            "custom_instructions": custom_instructions,
            "raw_response": "",
            "message": f"Số lượng {kind} hiện tại ({len(items)}) quá ít để tiến hành gom cụm.",
        }

    p_spec = providers.provider_spec(provider)
    resolved_model = model or p_spec.default_model or ("deepseek-chat" if "deepseek" in provider.lower() else "gpt-4o-mini")
    resolved_base_url = providers.resolve_base_url(provider, base_url)

    if p_spec.requires_api_key and not api_key:
        raise ValueError(
            f"Chưa cung cấp API Key cho {p_spec.name}. Vui lòng nhập API Key để thực hiện gom cụm bằng AI."
        )

    if prompt_override and prompt_override.strip():
        user_prompt = prompt_override.strip()
    else:
        user_prompt = build_clustering_prompt(items, kind, custom_instructions=custom_instructions)
    system_prompt = (
        "Bạn là trợ lý AI chuyên gia chuẩn hóa ontology và đồ thị tri thức tiếng Việt. "
        "Luôn phân tích sâu sắc ngữ nghĩa tiếng Việt và chỉ trả về JSON hợp lệ theo yêu cầu."
    )

    adapter = make_adapter(
        p_spec,
        api_key,
        resolved_base_url,
        client=client,
        timeout=120.0,
    )

    resp = adapter.chat(
        model=resolved_model,
        user=user_prompt,
        system=system_prompt,
        temperature=0.0,
        max_tokens=4096,
        response_format={"type": "json_object"} if p_spec.supports_json_mode else None,
    )

    parsed = _parse_clusters_json(resp.content)
    raw_clusters = parsed.get("clusters", []) if isinstance(parsed, dict) else []

    item_name_set = {it["name"] for it in items}
    item_by_norm = {normal(it["name"]): it["name"] for it in items}
    item_by_ckey = {canonical_key(it["name"]): it["name"] for it in items}
    count_map = {it["name"]: it.get("count", 0) for it in items}

    alias_map: dict[str, str] = {}
    for it in items:
        for al in it.get("aliases", []):
            if al and al not in item_name_set:
                alias_map[al] = it["name"]
                alias_map[normal(al)] = it["name"]
                alias_map[canonical_key(al)] = it["name"]

    def resolve_item_name(raw_name: str) -> str | None:
        val = str(raw_name or "").strip()
        if not val:
            return None
        if val in item_name_set:
            return val
        n_val = normal(val)
        if n_val in item_by_norm:
            return item_by_norm[n_val]
        ck_val = canonical_key(val)
        if ck_val in item_by_ckey:
            return item_by_ckey[ck_val]
        if val in alias_map:
            return alias_map[val]
        if n_val in alias_map:
            return alias_map[n_val]
        if ck_val in alias_map:
            return alias_map[ck_val]
        return None

    validated_clusters: list[dict[str, Any]] = []
    seen_sources: set[str] = set()

    for c_idx, raw_c in enumerate(raw_clusters, 1):
        if not isinstance(raw_c, dict):
            continue
        c_target = str(raw_c.get("canonical_name", "")).strip()
        raw_synonyms = raw_c.get("synonyms", [])
        if not c_target or not isinstance(raw_synonyms, list) or not raw_synonyms:
            continue

        c_target_resolved = resolve_item_name(c_target) or (clean_relation_name(c_target) if kind == "relations" else c_target)

        valid_syns: list[str] = []
        for s in raw_synonyms:
            s_clean = str(s).strip()
            if not s_clean:
                continue
            s_resolved = resolve_item_name(s_clean)
            if not s_resolved or s_resolved not in item_name_set:
                continue
            if s_resolved == c_target_resolved:
                continue
            if canonical_key(s_resolved) == canonical_key(c_target_resolved):
                continue
            if s_resolved in seen_sources:
                continue
            valid_syns.append(s_resolved)
            seen_sources.add(s_resolved)

        if not valid_syns:
            continue

        total_affected = sum(count_map.get(s, 0) for s in valid_syns)
        cluster_id = f"cluster_{kind}_{c_idx}_{uid()[:6]}"
        validated_clusters.append(
            {
                "id": cluster_id,
                "canonical_name": c_target_resolved,
                "synonyms": valid_syns,
                "reason": str(raw_c.get("reason", "Tương đương ngữ nghĩa trong tiếng Việt")).strip(),
                "affected_count": total_affected,
                "target_count": count_map.get(c_target_resolved, 0),
            }
        )

    validated_clusters.sort(key=lambda x: -x["affected_count"])

    return {
        "kind": kind,
        "scope": scope,
        "scanned_items_count": len(items),
        "clusters_count": len(validated_clusters),
        "clusters": validated_clusters,
        "used_prompt": user_prompt,
        "custom_instructions": custom_instructions,
        "raw_response": resp.content,
        "tokens": {
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
        },
    }


def bulk_apply_entity_type_merges(
    project: dict,
    mappings: list[dict | tuple[str, str]] | dict[str, str],
    *,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Gộp hàng loạt các loại thực thể (node kind) nghi trùng hoặc tương đương ngữ nghĩa."""
    if not mappings:
        raise ValueError("Danh sách loại thực thể cần gộp trống.")

    candidate = _clone_project_for_merge_mutation(project)
    rev_before = compute_project_revision(candidate)
    batch_id = uid()
    request_id = uid()
    merge_time = now_iso()

    resolved_pairs: list[tuple[str, str]] = []
    items_to_process = list(mappings.items()) if isinstance(mappings, dict) else mappings
    for item in items_to_process:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            s, t = str(item[0]).strip(), str(item[1]).strip()
        elif isinstance(item, dict):
            s = str(item.get("source") or item.get("source_kind") or item.get("synonym") or "").strip()
            t = str(item.get("target") or item.get("target_kind") or item.get("canonical_name") or "").strip()
        else:
            continue
        if s and t and s != t:
            resolved_pairs.append((s, t))

    if not resolved_pairs:
        raise ValueError("Không có cặp loại thực thể hợp lệ để gộp.")

    flat_map = flatten_redirects(resolved_pairs)
    if not flat_map:
        raise ValueError("Không có cặp loại thực thể hợp lệ để gộp.")

    affected_nodes: list[str] = []
    nodes_list = candidate["nodes"]
    for idx, node in enumerate(nodes_list):
        k = str(node.get("kind", "")).strip()
        if k in flat_map:
            new_node = dict(node)
            new_node["original_kind"] = new_node.get("original_kind") or k
            new_node["kind"] = flat_map[k]
            nodes_list[idx] = new_node
            affected_nodes.append(str(new_node.get("id", "")))

    aliases_map = candidate["entity_type_aliases"]
    for s, t in flat_map.items():
        t_aliases = list(aliases_map.get(t, []))
        if s not in t_aliases and normal(s) != normal(t):
            t_aliases.append(s)
        aliases_map[t] = t_aliases

    source_set = set(flat_map.keys())
    type_catalog = candidate["entity_types"]
    candidate["entity_types"] = [
        t for t in type_catalog
        if (t.get("name") if isinstance(t, dict) else str(t)).strip() not in source_set
    ]

    types_by_norm: dict[str, list[dict]] = {}
    for entry in candidate["entity_types"]:
        if isinstance(entry, dict):
            types_by_norm.setdefault(normal(entry.get("name", "")), []).append(entry)

    all_targets = set(flat_map.values())
    for t in all_targets:
        t_aliases = aliases_map.get(t, [])
        t_norm = normal(t)
        matched_entries = types_by_norm.get(t_norm)
        if matched_entries:
            for entry in matched_entries:
                curr_aliases = list(entry.get("aliases") or [])
                curr_set = set(curr_aliases)
                for a in t_aliases:
                    if a not in curr_set and normal(a) != t_norm:
                        curr_aliases.append(a)
                        curr_set.add(a)
                entry["aliases"] = curr_aliases
        else:
            new_et = {
                "name": t,
                "description": f"Loại thực thể chuẩn hóa nạp tự động qua gộp AI",
                "definition": f"Loại thực thể '{t}' gộp từ các biến thể.",
                "aliases": list(t_aliases),
            }
            candidate["entity_types"].append(new_et)
            types_by_norm.setdefault(t_norm, []).append(new_et)

    props_list = candidate["schema_proposals"]
    for idx, p in enumerate(props_list):
        p_name = p.get("name", "")
        if p.get("kind") == "entity_types" and p_name in flat_map:
            new_p = copy.deepcopy(p)
            new_p["status"] = "merged"
            new_p["canonical_name"] = flat_map[p_name]
            new_p["reviewed_at"] = merge_time
            new_p["review_note"] = (str(new_p.get("review_note") or "") + f" [Gộp loại vào '{flat_map[p_name]}']").strip()
            props_list[idx] = new_p

    affected_node_set = {nid for nid in affected_nodes if nid}
    invalidated_approved_count = 0
    invalidated_edge_ids: list[str] = []
    if affected_node_set:
        _, _, _, invalidated_approved_count, _, _ = remap_graph_edges_endpoints(
            candidate["edges"],
            {},
            member_set=affected_node_set,
            kind_changed_by_member={nid: True for nid in affected_node_set},
            merge_time=merge_time,
            actor=actor,
            curation_history=candidate.setdefault("curation_history", []),
            simulate_only=False,
        )
        invalidated_edge_ids = [
            str(e.get("id", ""))
            for e in candidate["edges"]
            if e.get("status") != STATUS_REJECTED
            and (e.get("source") in affected_node_set or e.get("target") in affected_node_set)
        ]

    type_merge_entry = {
        "merge_id": batch_id,
        "request_id": request_id,
        "at": merge_time,
        "actor": actor,
        "is_bulk": True,
        "merged_types_count": len(flat_map),
        "affected_node_count": len(affected_nodes),
        "affected_edge_count": len(invalidated_edge_ids),
        "invalidated_approved_count": invalidated_approved_count,
        "note": note or f"Gộp hàng loạt {len(flat_map)} loại thực thể.",
        "mappings": flat_map,
    }
    candidate.setdefault("entity_type_merges", []).append(type_merge_entry)
    candidate.setdefault("curation_history", []).append(
        {
            "id": batch_id,
            "request_id": request_id,
            "at": merge_time,
            "actor": actor,
            "decision_origin": "human",
            "action": "bulk_entity_type_merge",
            "target_id": f"{len(flat_map)}_entity_types",
            "note": type_merge_entry["note"],
            "after": type_merge_entry,
        }
    )

    rev_after = compute_project_revision(candidate)
    proj_id = str(candidate.get("project_id") or candidate.get("name") or "")
    result = CurationResultDTO(
        batch_id=batch_id,
        request_id=request_id,
        project_id=proj_id,
        operation="bulk_entity_type_merge",
        status="success",
        revision_before=rev_before,
        revision_after=rev_after,
        applied_count=len(flat_map),
        skipped_count=0,
        item_results=[{"source": s, "target": t} for s, t in flat_map.items()],
        affected_edge_ids=invalidated_edge_ids,
        invalidated_approved_count=invalidated_approved_count,
        merged_duplicate_edges=0,
    )

    if mutate_in_place and candidate is not project:
        project.clear()
        project.update(candidate)

    clear_duplicate_suggestions_cache()
    clear_relation_duplicate_suggestions_cache()
    return candidate, result


def apply_semantic_clusters(
    project: dict,
    kind: str,
    approved_clusters: list[dict],
    *,
    collapse_duplicate_edges: bool = True,
    actor: str = "human_reviewer",
    note: str = "",
    mutate_in_place: bool = True,
) -> tuple[dict, CurationResultDTO]:
    """Áp dụng các cụm gom ngữ nghĩa AI vào đồ thị dự án."""
    if not approved_clusters:
        raise ValueError("Danh sách cụm được duyệt trống.")

    mappings: list[tuple[str, str]] = []
    for cl in approved_clusters:
        target = str(cl.get("canonical_name", "")).strip()
        synonyms = cl.get("synonyms", [])
        if not target or not isinstance(synonyms, list):
            continue
        for s in synonyms:
            s_clean = str(s).strip()
            if s_clean and s_clean != target:
                mappings.append((s_clean, target))

    if not mappings:
        raise ValueError("Không có biến thể hợp lệ nào để áp dụng gộp.")

    if kind == "relations":
        return bulk_apply_relation_merges(
            project,
            mappings,
            collapse_edges=collapse_duplicate_edges,
            actor=actor,
            note=note or f"Gom cụm AI cho {len(approved_clusters)} cụm quan hệ.",
            mutate_in_place=mutate_in_place,
        )
    elif kind == "entity_types":
        return bulk_apply_entity_type_merges(
            project,
            mappings,
            actor=actor,
            note=note or f"Gom cụm AI cho {len(approved_clusters)} cụm loại thực thể.",
            mutate_in_place=mutate_in_place,
        )
    else:
        raise ValueError(f"Kind không được hỗ trợ: {kind}")
