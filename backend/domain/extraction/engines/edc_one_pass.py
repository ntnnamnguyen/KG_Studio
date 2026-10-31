"""Engine 2: Trích xuất EDC mở 1 lượt (Basic EDC Mode)."""
from __future__ import annotations

import time

from backend.domain.catalogs.service import extraction_prompt, prompt_signature
from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput
from backend.domain.extraction.validator import ingest_extraction
from backend.domain.prompts.service import get_active_prompt_version
from backend.integrations.llm_gateway import LLMGateway
from shared.constants import MODE_EDC
from shared.schemas.graph import StepTraceDTO
from shared.text_utils import uid


class EDCOnePassEngine(BaseExtractionEngine):
    mode_id = MODE_EDC
    display_name = "EDC mở — đề xuất định nghĩa (1 lượt)"

    def process_chunk(self, ctx: ChunkContext) -> EngineOutput:
        t0 = time.perf_counter()
        project = ctx.project
        prev_mode = project.get("extraction_mode")
        project["extraction_mode"] = MODE_EDC
        try:
            sys_prompt = extraction_prompt(project)
            prompt_id = prompt_signature(sys_prompt, ["edc"])

            active_ver = get_active_prompt_version(project, MODE_EDC)
            ver_id = active_ver["id"] if active_ver else ""
            ver_hash = active_ver["content_hash"] if active_ver else ""
            base_inst = active_ver["content"] if active_ver else ""

            result = LLMGateway.extract(
                ctx.provider,
                ctx.api_key,
                ctx.model,
                sys_prompt,
                ctx.chunk_record["text"],
                [],
                base_url=ctx.base_url,
                temperature=ctx.temperature,
                max_tokens=ctx.max_tokens,
                max_input_tokens=ctx.max_input_tokens,
                client=ctx.client,
                open_mode=True,
                project_id=str(project.get("project_id", "")),
                configuration_id=MODE_EDC,
                prompt_version_id=ver_id,
                prompt_content_hash=ver_hash,
                base_instructions=base_inst,
            )
            duration = int((time.perf_counter() - t0) * 1000)

            stats = ingest_extraction(
                project,
                result.data,
                ctx.document,
                ctx.chunk_record["text"],
                ctx.chunk_record["chunk_number"],
                ctx.model,
                prompt_id,
                run_id=uid(),
                start_char=ctx.chunk_record.get("start_char"),
                end_char=ctx.chunk_record.get("end_char"),
                page=ctx.chunk_record.get("page_from"),
                chunk_hash=ctx.chunk_record.get("chunk_hash", ""),
            )
        finally:
            if prev_mode is not None:
                project["extraction_mode"] = prev_mode

        prep = result.prepared_request
        req_hash = prep.request_hash if prep else ""
        prep_dict = prep.to_dict() if prep else {}

        trace = StepTraceDTO(
            step_name="EDC Open Extraction + Schema Definition",
            loop_index=1,
            duration_ms=duration,
            summary=f"EDC 1 lượt: +{stats['added_nodes']} thực thể, +{stats['added_edges']} quan hệ, +{stats['new_proposals']} đề xuất",
            details={
                "defined_relations": len(result.data.get("dinh_nghia_quan_he", [])),
                "defined_entity_types": len(result.data.get("dinh_nghia_loai", [])),
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

