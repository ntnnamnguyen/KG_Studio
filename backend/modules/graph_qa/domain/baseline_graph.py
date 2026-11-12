"""Construct a surface-form Open KG; no LLM, catalog, aliases or I/O."""
from __future__ import annotations

import copy
from typing import Any

from shared.schemas.free_triples import validate_free_triples
from shared.schemas.graph_input import BASELINE_GRAPH_POLICY, GraphSnapshotDTO, graph_fingerprint
from shared.text_utils import normal


def build_baseline_graph(bundle: dict[str, Any]) -> GraphSnapshotDTO:
    project_id = bundle["project_id"]
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    diagnostics: list[dict] = []
    manifest_runs: list[dict] = []
    chunks: set[tuple] = set()
    runs = sorted(bundle["runs"], key=lambda run: run["run_id"])
    for run in runs:
        rid = run["run_id"]
        doc_id = run.get("doc_id", "")
        chunk = (doc_id, run.get("chunk_number"))
        if not doc_id or type(chunk[1]) is not int or chunk[1] < 1:
            raise ValueError(f"Run {rid} thiếu doc/chunk identity")
        if chunk in chunks:
            raise ValueError("Chỉ chọn một attempt cho mỗi chunk; tách các lần chạy lại thành thí nghiệm riêng")
        chunks.add(chunk)
        prep = run.get("prepared_request") or {}
        if prep.get("project_id") and prep["project_id"] != project_id:
            raise ValueError(f"Run {rid} không thuộc project đang chọn")
        manifest_runs.append({
            key: copy.deepcopy(run.get(key)) for key in (
                "run_id", "doc_id", "doc_name", "chunk_number", "chunk_hash", "status",
                "provider", "model", "prompt_version_id", "prompt_content_hash",
                "prepared_request_hash", "input_tokens", "output_tokens", "credentials_redacted",
            )
        } | {"source_hash": graph_fingerprint(run),
             "fitted_input_hash": graph_fingerprint(prep["fitted_chunk_text"]) if isinstance(prep.get("fitted_chunk_text"), str) else None,
             "request_parameters": {key: prep.get(key) for key in ("temperature", "max_tokens", "max_input_tokens", "response_format")},
             "warnings": copy.deepcopy(run.get("warnings", []))})
        if run.get("status") != "ok":
            diagnostics.append({"run_id": rid, "code": "run_error", "error_kind": run.get("error_kind", "unknown")})
            continue
        payload = run.get("extraction_payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("triples"), list):
            diagnostics.append({"run_id": rid, "code": "invalid_payload", "payload": copy.deepcopy(payload)})
            continue
        fitted = prep.get("fitted_chunk_text")
        report = validate_free_triples(payload, fitted if isinstance(fitted, str) else None)
        for index, (triple, item_report) in enumerate(zip(payload["triples"], report["items"]), 1):
            if not isinstance(triple, dict) or any(
                not isinstance(triple.get(key), str) or not triple[key].strip()
                for key in ("subject", "predicate", "object")
            ):
                diagnostics.append({"run_id": rid, "triple_index": index, "code": "unbuildable_triple",
                                    "item": copy.deepcopy(triple), "issues": item_report["issues"]})
                continue
            endpoint_ids = []
            for label in (triple["subject"], triple["object"]):
                key = normal(label)
                nid = "b_n_" + graph_fingerprint([project_id, BASELINE_GRAPH_POLICY, key])
                if nid not in nodes:
                    nodes[nid] = {"id": nid, "name": label, "surface_key": key,
                                  "surface_forms": [], "kind": "", "description": ""}
                if label not in nodes[nid]["surface_forms"]:
                    nodes[nid]["surface_forms"].append(label)
                endpoint_ids.append(nid)
            quote = triple.get("evidence")
            evidence_found = quote in fitted if isinstance(quote, str) and quote.strip() and isinstance(fitted, str) else None
            if item_report["issues"] or evidence_found is None:
                diagnostics.append({"run_id": rid, "triple_index": index, "code": "triple_diagnostics",
                                    "item": copy.deepcopy(triple), "issues": item_report["issues"],
                                    "evidence_found": evidence_found})
            edges.append({
                "id": "b_e_" + graph_fingerprint([project_id, rid, index]),
                "source": endpoint_ids[0], "target": endpoint_ids[1], "relation": triple["predicate"],
                "evidence": quote if isinstance(quote, str) else "", "evidence_found": evidence_found,
                "run_id": rid, "triple_index": index, "doc_id": doc_id, "doc_name": run.get("doc_name", ""),
                "chunk_number": run.get("chunk_number"), "chunk_hash": run.get("chunk_hash"),
                "chunk_start_char": run.get("start_char"), "chunk_end_char": run.get("end_char"),
                "structurally_valid": item_report["structurally_valid"],
            })
    return GraphSnapshotDTO(
        project_id=project_id, name=bundle.get("project_name", ""), source="baseline",
        nodes=list(nodes.values()), edges=edges, diagnostics=diagnostics,
        manifest={"policy": BASELINE_GRAPH_POLICY, "identity_scope": "selected-corpus-surface-forms",
                  "selected_run_ids": [run["run_id"] for run in runs], "runs": manifest_runs,
                  "raw_runs_preserved": True, "semantic_canonicalization": False,
                  "duplicate_observations_preserved": True},
    )
