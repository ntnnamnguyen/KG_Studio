"""Application Service cho phân hệ Extraction, Documents & Prompts."""
from __future__ import annotations

import concurrent.futures
import copy
import json
import threading
from typing import Any, Callable

from backend.domain.catalogs.core import extraction_prompt, prompt_signature
from backend.domain.documents.processor import add_document as domain_add_document
from backend.domain.documents.processor import document_chunks as domain_document_chunks
from backend.domain.extraction.base_engine import ChunkContext, EngineOutput
from backend.domain.extraction.registry import EngineRegistry
from backend.domain.extraction.validator import cache_key
from backend.domain.prompts.service import (
    DEFAULT_PROMPTS,
    compute_prompt_hash,
    diff_prompt_versions,
    get_active_prompt_content,
    get_active_prompt_version,
    get_prompt_version,
    list_prompt_versions,
    restore_prompt_version,
    save_prompt_version,
)
from backend.integrations.embedder_gateway import default_embedder
from backend.integrations.llm import LLMGateway
from backend.modules.extraction.ports import LLMExtractionPort
from .free_triples_engine import FreeTriplesEngine
from .free_triples_runs import export_free_triples_results, read_free_triples_runs, run_free_triples
from shared.catalog_utils import edc_prompt, relation_catalog
from shared.constants import MODE_EDC, MODE_EDC_PLUS_R, MODE_FIXED, MODE_FREE_TRIPLES
from shared.schemas.free_triples import free_triples_prompt
from shared.schemas.project import EDCPlusRSettingsDTO
from shared.schemas.prompts import PreparedExtractionRequestDTO
from shared.text_utils import now_iso


