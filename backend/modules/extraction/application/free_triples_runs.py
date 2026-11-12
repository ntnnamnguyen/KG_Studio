"""Record and export raw baseline attempts without changing the curated graph."""
from __future__ import annotations

import copy
import json
from typing import Any

from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput
from backend.domain.prompts.service import ensure_project_prompt_history
from shared.constants import MODE_FREE_TRIPLES
from shared.text_utils import now_iso, sha, uid


def _redact_credential(value: Any, credential: str) -> Any:
    """Never log provider credentials, including an accidental SDK/model echo."""
    if isinstance(value, str):
        return value.replace(credential, "[REDACTED]") if credential else value
    if isinstance(value, dict):
        return {
            _redact_credential(key, credential): _redact_credential(item, credential)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_credential(item, credential) for item in value]
    return value


def run_free_triples(
    engine: BaseExtractionEngine,
    ctx: ChunkContext,
    *,
    coordinator: Any = None,
    persist_run: bool = True,
) -> EngineOutput:
    """Store successful AND failed attempts, never silently selecting good facts.

    Persistence uses the existing project commit coordinator. Without one, results
    are in-memory only; this helper never creates a second filesystem write path.
    ``persist_run=False`` supports explicitly unsaved experimental runs.
    """
    run_id = uid()
    # Seed immutable prompt bindings once before parallel provider calls begin.
    if ctx.lock:
        with ctx.lock:
            ensure_project_prompt_history(ctx.project)
    else:
        ensure_project_prompt_history(ctx.project)

    def record(output: EngineOutput | None, error: Exception | None = None) -> None:
        prep = output.prepared_request if output else getattr(error, "prepared_request", {})
        if hasattr(prep, "to_dict"):
            prep = prep.to_dict()
        prep = dict(prep or {})
        raw = output.raw_response if output else getattr(error, "raw", "")
        report = output.ingest_stats.get("validation_report", {}) if output else {}
        status = "error" if error is not None else "ok"
        chunk_hash = ctx.chunk_record.get("chunk_hash") or sha(ctx.chunk_record["text"])
        request_hash = output.prepared_request_hash if output else prep.get("request_hash", "")
        cache_key = sha(f"{MODE_FREE_TRIPLES}|{ctx.document['id']}|{chunk_hash}|{request_hash}")
        run = {
            "run_id": run_id, "at": now_iso(), "extraction_mode": MODE_FREE_TRIPLES,
            "stage": "raw", "artifact_only": True,
            "doc_id": ctx.document["id"], "doc_name": ctx.document.get("name", ""),
            "chunk_number": ctx.chunk_record["chunk_number"], "chunk_hash": chunk_hash,
            "start_char": ctx.chunk_record.get("start_char"),
            "end_char": ctx.chunk_record.get("end_char"), "page": ctx.chunk_record.get("page_from"),
            "cache_key": cache_key, "provider": ctx.provider, "model": ctx.model,
            "prompt_id": sha(prep.get("system_prompt", "")),
            "prompt_version_id": prep.get("prompt_version_id", ""),
            "prompt_content_hash": prep.get("prompt_content_hash", ""),
            "prepared_request_hash": request_hash, "prepared_request": prep,
            "input_tokens": output.input_tokens if output else int(getattr(error, "input_tokens", 0)),
            "output_tokens": output.output_tokens if output else int(getattr(error, "output_tokens", 0)),
            "extraction_payload": copy.deepcopy(output.payload) if output else None,
            "validation_report": copy.deepcopy(report),
            "raw_response": raw, "raw_truncated": False,
            "warnings": list(output.warnings) if output else [],
            "step_traces": list(output.step_traces) if output else [],
            "alignment_summary": {}, "added_nodes": 0, "added_edges": 0,
            "new_proposals": 0, "discarded": 0,
            "extracted_triples": report.get("total_triples", 0),
            "invalid_triples": report.get("invalid_triples", 0),
            "evidence_mismatch": report.get("evidence_mismatch", 0),
            "status": status,
            # Exception messages may echo credentials; keep only the error category.
            "error_kind": str(getattr(error, "kind", type(error).__name__)) if error else "",
            "policy": {"schema_retrieval": False, "definitions": False, "canonicalization": False,
                       "deduplication": False, "graph_ingestion": False},
        }
        safe_run = _redact_credential(run, ctx.api_key)
        safe_run["credentials_redacted"] = safe_run != run

        def append(candidate: dict) -> None:
            candidate.setdefault("runs", []).append(safe_run)
            if status == "ok":
                candidate.setdefault("processed_chunks", {})[cache_key] = safe_run["at"]

        if coordinator is not None and persist_run:
            def execute(current: dict) -> tuple[dict, dict]:
                candidate = copy.deepcopy(current)
                append(candidate)
                return candidate, {"run_id": run_id, "status": status}

            coordinator.commit(
                ctx.project,
                request_id=run_id,
                request_hash=sha(json.dumps(safe_run, ensure_ascii=False, sort_keys=True)),
                expected_revision="",
                executor=execute,
                idempotency_store_key="free_triples_run_idempotency_store",
            )
        elif ctx.lock:
            with ctx.lock:
                append(ctx.project)
        else:
            append(ctx.project)

    try:
        output = engine.process_chunk(ctx)
    except Exception as error:
        record(None, error)
        raise
    record(output)
    return output


def export_free_triples_results(project: dict) -> bytes:
    """Export every baseline attempt, independent of approval/schema filters."""
    payload = {
        "format": "kg-studio.free-triples.v1",
        "extraction_mode": MODE_FREE_TRIPLES,
        "project_id": project.get("project_id", ""),
        "project_name": project.get("name", ""),
        "runs": [run for run in list(project.get("runs", [])) if run.get("extraction_mode") == MODE_FREE_TRIPLES],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def read_free_triples_runs(project: dict, run_ids: list[str] | None = None) -> dict:
    """Public read contract: detached runs, never pick a best/latest attempt."""
    runs = [run for run in project.get("runs", []) if run.get("extraction_mode") == MODE_FREE_TRIPLES]
    ids = [run.get("run_id") for run in runs]
    if any(not isinstance(rid, str) or not rid for rid in ids) or len(set(ids)) != len(ids):
        raise ValueError("Baseline runs cần run_id duy nhất")
    if run_ids is not None:
        if len(set(run_ids)) != len(run_ids) or any(rid not in ids for rid in run_ids):
            raise ValueError("Run không tồn tại trong baseline của project hoặc bị chọn lặp")
        selected = set(run_ids)
        runs = [run for run in runs if run["run_id"] in selected]
    return copy.deepcopy({"project_id": str(project.get("project_id") or project.get("name") or ""),
                          "project_name": project.get("name", ""), "runs": runs})
