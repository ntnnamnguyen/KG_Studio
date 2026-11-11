"""Lớp cơ sở SchemaModel tương thích Pydantic v2 và bảo toàn to_dict / from_dict."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict


class SchemaModel(BaseModel):
    """Lớp cơ sở kế thừa Pydantic v2 BaseModel cho toàn bộ DTO trong KG Studio.
    
    Tự động hỗ trợ:
    - Rust-powered validation và type coercion từ Pydantic v2.
    - Phương thức .to_dict() tương đương .model_dump().
    - Phương thức .from_dict(data) tương đương .model_validate(data).
    - ConfigDict(extra='ignore') tự động bỏ qua các trường thừa mà không gây lỗi.
    """
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Any):
        if data is None:
            return cls()
        if isinstance(data, cls):
            return data
        if isinstance(data, dict):
            return cls.model_validate(data)
        return cls.model_validate(data)
