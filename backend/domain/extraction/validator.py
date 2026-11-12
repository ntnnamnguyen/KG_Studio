"""Kiểm tra đầu ra LLM và ghi nhận Thực thể / Quan hệ vào dự án (Độc lập 100%)."""
from __future__ import annotations

from backend.domain.catalogs.service import prepare_edc
from backend.domain.curation.common import resolve_active_node_id
from backend.domain.curation.service import doc_fingerprint, evidence_in_chunk
from shared.catalog_utils import validate_edc_payload
from shared.config_loader import CONFIG
from shared.constants import MODE_EDC, MODE_EDC_PLUS_R, STATUS_CHECK, STATUS_PENDING
from shared.text_utils import clean_relation_name, normal, now_iso, sha, uid

UNKNOWN_KIND = CONFIG["knowledge"]["unknown_entity_kind"]
UNKNOWN_KINDS: set[str] = {normal(UNKNOWN_KIND), normal("Chưa xác định"), normal("Chưa phân loại"), "unknown", ""}

# Danh mục các danh từ bộ phận kiến trúc, hiện vật và thực thể yếu (Weak Entities)
# Cần áp dụng Document Scoping để chống gộp nhầm giữa các di tích khác nhau (vd: 'cổng' Đình A vs 'cổng' Đình B).
GENERIC_COMPONENT_TERMS: frozenset[str] = frozenset(
    normal(term)
    for term in (
        "cổng", "cổng đình", "cổng chùa", "cổng đền", "cổng làng",
        "tam quan", "nghi môn", "hậu cung", "tiền đường", "trung đường", "đại đình",
        "tòa tiền tế", "nhà tiền tế", "nhà đại bái", "tòa đại bái", "phương đình", "nhà phương đình",
        "chuông", "chuông đồng", "đại hồng chung", "khánh", "khánh đồng",
        "bia", "bia đá", "nhà bia", "nhà bia tiến sĩ",
        "tượng", "tượng phật", "tượng thánh", "tượng mẫu", "tượng thần",
        "giếng", "giếng ngọc", "giếng làng", "giếng rồng", "ao", "ao làng", "ao chùa", "ao đình",
        "hồ", "hồ bán nguyệt", "sân", "sân đình", "sân chùa", "sân đền",
        "gác chuông", "gác trống", "nhà tổ", "tổ đường", "nhà thờ tổ", "nhà tăng",
        "hương án", "ngai thờ", "bàn thờ", "sắc phong", "hoành phi", "câu đối",
        "tháp", "tháp mộ", "tháp phật", "lăng", "lăng mộ", "mộ", "mộ phần",
    )
)


def is_generic_component_entity(name: str) -> bool:
    """Kiểm tra xem tên thực thể có phải danh từ bộ phận chung / thực thể yếu (Weak Entity) hay không.

    Các thực thể như 'cổng', 'chuông', 'tam quan', 'hậu cung' không mang danh tính độc lập toàn cục
    mà phụ thuộc vào di tích cha trong tài liệu cụ thể.
    """
    clean = normal(name)
    if not clean:
        return False
    if clean in GENERIC_COMPONENT_TERMS:
        return True
    words = clean.split()
    if len(words) == 1 and words[0] in {
        "cong", "chuong", "bia", "tuong", "gieng", "ao", "san", "thap", "mo", "lang", "khanh", "ngai",
    }:
        return True
    return False


