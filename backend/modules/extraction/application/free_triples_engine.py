"""Raw extraction baseline B: no domain schema, definitions or graph ingestion."""
from __future__ import annotations

from contextlib import nullcontext
import time

from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput
from backend.modules.extraction.ports import LLMExtractionPort
from shared.constants import DEFAULT_FREE_TRIPLES_PROMPT, MODE_FREE_TRIPLES
from shared.schemas.free_triples import free_triples_prompt, validate_free_triples
from shared.schemas.graph import StepTraceDTO


class FreeTriplesEngine(BaseExtractionEngine):
    """One extraction call through an injected gateway; return artifacts only.

    Registration and gateway wiring belong to the composition root. The engine
    never calls ingest_extraction, schema retrieval/alignment, or merge functions.
    """

    mode_id = MODE_FREE_TRIPLES
    display_name = "Bộ ba tự do — baseline (không chuẩn hóa ngữ nghĩa)"

    def __init__(self, llm_gateway: LLMExtractionPort) -> None:
        self.llm_gateway = llm_gateway

    def process_chunk(self, ctx: ChunkContext) -> EngineOutput:
        start = time.perf_counter()
        # A concurrent artifact commit can replace the shared project contents.
        # Resolve the immutable prompt while holding the same in-process lock.
        with (ctx.lock if ctx.lock is not None else nullcontext()):
            ver_id, ver_hash, instructions = self.resolve_prompt_version_info(ctx.project)
            project_id = str(ctx.project.get("project_id", ""))
        base = instructions or DEFAULT_FREE_TRIPLES_PROMPT
        prompt = free_triples_prompt(base)
        result = self.llm_gateway.extract(
            ctx.provider, ctx.api_key, ctx.model, prompt, ctx.chunk_record["text"], [],
            base_url=ctx.base_url,
            temperature=ctx.temperature,
            max_tokens=ctx.max_tokens,
            max_input_tokens=ctx.max_input_tokens,
            client=ctx.client,
            open_mode=True,
            output_contract=MODE_FREE_TRIPLES,
            project_id=project_id,
            configuration_id=MODE_FREE_TRIPLES,
            prompt_version_id=ver_id,
            prompt_content_hash=ver_hash,
            base_instructions=base,
            appended_content=prompt[len(base.strip()):].strip(),
        )
        req_hash, prep_dict = self.extract_prepared_request_info(result.prepared_request)
        fitted = prep_dict.get("fitted_chunk_text", ctx.chunk_record["text"])
        report = validate_free_triples(result.data, fitted)
        stats = {
            "added_nodes": 0, "added_edges": 0, "new_proposals": 0,
            "duplicates": 0, "discarded": 0,
            "extracted_triples": report["total_triples"],
            "valid_triples": report["valid_triples"],
            "invalid_triples": report["invalid_triples"],
            "evidence_mismatch": report["evidence_mismatch"],
            "validation_report": report,
        }
        warnings = list(result.warnings)
        if report["invalid_triples"] or report["evidence_mismatch"]:
            warnings.append("Baseline giữ nguyên cả triple lỗi cấu trúc/bằng chứng; xem validation_report trước khi đánh giá.")
        trace = StepTraceDTO(
            step_name="Free triple baseline — raw extraction only",
            loop_index=1,
            duration_ms=int((time.perf_counter() - start) * 1000),
            summary=f"{report['total_triples']} triple thô; không nhập đồ thị hoặc chuẩn hóa schema",
            details={"validation_report": report, "prepared_request_hash": req_hash, "artifact_only": True},
        )
        return EngineOutput(
            payload=result.data, ingest_stats=stats,
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            raw_response=result.raw, warnings=warnings, step_traces=[trace.to_dict()],
            prompt_version_id=ver_id, prompt_content_hash=ver_hash,
            prepared_request_hash=req_hash, prepared_request=prep_dict,
        )
