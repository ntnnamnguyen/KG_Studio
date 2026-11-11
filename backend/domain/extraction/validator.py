"""Kiểm tra đầu ra LLM và ghi nhận Thực thể / Quan hệ vào dự án (Độc lập 100%)."""
from __future__ import annotations

from backend.domain.catalogs.service import prepare_edc
from backend.domain.curation.service import doc_fingerprint, evidence_in_chunk
from shared.catalog_utils import validate_edc_payload
from shared.config_loader import CONFIG
from shared.constants import MODE_EDC, MODE_EDC_PLUS_R, STATUS_CHECK, STATUS_PENDING
from shared.text_utils import clean_relation_name, normal, now_iso, sha, uid

UNKNOWN_KIND = CONFIG["knowledge"]["unknown_entity_kind"]


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
    if not name:
        return ""

    for node in project.setdefault("nodes", []):
        same_name = normal(node.get("name", "")) == normal(name)
        node_kind = str(node.get("kind") or UNKNOWN_KIND)
        compatible = normal(node_kind) == normal(kind) or (not strict_kind and UNKNOWN_KIND in (node_kind, kind))
        if same_name and compatible:
            if kind != UNKNOWN_KIND and node_kind == UNKNOWN_KIND:
                node["kind"] = kind
            if doc_id and doc_id not in node["documents"]:
                node["documents"].append(doc_id)
            if description and not node.get("description"):
                node["description"] = description
            return node["id"]

    node_id = uid()
    project["nodes"].append(
        {
            "id": node_id,
            "name": name,
            "kind": kind,
            "description": description,
            "aliases": [],
            "documents": [doc_id] if doc_id else [],
            "created_at": now_iso(),
        }
    )
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