class ExtractionApplicationService:
    """Dịch vụ ứng dụng quản lý Tài liệu, Cấu hình Prompt, và Trích xuất Thực thể - Quan hệ."""

    def __init__(
        self,
        *,
        engine_registry: EngineRegistry | None = None,
        schema_service: Any | None = None,
        project_store: Any | None = None,
        commit_coordinator: Any | None = None,
        llm_gateway: LLMExtractionPort | None = None,
    ) -> None:
        if engine_registry is None:
            self.engine_registry = EngineRegistry()
        else:
            self.engine_registry = engine_registry

        if llm_gateway is not None and MODE_FREE_TRIPLES not in {
            entry["mode_id"] for entry in self.engine_registry.available_modes()
        }:
            self.engine_registry.register(FreeTriplesEngine(llm_gateway=llm_gateway))
        self.schema_service = schema_service
        self.project_store = project_store
        self.commit_coordinator = commit_coordinator
        self.llm_gateway = llm_gateway
        self._project_locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def get_project_lock(self, project_id: str) -> threading.RLock:
        if self.commit_coordinator and hasattr(self.commit_coordinator, "get_project_lock"):
            return self.commit_coordinator.get_project_lock(project_id)
        with self._locks_guard:
            if project_id not in self._project_locks:
                self._project_locks[project_id] = threading.RLock()
            return self._project_locks[project_id]

    def _save_project_safe(self, project: dict) -> None:
        if self.commit_coordinator and hasattr(self.commit_coordinator, "project_store"):
            self.commit_coordinator.project_store.save_project(project)
        elif self.project_store:
            self.project_store.save_project(project)

    # --- Documents Management ---

    def add_document(
        self,
        project: dict,
        name: str,
        data: bytes | str,
        place_scope: str = "",
        source_label: str = "",
    ) -> tuple[bool, str]:
        raw_data = data.encode("utf-8") if isinstance(data, str) else data
        return domain_add_document(
            project,
            name=name,
            data=raw_data,
            place_scope=place_scope,
            source_label=source_label,
        )

    def document_chunks(
        self,
        document: dict,
        limit: int | None = None,
        overlap: int | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if limit is not None:
            kwargs["limit"] = limit
        if overlap is not None:
            kwargs["overlap"] = overlap
        return domain_document_chunks(document, **kwargs)

    # --- Prompt Versioning ---

    def get_active_prompt_version(self, project: dict, configuration_id: str) -> dict | None:
        return get_active_prompt_version(project, configuration_id)

    def list_prompt_versions(self, project: dict, configuration_id: str) -> list[dict]:
        return list_prompt_versions(project, configuration_id)

    def get_prompt_version(self, project: dict, configuration_id: str, version_id: str) -> dict | None:
        return get_prompt_version(project, configuration_id, version_id)

    def save_prompt_version(
        self,
        project: dict,
        configuration_id: str,
        content: str,
        change_description: str = "",
        author: str = "user",
    ) -> dict:
        return save_prompt_version(
            project,
            configuration_id=configuration_id,
            content=content,
            change_description=change_description,
            author=author,
        )

    def restore_prompt_version(
        self,
        project: dict,
        configuration_id: str,
        version_id: str,
        note: str = "",
    ) -> dict | None:
        return restore_prompt_version(
            project,
            configuration_id=configuration_id,
            version_id=version_id,
            note=note,
        )

    def diff_prompt_versions(
        self,
        project: dict,
        configuration_id: str,
        version_id_a: str,
        version_id_b: str,
    ) -> dict[str, Any]:
        return diff_prompt_versions(project, configuration_id, version_id_a, version_id_b)

    # --- Request Preparation & Extraction Execution ---

    def prepare_extraction_request(
        self,
        project: dict,
        chunk_text: str,
        *,
        provider: str = "",
        model: str = "",
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 12000,
        prompt_override: str | None = None,
    ) -> PreparedExtractionRequestDTO:
        cfg_id = project.get("extraction_mode", MODE_FIXED)
        active_ver = self.get_active_prompt_version(project, cfg_id)

        if prompt_override is not None:
            base_instructions = prompt_override
            ver_id = "custom_draft"
            ver_hash = compute_prompt_hash(prompt_override)
            is_draft = True
        else:
            is_draft = False
            base_instructions = active_ver.get("content", DEFAULT_PROMPTS.get(cfg_id, "")) if active_ver else DEFAULT_PROMPTS.get(cfg_id, "")
            ver_id = active_ver.get("id", "") if active_ver else ""
            ver_hash = active_ver.get("content_hash", "") if active_ver else ""

        retrieval_summary: dict[str, Any] = {}
        if cfg_id == MODE_FREE_TRIPLES:
            if self.llm_gateway is None:
                raise RuntimeError("Free-triple baseline cần LLM port được inject từ composition root.")
            full_prompt = free_triples_prompt(base_instructions)
            return self.llm_gateway.prepare_extraction_request(
                provider=provider or LLMGateway.DEFAULT_PROVIDER,
                model=model or LLMGateway.DEFAULT_MODELS.get(provider or LLMGateway.DEFAULT_PROVIDER, "deepseek-chat"),
                system_prompt=full_prompt, chunk=chunk_text, allowed_relations=[],
                temperature=temperature, max_tokens=max_tokens, max_input_tokens=max_input_tokens,
                open_mode=True, output_contract=MODE_FREE_TRIPLES,
                project_id=str(project.get("project_id", "")), configuration_id=cfg_id,
                prompt_version_id=ver_id, prompt_content_hash=ver_hash,
                base_instructions=base_instructions,
                appended_content=full_prompt[len(base_instructions.strip()):].strip(),
                is_draft=is_draft,
            )
        elif cfg_id == MODE_FIXED:
            catalogs = {"relations": relation_catalog(project), "entity_types": project.get("entity_types", [])}
            appended = (
                "\n\nDANH MỤC QUAN HỆ VÀ LOẠI THỰC THỂ ĐƯỢC PHÉP (JSON):\n"
                + json.dumps(catalogs, ensure_ascii=False, indent=2)
                + "\nChỉ dùng name trong relations cho trường quan_he và name trong entity_types cho trường loai."
            )
            full_sys_prompt = base_instructions + appended
            allowed_relations = project.get("relations", [])
            open_mode = False
        elif cfg_id == MODE_EDC:
            appended = "Hợp đồng JSON cấu trúc trích xuất mở (EDC_SCHEMA)."
            full_sys_prompt = edc_prompt(base_instructions)
            allowed_relations = []
            open_mode = True
        elif cfg_id == MODE_EDC_PLUS_R:
            raw_s = project.get("edc_plus_r_settings") or {}
            settings = raw_s if isinstance(raw_s, EDCPlusRSettingsDTO) else EDCPlusRSettingsDTO.from_dict(raw_s if isinstance(raw_s, dict) else {})
            embedder = default_embedder(settings.embedder_model)

            retriever = getattr(self.schema_service, "retriever", None)
            if retriever:
                retrieved = retriever.retrieve_for_chunk(
                    project,
                    chunk_text,
                    top_k_relations=settings.top_k_relations,
                    top_k_entity_types=settings.top_k_entity_types,
                    embedder=embedder,
                )
                schema_block = retriever.format_retrieved_schema_block(retrieved)
            else:
                from backend.domain.schema_intelligence.retriever import SchemaRetriever
                r = SchemaRetriever()
                retrieved = r.retrieve_for_chunk(
                    project,
                    chunk_text,
                    top_k_relations=settings.top_k_relations,
                    top_k_entity_types=settings.top_k_entity_types,
                    embedder=embedder,
                )
                schema_block = r.format_retrieved_schema_block(retrieved)

            augmented = base_instructions.strip() + "\n\n" + schema_block
            full_sys_prompt = edc_prompt(augmented)
            appended = schema_block
            allowed_relations = []
            open_mode = True
            retrieval_summary = {
                "retrieved_relations": len(retrieved.get("relations", [])),
                "retrieved_entity_types": len(retrieved.get("entity_types", [])),
                "embedder_model": getattr(embedder, "model_id", ""),
            }
        else:
            full_sys_prompt = base_instructions
            appended = ""
            allowed_relations = []
            open_mode = False

        prov = provider or LLMGateway.DEFAULT_PROVIDER
        mod = model or LLMGateway.DEFAULT_MODELS.get(prov, "deepseek-chat")

        return LLMGateway.prepare_extraction_request(
            provider=prov,
            model=mod,
            system_prompt=full_sys_prompt,
            chunk=chunk_text,
            allowed_relations=allowed_relations,
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            open_mode=open_mode,
            project_id=str(project.get("project_id", "")),
            configuration_id=cfg_id,
            prompt_version_id=ver_id,
            prompt_content_hash=ver_hash,
            base_instructions=base_instructions,
            appended_content=appended,
            loop_index=1,
            is_draft=is_draft,
            retrieval_summary=retrieval_summary,
        )

    def preview_extraction_request(
        self,
        project: dict,
        *,
        configuration_id: str,
        doc_id: str = "",
        chunk_number: int = 1,
        draft_content: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        base_url: str = "",
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 16000,
    ) -> PreparedExtractionRequestDTO:
        docs = project.get("documents", [])
        target_doc = None
        if doc_id:
            for d in docs:
                if d.get("id") == doc_id or d.get("name") == doc_id:
                    target_doc = d
                    break
        if not target_doc and docs:
            target_doc = docs[0]

        if target_doc:
            chunks = self.document_chunks(target_doc)
            chunk_rec = next((c for c in chunks if c.get("chunk_number") == chunk_number), chunks[0] if chunks else None)
            chunk_text = chunk_rec.get("text", "") if chunk_rec else (target_doc.get("text", "")[:2000])
        else:
            chunk_text = "Văn bản mẫu để kiểm tra trước cấu hình trích xuất và kiểm tra ngân sách token."

        # Preview the selected configuration without migrating/mutating the source project.
        # Only prompt metadata is migrated here; share read-only documents/catalogs
        # rather than deepcopying the entire graph for every preview.
        preview_project = dict(project)
        for key in ("prompt_bindings", "prompt_versions"):
            if key in project:
                preview_project[key] = copy.deepcopy(project[key])
        preview_project["extraction_mode"] = configuration_id
        return self.prepare_extraction_request(
            preview_project,
            chunk_text,
            provider=provider or "",
            model=model or "",
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            prompt_override=draft_content,
        )

    def extract_chunk(
        self,
        project: dict,
        document: dict,
        chunk_record: dict,
        *,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = "",
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 12000,
        client: object | None = None,
        lock: threading.Lock | threading.RLock | None = None,
        persist_run: bool = True,
    ) -> EngineOutput:
        mode = project.get("extraction_mode", "closed")
        engine = self.engine_registry.get(mode)
        if mode == MODE_FREE_TRIPLES and engine.mode_id != MODE_FREE_TRIPLES:
            raise ValueError("Registry chưa được inject engine free_triples; không fallback sang schema cố định.")
        if mode == MODE_FREE_TRIPLES and lock is None:
            lock = self.get_project_lock(str(project.get("project_id") or project.get("name") or "default"))
        ctx = ChunkContext(
            project=project,
            document=document,
            chunk_record=chunk_record,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            client=client,
            lock=lock,
        )
        if mode == MODE_FREE_TRIPLES:
            if self.project_store is not None and self.commit_coordinator is None and persist_run:
                raise RuntimeError("Lưu baseline cần ProjectCommitCoordinator; không ghi trực tiếp qua store.")
            return run_free_triples(engine, ctx, coordinator=self.commit_coordinator, persist_run=persist_run)
        output = engine.process_chunk(ctx)

        sys_prompt = extraction_prompt(project)
        rel_sig = (
            "edc_plus_r"
            if mode == MODE_EDC_PLUS_R
            else ("edc" if mode == MODE_EDC else "|".join(project.get("relations", [])))
        )
        p_id = prompt_signature(sys_prompt, [rel_sig])
        c_key = cache_key(document, chunk_record, p_id, rel_sig, provider, model, base_url, temperature, max_tokens)

        raw = output.raw_response or ""
        run_record = {
            "at": now_iso(),
            "doc_id": document["id"],
            "doc_name": document.get("name", ""),
            "chunk_number": chunk_record["chunk_number"],
            "chunk_hash": chunk_record.get("chunk_hash", ""),
            "cache_key": c_key,
            "provider": provider,
            "model": model,
            "prompt_id": p_id,
            "prompt_version_id": getattr(output, "prompt_version_id", ""),
            "prompt_content_hash": getattr(output, "prompt_content_hash", ""),
            "prepared_request_hash": getattr(output, "prepared_request_hash", ""),
            "prepared_request": getattr(output, "prepared_request", {}),
            "extraction_mode": mode,
            "input_tokens": output.input_tokens,
            "output_tokens": output.output_tokens,
            "added_nodes": output.ingest_stats.get("added_nodes", 0),
            "added_edges": output.ingest_stats.get("added_edges", 0),
            "duplicates": output.ingest_stats.get("duplicates", 0),
            "discarded": output.ingest_stats.get("discarded", 0),
            "evidence_mismatch": output.ingest_stats.get("evidence_mismatch", 0),
            "disallowed_relations": output.ingest_stats.get("disallowed_relations", []),
            "rejected_items": output.ingest_stats.get("rejected_items", []),
            "new_proposals": output.ingest_stats.get("new_proposals", 0),
            "warnings": output.warnings,
            "step_traces": output.step_traces,
            "alignment_summary": output.alignment_summary,
            "raw_response": raw[:100_000],
            "raw_truncated": len(raw) > 100_000,
            "status": "ok",
        }

        if lock:
            with lock:
                project.setdefault("runs", []).append(run_record)
                project.setdefault("processed_chunks", {})[c_key] = now_iso()
        else:
            project.setdefault("runs", []).append(run_record)
            project.setdefault("processed_chunks", {})[c_key] = now_iso()

        return output

    def export_free_triples_results(self, project: dict) -> bytes:
        return export_free_triples_results(project)

    def read_free_triples_runs(self, project: dict, run_ids: list[str] | None = None) -> dict:
        key = str(project.get("project_id") or project.get("name") or "default")
        with self.get_project_lock(key):
            return read_free_triples_runs(project, run_ids)

    def extract_chunks_parallel(
        self,
        project: dict,
        tasks: list[tuple[dict, dict]],
        *,
        provider: str,
        api_key: str,
        model: str,
        base_url: str = "",
        temperature: float = 0.0,
        max_tokens: int = 8192,
        max_input_tokens: int = 12000,
        max_workers: int = 3,
        on_progress: Callable[[int, int, dict, dict, EngineOutput | None, Exception | None], None] | None = None,
        save_after_chunk: bool = True,
        chunk_extractor: Callable[..., EngineOutput] | None = None,
        project_saver: Callable[[dict], Any] | None = None,
    ) -> dict[str, Any]:
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        proj_lock = self.get_project_lock(proj_id)
        extract_fn = chunk_extractor or self.extract_chunk
        save_fn = project_saver or self._save_project_safe
        baseline = project.get("extraction_mode") == MODE_FREE_TRIPLES
        baseline_kwargs = {"persist_run": save_after_chunk} if baseline else {}

        workers = max(1, min(int(max_workers or 1), 32))
        total_tasks = len(tasks)
        success_count = 0
        failed_tasks: list[dict] = []
        completed_count = 0

        if workers == 1:
            for idx, (doc, rec) in enumerate(tasks, 1):
                try:
                    out = extract_fn(
                        project,
                        doc,
                        rec,
                        provider=provider,
                        api_key=api_key,
                        model=model,
                        base_url=base_url,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        max_input_tokens=max_input_tokens,
                        lock=proj_lock,
                        **baseline_kwargs,
                    )
                    if save_after_chunk and not baseline:
                        with proj_lock:
                            save_fn(project)
                    success_count += 1
                    if on_progress:
                        on_progress(idx, total_tasks, doc, rec, out, None)
                except Exception as exc:
                    error_text = str(getattr(exc, "kind", type(exc).__name__)) if baseline else str(exc)
                    failed_tasks.append({"doc": doc, "rec": rec, "error": error_text})
                    if on_progress:
                        on_progress(idx, total_tasks, doc, rec, None, exc)
            return {
                "total": total_tasks,
                "success_count": success_count,
                "failed_count": len(failed_tasks),
                "failed_tasks": failed_tasks,
            }

        def _worker(task_tuple: tuple[dict, dict]) -> EngineOutput:
            d, r = task_tuple
            out = extract_fn(
                project,
                d,
                r,
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens,
                max_input_tokens=max_input_tokens,
                lock=proj_lock,
                **baseline_kwargs,
            )
            if save_after_chunk and not baseline:
                with proj_lock:
                    save_fn(project)
            return out

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_task = {
                executor.submit(_worker, task): task
                for task in tasks
            }
            for future in concurrent.futures.as_completed(future_to_task):
                completed_count += 1
                doc, rec = future_to_task[future]
                try:
                    out = future.result()
                    success_count += 1
                    if on_progress:
                        on_progress(completed_count, total_tasks, doc, rec, out, None)
                except Exception as exc:
                    error_text = str(getattr(exc, "kind", type(exc).__name__)) if baseline else str(exc)
                    failed_tasks.append({"doc": doc, "rec": rec, "error": error_text})
                    if on_progress:
                        on_progress(completed_count, total_tasks, doc, rec, None, exc)

        return {
            "total": total_tasks,
            "success_count": success_count,
            "failed_count": len(failed_tasks),
            "failed_tasks": failed_tasks,
        }
