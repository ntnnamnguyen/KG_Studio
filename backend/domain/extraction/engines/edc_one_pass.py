"""Engine 2: Trích xuất EDC mở 1 lượt (Basic EDC Mode)."""
from __future__ import annotations

import time

from backend.domain.catalogs.service import extraction_prompt, prompt_signature
from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput
from backend.integrations.llm import LLMGateway
from shared.constants import MODE_EDC
from shared.schemas.graph import StepTraceDTO


class EDCOnePassEngine(BaseExtractionEngine):
    mode_id = MODE_EDC
    display_name = "EDC mở — đề xuất định nghĩa (1 lượt)"

    def process_chunk(self, ctx: ChunkContext) -> EngineOutput:
        t0 = time.perf_counter()
        project = ctx.project

        def _read_prompt_inputs() -> tuple[str, str, str, str, str, str]:
            snap = dict(project)
            snap["extraction_mode"] = MODE_EDC
            s_prompt = extraction_prompt(snap)
            p_id = prompt_signature(s_prompt, ["edc"])
            v_id, v_hash, b_inst = self.resolve_prompt_version_info(snap)
            return s_prompt, p_id, v_id, v_hash, b_inst, str(snap.get("project_id", ""))

        if ctx.lock:
            with ctx.lock:
                sys_prompt, prompt_id, ver_id, ver_hash, base_inst, project_id = _read_prompt_inputs()
        else:
            sys_prompt, prompt_id, ver_id, ver_hash, base_inst, project_id = _read_prompt_inputs()

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
            project_id=project_id,
            configuration_id=MODE_EDC,
            prompt_version_id=ver_id,
            prompt_content_hash=ver_hash,
            base_instructions=base_inst,
        )
        duration = int((time.perf_counter() - t0) * 1000)
        stats = self.perform_ingest(ctx, result.data, prompt_id, MODE_EDC)

        req_hash, prep_dict = self.extract_prepared_request_info(result.prepared_request)

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
