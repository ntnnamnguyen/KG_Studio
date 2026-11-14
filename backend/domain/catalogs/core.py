"""Các hàm cốt lõi cho Danh mục, Prompt và Revision Hashing."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from shared.catalog_utils import apply_relations, edc_prompt, relation_catalog, validate_catalog
from shared.constants import (
    DEFAULT_EDC_PROMPT,
    MODE_EDC,
    MODE_EDC_PLUS_R,
    MODE_FIXED,
)
from shared.schemas.edc import (
    BulkReviewRequestDTO,
    ProposalDecisionDTO,
)
from shared.text_utils import sha
from backend.domain.prompts.service import (
    get_active_prompt_content,
    save_prompt_version,
)


def prompt_signature(prompt: str, relations: list[str]) -> str:
    return sha(prompt + "\n" + "\n".join(relations))[:12]


def extraction_prompt(project: dict) -> str:
    mode = project.get("extraction_mode", MODE_FIXED)
    from shared.constants import MODE_FREE_TRIPLES
    from shared.schemas.free_triples import free_triples_prompt

    if mode == MODE_FREE_TRIPLES:
        return free_triples_prompt(get_active_prompt_content(project, mode))
    if mode in (MODE_EDC, MODE_EDC_PLUS_R):
        base = get_active_prompt_content(project, mode)
        return edc_prompt(base)
    base = get_active_prompt_content(project, MODE_FIXED)
    catalogs = {"relations": relation_catalog(project), "entity_types": project.get("entity_types", [])}
    return (
        base.strip()
        + "\n\nDANH MỤC QUAN HỆ VÀ LOẠI THỰC THỂ ĐƯỢC PHÉP (JSON):\n"
        + json.dumps(catalogs, ensure_ascii=False, indent=2)
        + "\nChỉ dùng name trong relations cho trường quan_he và name trong entity_types cho trường loai."
    )


def save_prompt_settings(project: dict, prompt: str, relations: list[dict], entity_types: list[dict]) -> bool:
    relations = validate_catalog(relations, "relations", allow_empty=True)
    entity_types = validate_catalog(entity_types, "entity_types", allow_empty=True)
    apply_relations(project, relations)
    project["entity_types"] = entity_types
    if isinstance(prompt, str) and prompt.strip():
        save_prompt_version(project, MODE_FIXED, prompt.strip(), note="Cập nhật kèm danh mục")
    return True


def catalog_rows(project: dict, kind: str) -> list[dict]:
    if kind == "relations":
        return relation_catalog(project)
    if kind == "entity_types":
        return validate_catalog(project.get("entity_types", []), "entity_types") if project.get("entity_types") else []
    raise ValueError("Nhóm đề xuất không hợp lệ")


def compute_catalog_hash(project: dict, kind: str | None = None) -> str:
    """Băm xác định cho danh mục hiện tại của dự án (theo từng kind hoặc toàn bộ)."""
    if kind in ("relations", "entity_types"):
        rows = catalog_rows(project, kind)
        return sha(json.dumps(rows, ensure_ascii=False, sort_keys=True))[:16]
    payload = {
        "relations": catalog_rows(project, "relations"),
        "entity_types": catalog_rows(project, "entity_types"),
    }
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def compute_project_revision(project: dict) -> str:
    """Tính revision phản ánh chính xác trạng thái dự án, danh mục, đề xuất và node/cạnh (streaming SHA-256 O(V+E+P))."""
    h = hashlib.sha256()
    upd = h.update
    sep = "\x1f"
    rec = "\x1e"

    upd(
        f"hdr{sep}{project.get('project_id', '')}{sep}{project.get('name', '')}{sep}{compute_catalog_hash(project)}{rec}".encode(
            "utf-8"
        )
    )

    prop_chunks: list[str] = []
    for p in project.get("schema_proposals", []):
        prop_chunks.append(
            f"{p.get('id', '')}{sep}{p.get('kind', '')}{sep}{p.get('name', '')}{sep}"
            f"{p.get('definition', '')}{sep}{p.get('description', '')}{sep}"
            f"{p.get('status', 'pending')}{sep}{p.get('canonical_name', '')}{sep}"
            f"{1 if p.get('auto_aligned', False) else 0}{sep}{p.get('decision_origin', '')}"
        )
    upd(("P:" + rec.join(prop_chunks) + rec).encode("utf-8"))

    node_chunks: list[str] = []
    for n in project.get("nodes", []):
        aliases_s = "\x1d".join(str(x) for x in n.get("aliases", ()))
        docs_s = "\x1d".join(str(x) for x in n.get("documents", ()))
        pids_s = "\x1d".join(str(x) for x in n.get("schema_proposal_ids", ()))
        node_chunks.append(
            f"{n.get('id', '')}{sep}{n.get('name', '')}{sep}{n.get('kind', '')}{sep}"
            f"{n.get('description', '')}{sep}{aliases_s}{sep}{docs_s}{sep}{pids_s}"
        )
    upd(("N:" + rec.join(node_chunks) + rec).encode("utf-8"))

    edge_chunks: list[str] = []
    for e in project.get("edges", []):
        pids_s = "\x1d".join(str(x) for x in e.get("schema_proposal_ids", ()))
        edge_chunks.append(
            f"{e.get('id', '')}{sep}{e.get('source', '')}{sep}{e.get('target', '')}{sep}"
            f"{e.get('relation', '')}{sep}{e.get('evidence', '')}{sep}{e.get('doc_id', '')}{sep}"
            f"{e.get('start_char')}{sep}{e.get('end_char')}{sep}{e.get('status', '')}{sep}"
            f"{1 if e.get('override', False) else 0}{sep}{e.get('rejection_code', '')}{sep}{pids_s}"
        )
    upd(("E:" + rec.join(edge_chunks) + rec).encode("utf-8"))

    node_redirs = sorted((str(k), str(v)) for k, v in (project.get("node_redirects") or {}).items())
    rel_redirs = sorted((str(k), str(v)) for k, v in (project.get("relation_redirects") or {}).items())
    p_bindings = sorted((str(k), str(v)) for k, v in (project.get("prompt_bindings") or {}).items())
    p_versions = sorted(str(v.get("id", "")) for v in project.get("prompt_versions", ()))
    gaz_items = sorted(
        (
            str(k),
            str(v.get("canonical_name", "")) if isinstance(v, dict) else str(v),
            str(v.get("kind", "")) if isinstance(v, dict) else "",
        )
        for k, v in (project.get("domain_gazetteer") or {}).items()
    )
    nd_entities = sorted(
        (
            str(r.get("node_a_id", "")),
            str(r.get("node_b_id", "")),
            str(r.get("pair_fingerprint", "")),
        )
        for r in (project.get("not_duplicate_pairs") or ())
        if isinstance(r, dict)
    )
    nd_rels = sorted(
        (
            str(r.get("relation_a", "")),
            str(r.get("relation_b", "")),
            str(r.get("pair_fingerprint", "")),
            str(r.get("kind", "")),
        )
        for r in (project.get("not_duplicate_relation_pairs") or ())
        if isinstance(r, dict)
    )
    tail = (
        f"T:{node_redirs}{sep}{rel_redirs}{sep}"
        f"{nd_entities}{sep}{nd_rels}{sep}"
        f"{p_bindings}{sep}{p_versions}{sep}{gaz_items}"
    )
    upd(tail.encode("utf-8"))
    return h.hexdigest()[:16]


def compute_decisions_hash(project_id: str, kind: str, decisions: list[ProposalDecisionDTO | dict]) -> str:
    """Băm danh sách quyết định trong lô (dùng để kiểm tra tính toàn vẹn giữa preview và apply)."""
    normalized = [ProposalDecisionDTO.from_dict(d).to_dict() for d in decisions]
    payload = {
        "project_id": str(project_id or "").strip(),
        "kind": str(kind or "").strip(),
        "decisions": normalized,
    }
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]


def compute_full_request_hash(req: BulkReviewRequestDTO | dict) -> str:
    """Băm toàn bộ nội dung request (kể cả apply_mode) để kiểm tra idempotency theo request_id."""
    dto = BulkReviewRequestDTO.from_dict(req)
    payload = {
        "project_id": dto.project_id,
        "kind": dto.kind,
        "apply_mode": dto.apply_mode,
        "decisions": [d.to_dict() for d in dto.decisions],
    }
    return sha(json.dumps(payload, ensure_ascii=False, sort_keys=True))[:16]
