"""Engine 1: Trích xuất theo Danh mục cố định (Fixed Catalog Mode)."""
from __future__ import annotations

import time

from backend.domain.catalogs.service import extraction_prompt, prompt_signature
from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput
from backend.integrations.llm import LLMGateway
from shared.constants import MODE_FIXED
from shared.schemas.graph import StepTraceDTO


class FixedCatalogEngine(BaseExtractionEngine):
    mode_id = MODE_FIXED
    display_name = "Danh mục cố định"

    def process_chunk(self, ctx: ChunkContext) -> EngineOutput:
        t0 = time.perf_counter()
        project = ctx.project
        sys_prompt = extraction_prompt(project)
        allowed = project.get("relations", [])
        prompt_id = prompt_signature(sys_prompt, allowed)

        ver_id, ver_hash, base_inst = self.resolve_prompt_version_info(project)
        appended = sys_prompt[len(base_inst):].strip() if (base_inst and sys_prompt.startswith(base_inst)) else ""

        result = LLMGateway.extract(
            ctx.provider,
            ctx.api_key,
            ctx.model,
            sys_prompt,
            ctx.chunk_record["text"],
            allowed,
            base_url=ctx.base_url,
            temperature=ctx.temperature,
            max_tokens=ctx.max_tokens,
            max_input_tokens=ctx.max_input_tokens,
            client=ctx.client,
            open_mode=False,
            project_id=str(project.get("project_id", "")),
            configuration_id=MODE_FIXED,
            prompt_version_id=ver_id,
            prompt_content_hash=ver_hash,
            base_instructions=base_inst,
            appended_content=appended,
        )
        duration = int((time.perf_counter() - t0) * 1000)

        stats = self.perform_ingest(ctx, result.data, prompt_id, MODE_FIXED)
        req_hash, prep_dict = self.extract_prepared_request_info(result.prepared_request)

        trace = StepTraceDTO(
            step_name="Fixed Catalog Extraction",
            loop_index=1,
            duration_ms=duration,
            summary=f"Trích xuất đóng: +{stats['added_nodes']} thực thể, +{stats['added_edges']} quan hệ",
            details={
                "allowed_relations_count": len(allowed),
                "prompt_version_id": ver_id,
                "prepared_request_hash": req_hash,
            },
        )
        return EngineOutput(
            payload=result.data,
            ingest_stats=stats,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            raw_response=result.raw,
            warnings=list(result.warnings),
            step_traces=[trace.to_dict()],
            prompt_version_id=ver_id,
            prompt_content_hash=ver_hash,
            prepared_request_hash=req_hash,
            prepared_request=prep_dict,
        )
