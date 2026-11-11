"""Giao diện chuẩn (Strategy Pattern) cho các Bộ Trích xuất Tri thức (Extraction Engines)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkContext:
    project: dict
    document: dict
    chunk_record: dict
    provider: str
    api_key: str
    model: str
    base_url: str = ""
    temperature: float = 0.0
    max_tokens: int = 8192
    max_input_tokens: int = 12000
    client: object | None = None
    lock: object | None = None


@dataclass
class EngineOutput:
    payload: dict
    ingest_stats: dict
    input_tokens: int = 0
    output_tokens: int = 0
    raw_response: str = ""
    warnings: list[str] = field(default_factory=list)
    step_traces: list[dict] = field(default_factory=list)
    alignment_summary: dict = field(default_factory=dict)
    prompt_version_id: str = ""
    prompt_content_hash: str = ""
    prepared_request_hash: str = ""
    prepared_request: dict = field(default_factory=dict)


class BaseExtractionEngine(ABC):
    mode_id: str = ""
    display_name: str = ""

    @abstractmethod
    def process_chunk(self, ctx: ChunkContext) -> EngineOutput:
        raise NotImplementedError

    def resolve_prompt_version_info(self, project: dict) -> tuple[str, str, str]:
        """Lấy thông tin phiên bản prompt đang hoạt động: (version_id, content_hash, base_instructions)."""
        from backend.domain.prompts.service import get_active_prompt_version

        active_ver = get_active_prompt_version(project, self.mode_id)
        if not active_ver:
            return "", "", ""
        return (
            str(active_ver.get("id") or ""),
            str(active_ver.get("content_hash") or ""),
            str(active_ver.get("content") or ""),
        )

    def extract_prepared_request_info(self, prepared_request: Any) -> tuple[str, dict]:
        """Trích xuất chữ ký và dict của prepared request từ kết quả LLM extract."""
        if not prepared_request:
            return "", {}
        req_hash = getattr(prepared_request, "request_hash", "") or ""
        prep_dict = prepared_request.to_dict() if hasattr(prepared_request, "to_dict") else {}
        return str(req_hash), prep_dict

    def safe_ingest(self, ctx: ChunkContext, ingest_fn: Callable[[], Any], target_mode: str) -> Any:
        """Thực thi hàm ingest an toàn với thread lock và bảo toàn extraction_mode gốc của dự án."""
        prev_mode = ctx.project.get("extraction_mode")
        ctx.project["extraction_mode"] = target_mode
        try:
            if ctx.lock:
                with ctx.lock:
                    return ingest_fn()
            return ingest_fn()
        finally:
            if prev_mode is not None:
                ctx.project["extraction_mode"] = prev_mode

    def perform_ingest(self, ctx: ChunkContext, payload: dict, prompt_id: str, target_mode: str) -> dict:
        """Thực thi trích xuất và nạp dữ liệu chuẩn tắc (Entities / Edges) vào dự án."""
        from backend.domain.extraction.validator import ingest_extraction
        from shared.text_utils import uid

        def _do() -> dict:
            return ingest_extraction(
                ctx.project,
                payload,
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

        return self.safe_ingest(ctx, _do, target_mode)