def validate_extraction(
    extraction: dict,
    chunk_text: str,
    allowed_relations: list[str],
    *,
    open_mode: bool = False,
) -> tuple[dict, dict]:
    if not isinstance(extraction, dict):
        raise ValueError("Kết quả trích xuất phải là JSON object")
    entities_in = extraction.get("thuc_the", [])
    relations_in = extraction.get("quan_he", [])
    if not isinstance(entities_in, list) or not isinstance(relations_in, list):
        raise ValueError("thuc_the và quan_he phải là danh sách")

    report = {
        "invalid_entities": 0,
        "invalid_relations": 0,
        "disallowed_relations": [],
        "evidence_mismatch": 0,
        "added_endpoints": 0,
        "duplicate_entities": 0,
        "rejected_items": [],
    }

    entities: list[dict] = []
    known: dict[str, dict] = {}
    for item in entities_in:
        if not isinstance(item, dict):
            report["invalid_entities"] += 1
            continue
        name = str(item.get("ten") or "").strip()
        if not name:
            report["invalid_entities"] += 1
            continue
        kind = str(item.get("loai") or "").strip() or UNKNOWN_KIND
        description = str(item.get("mo_ta") or "").strip()
        key = normal(name)
        if key in known:
            report["duplicate_entities"] += 1
            if known[key]["loai"] == UNKNOWN_KIND and kind != UNKNOWN_KIND:
                known[key]["loai"] = kind
            if description and not known[key]["mo_ta"]:
                known[key]["mo_ta"] = description
            continue
        entity = {"ten": name, "loai": kind, "mo_ta": description}
        known[key] = entity
        entities.append(entity)

    allowed = {normal(name): name for name in allowed_relations}
    relations: list[dict] = []
    for index, item in enumerate(relations_in, 1):
        if not isinstance(item, dict):
            report["invalid_relations"] += 1
            report["rejected_items"].append({"index": index, "reason": "Quan hệ không phải object", "item": item})
            continue
        source = str(item.get("nguon") or "").strip()
        target = str(item.get("dich") or "").strip()
        relation = str(item.get("quan_he") or "").strip()
        quote = str(item.get("trich_dan") or "").strip()
        if not (source and target and relation and quote):
            report["invalid_relations"] += 1
            report["rejected_items"].append({"index": index, "reason": "Thiếu nguồn, đích, tên quan hệ hoặc trích dẫn", "item": item})
            continue
        cleaned_rel = clean_relation_name(relation) if open_mode else relation
        canonical = allowed.get(normal(relation)) or (allowed.get(normal(cleaned_rel)) if open_mode else None)
        if canonical is None:
            if open_mode:
                canonical = cleaned_rel
            else:
                report["disallowed_relations"].append(relation)
                report["invalid_relations"] += 1
                report["rejected_items"].append({"index": index, "reason": "Ngoài danh mục quan hệ", "item": item})
                continue
        if not canonical:
            report["invalid_relations"] += 1
            report["rejected_items"].append({"index": index, "reason": "Tên quan hệ rỗng sau chuẩn hóa", "item": item})
            continue
        for endpoint in (source, target):
            key = normal(endpoint)
            if key not in known:
                entity = {"ten": endpoint, "loai": UNKNOWN_KIND, "mo_ta": ""}
                known[key] = entity
                entities.append(entity)
                report["added_endpoints"] += 1
        verified = evidence_in_chunk(quote, chunk_text)
        if not verified:
            report["evidence_mismatch"] += 1
        relations.append(
            {
                "nguon": source,
                "quan_he": canonical,
                "dich": target,
                "trich_dan": quote,
                "evidence_found": verified,
                "status": STATUS_PENDING if verified else STATUS_CHECK,
            }
        )
    return {"thuc_the": entities, "quan_he": relations}, report


