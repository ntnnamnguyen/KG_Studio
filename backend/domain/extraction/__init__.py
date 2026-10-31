"""Phân hệ điều phối Trích xuất (Pluggable Extraction Engines)."""
from __future__ import annotations

from .base_engine import BaseExtractionEngine, ChunkContext, EngineOutput
from .registry import EngineRegistry, default_registry
from .validator import cache_key, ensure_node, ingest_extraction, validate_extraction

__all__ = [
    "BaseExtractionEngine",
    "ChunkContext",
    "EngineOutput",
    "EngineRegistry",
    "cache_key",
    "default_registry",
    "ensure_node",
    "ingest_extraction",
    "validate_extraction",
]

