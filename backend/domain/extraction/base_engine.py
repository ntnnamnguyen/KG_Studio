"""Giao diện chuẩn (Strategy Pattern) cho các Bộ Trích xuất Tri thức (Extraction Engines)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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