def ensure_node(
    project: dict,
    name: str,
    kind: str = UNKNOWN_KIND,
    description: str = "",
    doc_id: str = "",
    *,
    strict_kind: bool = False,
) -> str:
    name = str(name or "").strip()
    kind = str(kind or "").strip() or UNKNOWN_KIND
    description = str(description or "").strip()
    doc_id = str(doc_id or "").strip()
    if not name:
        return ""

    n_name = normal(name)
    n_kind = normal(kind)
    is_generic = is_generic_component_entity(name)

    nodes = project.setdefault("nodes", [])

    for node in nodes:
        # 1. So khớp danh tính qua Tên chính hoặc bất kỳ Bí danh (alias) nào
        node_name_norm = normal(node.get("name", ""))
        alias_norms = {normal(a) for a in node.get("aliases", []) if a}
        same_identity = (n_name == node_name_norm) or (n_name in alias_norms)
        if not same_identity:
            continue

        # Với thực thể bộ phận chung (Weak Entity như 'cổng', 'chuông', 'tam quan'):
        # Áp dụng Document Scoping: CHỈ khớp nếu cùng xuất hiện trong một tài liệu nguồn (doc_id).
        # Ngăn chặn việc gộp nhầm 'cổng' của Đình A sang 'cổng' của Đình B giữa các tài liệu khác nhau.
        if is_generic and doc_id:
            node_docs = node.get("documents", [])
            if node_docs and doc_id not in node_docs:
                continue

        # 2. Xử lý tính tương thích Loại thực thể (Kind Compatibility):
        # - Khớp nếu cùng loại (normalized)
        # - Khớp nếu một trong hai bên là UNKNOWN_KIND (cho phép liên kết và nâng cấp loại)
        # - Khớp nếu strict_kind = False (chế độ nới lỏng)
        # - CHỈ coi là xung đột khi cả 2 bên ĐỀU có loại cụ thể nhưng khác nhau trong strict_kind
        node_kind = str(node.get("kind") or UNKNOWN_KIND)
        node_kind_norm = normal(node_kind)

        has_unknown = (node_kind == UNKNOWN_KIND) or (kind == UNKNOWN_KIND) or (node_kind_norm in UNKNOWN_KINDS) or (n_kind in UNKNOWN_KINDS)
        compatible = (node_kind_norm == n_kind) or has_unknown or (not strict_kind)
        if not compatible:
            continue

        # 3. Phân giải Canonical Node nếu node này đã được redirect trong node_redirects
        active_id = resolve_active_node_id(project, node.get("id", ""))
        target_node = node
        if active_id != node.get("id"):
            canonical = next((n for n in nodes if n.get("id") == active_id), None)
            if canonical is not None:
                target_node = canonical

        # 4. Nâng cấp Loại nếu node cũ là UNKNOWN mà lần này trích xuất được loại cụ thể
        target_kind = str(target_node.get("kind") or UNKNOWN_KIND)
        if (target_kind == UNKNOWN_KIND or normal(target_kind) in UNKNOWN_KINDS) and (kind != UNKNOWN_KIND and n_kind not in UNKNOWN_KINDS):
            target_node["kind"] = kind

        # 5. Chuẩn hóa Casing: Ưu tiên tên bắt đầu bằng chữ hoa nếu tên cũ viết thường
        cur_name = str(target_node.get("name") or "")
        if name and name[0].isupper() and cur_name and not cur_name[0].isupper():
            target_node["name"] = name
            if cur_name and normal(cur_name) != normal(name):
                aliases = target_node.setdefault("aliases", [])
                if cur_name not in aliases:
                    aliases.append(cur_name)

        # 6. Làm giàu Bí danh: Nếu tên mới khác tên chính nhưng match qua alias/casing, lưu vào aliases
        if name and cur_name and normal(name) != normal(cur_name):
            aliases = target_node.setdefault("aliases", [])
            if name not in aliases:
                aliases.append(name)

        # 7. Ghi nhận tài liệu xuất hiện
        if doc_id:
            docs = target_node.setdefault("documents", [])
            if doc_id not in docs:
                docs.append(doc_id)

        # 8. Làm giàu Mô tả (Enrichment): Cập nhật nếu chưa có hoặc mô tả mới chi tiết hơn
        if description:
            old_desc = str(target_node.get("description") or "").strip()
            if not old_desc:
                target_node["description"] = description
            elif len(description) > len(old_desc) and (
                normal(old_desc) in normal(description) or len(old_desc) < 30
            ):
                target_node["description"] = description

        return str(target_node.get("id") or active_id)

    # Không tìm thấy thực thể tương ứng: Tạo node mới
    node_id = uid()
    new_node = {
        "id": node_id,
        "name": name,
        "kind": kind,
        "description": description,
        "aliases": [],
        "documents": [doc_id] if doc_id else [],
        "created_at": now_iso(),
    }
    if is_generic:
        new_node["is_component"] = True
    nodes.append(new_node)
    return node_id


def _is_duplicate_edge(project: dict, source: str, target: str, relation: str, quote: str, doc_id: str) -> bool:
    return any(
        edge.get("source") == source
        and edge.get("target") == target
        and normal(edge.get("relation", "")) == normal(relation)
        and normal(edge.get("evidence", "")) == normal(quote)
        and edge.get("doc_id") == doc_id
        for edge in project.get("edges", [])
    )


