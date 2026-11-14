"""Engine 3: EDC + R (Iterative Refinement + Schema Retriever + Target Alignment)."""
from __future__ import annotations

import copy
import time

from backend.domain.catalogs.service import prompt_signature
from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput
from backend.domain.extraction.validator import ingest_extraction
from backend.domain.prompts.service import get_active_prompt_version
from backend.domain.schema_intelligence.aligner import TargetAligner
from backend.domain.schema_intelligence.retriever import SchemaRetriever
from backend.integrations.embedder_gateway import default_embedder
from backend.integrations.llm import LLMGateway
from shared.catalog_utils import edc_prompt
from shared.constants import DEFAULT_EDC_PROMPT, MODE_EDC, MODE_EDC_PLUS_R
from shared.schemas.graph import StepTraceDTO
from shared.schemas.project import EDCPlusRSettingsDTO
from shared.text_utils import uid


class EDCPlusREngine(BaseExtractionEngine):
    mode_id = MODE_EDC_PLUS_R
    display_name = "EDC + R — Truy xuất quan hệ (+R) & Chuẩn hóa tự động (Target Alignment)"

    def __init__(
        self,
        retriever: SchemaRetriever | None = None,
        aligner: TargetAligner | None = None,
    ) -> None:
        self.retriever = retriever or SchemaRetriever()
        self.aligner = aligner or TargetAligner()

    def process_chunk(self, ctx: ChunkContext) -> EngineOutput:
        project = ctx.project
        run_id = uid()

        def _read_shared_snapshot() -> tuple[EDCPlusRSettingsDTO, str, str, str, dict]:
            snap_proj = dict(project)
            snap_proj["extraction_mode"] = MODE_EDC_PLUS_R
            s = EDCPlusRSettingsDTO.from_dict(project.get("edc_plus_r_settings"))
            v_id, v_hash, b_inst = self.resolve_prompt_version_info(snap_proj)
            b_instructions = b_inst or project.get("edc_prompt", DEFAULT_EDC_PROMPT)
            retrieval_snapshot = {
                "project_id": project.get("project_id", ""),
                "relations": copy.deepcopy(project.get("relations", [])),
                "relation_notes": copy.deepcopy(project.get("relation_notes", {})),
                "relation_catalog": copy.deepcopy(project.get("relation_catalog", [])),
                "entity_types": copy.deepcopy(project.get("entity_types", [])),
                "entity_type_aliases": copy.deepcopy(project.get("entity_type_aliases", {})),
                "relation_aliases": copy.deepcopy(project.get("relation_aliases", {})),
            }
            return s, v_id, v_hash, b_instructions, retrieval_snapshot

        if ctx.lock:
            with ctx.lock:
                settings, ver_id, ver_hash, base_instructions, retrieval_proj = _read_shared_snapshot()
        else:
            settings, ver_id, ver_hash, base_instructions, retrieval_proj = _read_shared_snapshot()

        embedder = default_embedder(settings.embedder_model)

        step_traces: list[dict] = []
        total_in_tokens = 0
        total_out_tokens = 0
        all_warnings: list[str] = []
        last_raw = ""
        final_payload: dict = {
            "thuc_the": [],
            "quan_he": [],
            "dinh_nghia_quan_he": [],
            "dinh_nghia_loai": [],
        }

        entity_hints: list[str] = []
        relation_hints: list[str] = []
        last_prep = None

        for loop_idx in range(1, settings.refinement_loops + 1):
            t_sr = time.perf_counter()
            retrieved = self.retriever.retrieve_for_chunk(
                retrieval_proj,
                ctx.chunk_record["text"],
                top_k_relations=settings.top_k_relations,
                top_k_entity_types=settings.top_k_entity_types,
                extracted_relation_hints=relation_hints,
                embedder=embedder,
            )
            sr_ms = int((time.perf_counter() - t_sr) * 1000)
            schema_block = self.retriever.format_retrieved_schema_block(
                retrieved,
                entity_hints=entity_hints if loop_idx > 1 else None,
            )
            step_traces.append(
                StepTraceDTO(
                    step_name="1. Schema Retrieval (+R)",
                    loop_index=loop_idx,
                    duration_ms=sr_ms,
                    summary=(
                        f"Truy xuất Top-{len(retrieved['relations'])} quan hệ & "
                        f"Top-{len(retrieved['entity_types'])} loại thực thể ({embedder.model_id})"
                    ),
                    details={
                        "retrieved_relations": [
                            {"name": r["name"], "score": r.get("score", 0.0)} for r in retrieved["relations"]
                        ],
                        "retrieved_entity_types": [
                            {"name": t["name"], "score": t.get("score", 0.0)} for t in retrieved["entity_types"]
                        ],
                        "entity_hints": list(entity_hints),
                        "prompt_version_id": ver_id,
                    },
                ).to_dict()
            )

            t_ext = time.perf_counter()
            augmented_instructions = base_instructions.strip() + "\n\n" + schema_block
            full_sys_prompt = edc_prompt(augmented_instructions)
            result = LLMGateway.extract(
                ctx.provider,
                ctx.api_key,
                ctx.model,
                full_sys_prompt,
                ctx.chunk_record["text"],
                [],
                base_url=ctx.base_url,
                temperature=ctx.temperature,
                max_tokens=ctx.max_tokens,
                max_input_tokens=ctx.max_input_tokens,
                client=ctx.client,
                open_mode=True,
                project_id=str(retrieval_proj.get("project_id", "")),
                configuration_id=MODE_EDC_PLUS_R,
                prompt_version_id=ver_id,
                prompt_content_hash=ver_hash,
                base_instructions=base_instructions,
                appended_content=schema_block,
                loop_index=loop_idx,
            )
            last_prep = result.prepared_request
            ext_ms = int((time.perf_counter() - t_ext) * 1000)

            total_in_tokens += result.input_tokens
            total_out_tokens += result.output_tokens
            all_warnings.extend(result.warnings)
            last_raw = result.raw
            final_payload = result.data

            entity_hints = [e.get("ten", "") for e in final_payload.get("thuc_the", []) if e.get("ten")]
            relation_hints = [r.get("quan_he", "") for r in final_payload.get("quan_he", []) if r.get("quan_he")]

            step_traces.append(
                StepTraceDTO(
                    step_name="2. Open Extraction & 3. Schema Definition",
                    loop_index=loop_idx,
                    duration_ms=ext_ms,
                    summary=(
                        f"Vòng {loop_idx}: rút {len(final_payload.get('thuc_the', []))} thực thể, "
                        f"{len(final_payload.get('quan_he', []))} quan hệ"
                    ),
                    details={
                        "entities_extracted": len(final_payload.get("thuc_the", [])),
                        "relations_extracted": len(final_payload.get("quan_he", [])),
                        "relation_definitions": final_payload.get("dinh_nghia_quan_he", []),
                        "entity_type_definitions": final_payload.get("dinh_nghia_loai", []),
                        "prompt_version_id": ver_id,
                        "prepared_request_hash": getattr(result.prepared_request, "request_hash", "") or "",
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                    },
                ).to_dict()
            )

        def _do_ingest_and_align():
            prompt_id = prompt_signature(edc_prompt(base_instructions), ["edc_plus_r", embedder.fingerprint])
            stats = ingest_extraction(
                project,
                final_payload,
                ctx.document,
                ctx.chunk_record["text"],
                ctx.chunk_record["chunk_number"],
                ctx.model,
                prompt_id,
                run_id=run_id,
                start_char=ctx.chunk_record.get("start_char"),
                end_char=ctx.chunk_record.get("end_char"),
                page=ctx.chunk_record.get("page_from"),
                chunk_hash=ctx.chunk_record.get("chunk_hash", ""),
            )
            t_align = time.perf_counter()
            llm_params = {
                "provider": ctx.provider,
                "api_key": ctx.api_key,
                "model": ctx.model,
                "base_url": ctx.base_url,
                "client": ctx.client,
            }
            touched_ids = list(stats.get("touched_proposal_ids") or [])
            if touched_ids:
                alignment_summary = self.aligner.align_project_proposals(
                    project,
                    auto_align_threshold=settings.auto_align_threshold,
                    candidate_threshold=settings.candidate_threshold,
                    enable_llm_verifier=settings.enable_llm_verifier,
                    llm_params=llm_params,
                    embedder=embedder,
                    proposal_ids=touched_ids,
                )
            else:
                alignment_summary = {
                    "auto_aligned": 0,
                    "suggested_for_review": 0,
                    "novel_proposals": 0,
                    "error_count": 0,
                    "verifier_input_tokens": 0,
                    "verifier_output_tokens": 0,
                }
            align_ms = int((time.perf_counter() - t_align) * 1000)
            return stats, alignment_summary, align_ms

        stats, alignment_summary, align_ms = self.safe_ingest(ctx, _do_ingest_and_align, MODE_EDC_PLUS_R)
        total_in_tokens += int(alignment_summary.get("verifier_input_tokens", 0) or 0)
        total_out_tokens += int(alignment_summary.get("verifier_output_tokens", 0) or 0)

        step_traces.append(
            StepTraceDTO(
                step_name="4. Target Alignment (Schema Canonicalization)",
                loop_index=settings.refinement_loops,
                duration_ms=align_ms,
                summary=(
                    f"Tự động khớp: {alignment_summary['auto_aligned']} | "
                    f"Gợi ý duyệt: {alignment_summary['suggested_for_review']} | "
                    f"Mục mới: {alignment_summary['novel_proposals']}"
                ),
                details=alignment_summary,
            ).to_dict()
        )

        req_hash, prep_dict = self.extract_prepared_request_info(last_prep)

        return EngineOutput(
            payload=final_payload,
            ingest_stats=stats,
            input_tokens=total_in_tokens,
            output_tokens=total_out_tokens,
            raw_response=last_raw,
            warnings=all_warnings,
            step_traces=step_traces,
            alignment_summary=alignment_summary,
            prompt_version_id=ver_id,
            prompt_content_hash=ver_hash,
            prepared_request_hash=req_hash,
            prepared_request=prep_dict,
            run_id=run_id,
        )

