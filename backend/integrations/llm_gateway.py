"""Lớp tương thích ngược: mã nguồn đã chuyển sang gói ``backend.integrations.llm``.

Giữ file này để các import cũ (``from backend.integrations.llm_gateway import LLMGateway``) tiếp tục chạy.
Mã mới nên import trực tiếp từ ``backend.integrations.llm``.
"""
from __future__ import annotations

from backend.integrations.llm import *  # noqa: F401,F403
from backend.integrations.llm import __all__  # noqa: F401
from backend.integrations.llm.errors import classify_error as _classify  # noqa: F401
