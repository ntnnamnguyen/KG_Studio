"""Ports cho phân hệ Extraction, Documents & Prompts."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput


@runtime_checkable
class DocumentParserPort(Protocol):
    """Port trích xuất nội dung từ tệp tài liệu thô."""

    def parse(self, file_path: str, file_name: str) -> str:
        ...


@runtime_checkable
class LLMExtractionPort(Protocol):
    """Port giao tiếp LLM phục vụ trích xuất tri thức."""

    def extract(self, *args: Any, **kwargs: Any) -> Any:
        ...

    def prepare_extraction_request(self, *args: Any, **kwargs: Any) -> Any:
        ...
