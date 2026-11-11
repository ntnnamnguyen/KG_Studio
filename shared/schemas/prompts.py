"""Mô hình dữ liệu cho Quản lý Phiên bản Prompt, Xem trước và Chuẩn bị Request LLM (Pydantic v2)."""
from __future__ import annotations

from typing import Any
from pydantic import Field

from shared.schemas.base import SchemaModel


class PromptVersionDTO(SchemaModel):
    id: str = ""
    configuration_id: str = ""
    mode: str = ""
    version: int = 1
    content: str = ""
    content_hash: str = ""
    created_at: str = ""
    created_by: str = "local_user"
    note: str = ""
    parent_version_id: str | None = None
    restored_from_version_id: str | None = None
    origin: str = "human"


class PromptSaveRequestDTO(SchemaModel):
    project_id: str = ""
    configuration_id: str = ""
    content: str = ""
    note: str = ""
    created_by: str = "local_user"
    expected_revision: str | None = None
    request_id: str = ""


class PromptPreviewRequestDTO(SchemaModel):
    project_id: str = ""
    configuration_id: str = ""
    doc_id: str = ""
    chunk_number: int = 1
    version_id: str | None = None
    draft_content: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str = ""
    temperature: float = 0.0
    max_tokens: int = 8192
    max_input_tokens: int = 16000


class PreparedExtractionRequestDTO(SchemaModel):
    project_id: str = ""
    configuration_id: str = ""
    mode: str = ""
    prompt_version_id: str = ""
    prompt_content_hash: str = ""
    base_instructions: str = ""
    appended_content: str = ""
    system_prompt: str = ""
    user_message: str = ""
    raw_chunk_text: str = ""
    fitted_chunk_text: str = ""
    raw_chars: int = 0
    fitted_chars: int = 0
    allowed_relations: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 8192
    max_input_tokens: int = 16000
    response_format: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    loop_index: int = 1
    request_hash: str = ""
    is_draft: bool = False
    retrieval_summary: dict[str, Any] = Field(default_factory=dict)
