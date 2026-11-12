"""Ports cho phân hệ Curation, Evidence & Entity/Relation Merging."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CurationLLMPort(Protocol):
    """Port giao tiếp LLM phục vụ phân cụm ngữ nghĩa (Semantic Clustering)."""

    def generate(self, prompt: str, **kwargs: Any) -> str:
        ...