def ingest_extraction(
    project: dict,
    extraction: dict,
    document: dict,
    chunk: str,
    chunk_number: int,
    model: str,
    prompt_id: str,
    run_id: str = "",
    start_char: int | None = None,
    end_char: int | None = None,
    page: int | None = None,
    chunk_hash: str = "",
) -> dict:
    open_mode = project.get("extraction_mode") in (MODE_EDC, MODE_EDC_PLUS_R)
    if open_mode:
        validate_edc_payload(extraction)
    clean, report = validate_extraction(extraction, chunk, project.get("relations", []), open_mode=open_mode)
    proposal_count = len(project.get("schema_proposals", []))
    if open_mode:
        prepare_edc(
            project,
            clean,
            extraction,
            {
                "doc_id": document["id"],
                "doc_name": document.get("name", ""),
                "chunk_number": chunk_number,
                "chunk_hash": chunk_hash or sha(chunk),
                "run_id": run_id,
                "page": page,
                "model": model,
                "prompt_id": prompt_id,
            },
        )

    local: dict[str, str] = {}
    added_nodes = 0
    for entity in clean["thuc_the"]:
        before = len(project.get("nodes", []))
        node_id = ensure_node(project, entity["ten"], entity["loai"], entity["mo_ta"], document["id"], strict_kind=open_mode)
        if node_id:
            local[normal(entity["ten"])] = node_id
            if open_mode:
                node = next(n for n in project["nodes"] if n["id"] == node_id)
                node["schema_proposal_ids"] = list(dict.fromkeys(node.get("schema_proposal_ids", []) + entity["schema_proposal_ids"]))
                observation = {
                    "doc_id": document["id"],
                    "chunk_number": chunk_number,
                    "chunk_hash": chunk_hash or sha(chunk),
                    "name": entity["ten"],
                    "kind": entity["original_kind"],
                    "description": entity["mo_ta"],
                }
                if observation not in node.setdefault("edc_observations", []):
                    node["edc_observations"].append(observation)
        added_nodes += len(project["nodes"]) - before

    added_edges = 0
    duplicates = 0
    missing_endpoint = 0
    for relation in clean["quan_he"]:
        source = local.get(normal(relation["nguon"]))
        target = local.get(normal(relation["dich"]))
        if not source or not target:
            missing_endpoint += 1
            continue
        status = STATUS_CHECK if source == target else relation["status"]
        quote = relation["trich_dan"]
        relation_name = relation["quan_he"]
        if _is_duplicate_edge(project, source, target, relation_name, quote, document["id"]):
            duplicates += 1
            continue
        project.setdefault("edges", []).append(
            {
                "id": uid(),
                "source": source,
                "target": target,
                "relation": relation_name,
                "evidence": quote,
                "evidence_found": relation["evidence_found"],
                "doc_id": document["id"],
                "doc_name": document.get("name", ""),
                "doc_fingerprint": doc_fingerprint(document),
                "chunk_number": chunk_number,
                "chunk_hash": chunk_hash or sha(chunk),
                "start_char": start_char,
                "end_char": end_char,
                "page": page,
                "status": status,
                "model": model,
                "prompt_id": prompt_id,
                "run_id": run_id,
                "created_at": now_iso(),
                "reviewed_at": "",
                "review_note": "",
                "override": False,
            }
        )
        if open_mode:
            project["edges"][-1].update(
                extraction_mode="edc",
                edc_original=relation["edc_original"],
                schema_proposal_ids=relation["schema_proposal_ids"],
            )
        added_edges += 1

    return {
        "added_edges": added_edges,
        "added_nodes": added_nodes,
        "duplicates": duplicates,
        "discarded": report["invalid_relations"],
        "invalid_entities": report["invalid_entities"],
        "invalid_relations": report["invalid_relations"],
        "disallowed_relations": report["disallowed_relations"],
        "evidence_mismatch": report["evidence_mismatch"],
        "added_endpoints": report["added_endpoints"],
        "duplicate_entities": report["duplicate_entities"],
        "missing_endpoint": missing_endpoint,
        "rejected_items": report["rejected_items"],
        "new_proposals": len(project.get("schema_proposals", [])) - proposal_count,
    }


def cache_key(
    document: dict,
    record: dict,
    prompt_id: str,
    relation_sig: str,
    provider: str,
    model: str,
    base_url: str = "",
    temperature: float = 0.0,
    max_tokens: int = 0,
) -> str:
    parts = [
        document.get("hash", ""),
        record.get("chunk_hash", ""),
        prompt_id,
        relation_sig,
        provider,
        model,
        base_url,
        str(temperature),
        str(max_tokens),
    ]
    return sha("|".join(parts))

