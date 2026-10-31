"""Mô hình dữ liệu cho Quản lý Phiên bản Prompt, Xem trước và Chuẩn bị Request LLM."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PromptVersionDTO:
    id: str
    configuration_id: str
    mode: str
    version: int
    content: str
    content_hash: str
    created_at: str
    created_by: str = "local_user"
    note: str = ""
    parent_version_id: str | None = None
    restored_from_version_id: str | None = None
    origin: str = "human"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PromptVersionDTO:
        raw = data or {}
        return cls(
            id=str(raw.get("id", "")),
            configuration_id=str(raw.get("configuration_id", "")),
            mode=str(raw.get("mode", raw.get("configuration_id", ""))),
            version=int(raw.get("version", 1)),
            content=str(raw.get("content", "")),
            content_hash=str(raw.get("content_hash", "")),
            created_at=str(raw.get("created_at", "")),
            created_by=str(raw.get("created_by", "local_user")),
            note=str(raw.get("note", "")),
            parent_version_id=raw.get("parent_version_id"),
            restored_from_version_id=raw.get("restored_from_version_id"),
            origin=str(raw.get("origin", "human")),
        )


@dataclass
class PromptSaveRequestDTO:
    project_id: str
    configuration_id: str
    content: str
    note: str = ""
    created_by: str = "local_user"
    expected_revision: str | None = None
    request_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PromptSaveRequestDTO:
        raw = data or {}
        return cls(
            project_id=str(raw.get("project_id", "")),
            configuration_id=str(raw.get("configuration_id", "")),
            content=str(raw.get("content", "")),
            note=str(raw.get("note", "")),
            created_by=str(raw.get("created_by", "local_user")),
            expected_revision=raw.get("expected_revision"),
            request_id=str(raw.get("request_id", "")),
        )


@dataclass
class PromptPreviewRequestDTO:
    project_id: str
    configuration_id: str
    doc_id: str
    chunk_number: int = 1
    version_id: str | None = None
    draft_content: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str = ""
    temperature: float = 0.0
    max_tokens: int = 8192
    max_input_tokens: int = 16000

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PromptPreviewRequestDTO:
        raw = data or {}
        return cls(
            project_id=str(raw.get("project_id", "")),
            configuration_id=str(raw.get("configuration_id", "")),
            doc_id=str(raw.get("doc_id", "")),
            chunk_number=int(raw.get("chunk_number", 1)),
            version_id=raw.get("version_id"),
            draft_content=raw.get("draft_content"),
            provider=raw.get("provider"),
            model=raw.get("model"),
            base_url=str(raw.get("base_url", "")),
            temperature=float(raw.get("temperature", 0.0) or 0.0),
            max_tokens=int(raw.get("max_tokens", 8192)),
            max_input_tokens=int(raw.get("max_input_tokens", 16000)),
        )


@dataclass
class PreparedExtractionRequestDTO:
    project_id: str
    configuration_id: str
    mode: str
    prompt_version_id: str
    prompt_content_hash: str
    base_instructions: str
    appended_content: str = ""
    system_prompt: str = ""
    user_message: str = ""
    raw_chunk_text: str = ""
    fitted_chunk_text: str = ""
    raw_chars: int = 0
    fitted_chars: int = 0
    allowed_relations: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 8192
    max_input_tokens: int = 16000
    response_format: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    loop_index: int = 1
    request_hash: str = ""
    is_draft: bool = False
    retrieval_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PreparedExtractionRequestDTO:
        raw = data or {}
        return cls(
            project_id=str(raw.get("project_id", "")),
            configuration_id=str(raw.get("configuration_id", "")),
            mode=str(raw.get("mode", raw.get("configuration_id", ""))),
            prompt_version_id=str(raw.get("prompt_version_id", "")),
            prompt_content_hash=str(raw.get("prompt_content_hash", "")),
            base_instructions=str(raw.get("base_instructions", "")),
            appended_content=str(raw.get("appended_content", "")),
            system_prompt=str(raw.get("system_prompt", "")),
            user_message=str(raw.get("user_message", "")),
            raw_chunk_text=str(raw.get("raw_chunk_text", "")),
            fitted_chunk_text=str(raw.get("fitted_chunk_text", "")),
            raw_chars=int(raw.get("raw_chars", 0)),
            fitted_chars=int(raw.get("fitted_chars", 0)),
            allowed_relations=list(raw.get("allowed_relations", [])),
            provider=str(raw.get("provider", "")),
            model=str(raw.get("model", "")),
            temperature=float(raw.get("temperature", 0.0) or 0.0),
            max_tokens=int(raw.get("max_tokens", 8192)),
            max_input_tokens=int(raw.get("max_input_tokens", 16000)),
            response_format=dict(raw.get("response_format", {})),
            warnings=list(raw.get("warnings", [])),
            loop_index=int(raw.get("loop_index", 1)),
            request_hash=str(raw.get("request_hash", "")),
            is_draft=bool(raw.get("is_draft", False)),
            retrieval_summary=dict(raw.get("retrieval_summary", {})),
        )

