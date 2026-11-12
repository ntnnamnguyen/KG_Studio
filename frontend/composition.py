"""Composition Root cho Frontend (Streamlit UI).
Cung cấp Application Boundaries cho UI components thay vì để components tự khởi tạo
singleton facade/repositories hoặc can thiệp trực tiếp vào save/snapshot sequences.
"""
from __future__ import annotations

import os
from typing import Any

from backend.bootstrap import AppContainer, get_container
from backend.facade import KGStudioFacade, get_facade
from backend.modules.projects.application.service import ProjectsApplicationService
from backend.modules.schema_intelligence.application.service import SchemaIntelligenceApplicationService
from backend.modules.extraction.application.service import ExtractionApplicationService
from backend.modules.curation.application.service import CurationApplicationService
from backend.modules.graph_qa.application.service import GraphQAApplicationService
from backend.modules.training.application.service import TrainingApplicationService


class FrontendComposition:
    """Container dịch vụ dành riêng cho tầng UI."""

    def __init__(
        self,
        container: AppContainer | None = None,
        facade: KGStudioFacade | None = None,
    ) -> None:
        self._container = container or get_container()
        self._facade = facade or get_facade()

    @property
    def projects_service(self) -> ProjectsApplicationService:
        """Dịch vụ ứng dụng phân hệ Dự án."""
        return self._container.projects_service

    @property
    def schema_service(self) -> SchemaIntelligenceApplicationService:
        """Dịch vụ ứng dụng phân hệ Schema Intelligence & EDC."""
        return self._container.schema_service

    @property
    def extraction_service(self) -> ExtractionApplicationService:
        """Dịch vụ ứng dụng phân hệ Extraction, Documents & Prompts."""
        return self._container.extraction_service

    @property
    def curation_service(self) -> CurationApplicationService:
        """Dịch vụ ứng dụng phân hệ Curation, Evidence & Merging."""
        return self._container.curation_service

    @property
    def graph_qa_service(self) -> GraphQAApplicationService:
        """Dịch vụ ứng dụng phân hệ Graph QA, G-Retriever & Export."""
        return self._container.graph_qa_service

    @property
    def training_service(self) -> TrainingApplicationService:
        """Dịch vụ ứng dụng phân hệ Training & Active Learning Dataset Exporter."""
        return self._container.training_service

    @property
    def facade(self) -> KGStudioFacade:
        """Facade nghiệp vụ (sử dụng cho các use case chưa tách module)."""
        return self._facade


_COMPOSITION: FrontendComposition | None = None


def get_ui_composition() -> FrontendComposition:
    """Singleton getter cho Frontend Composition Root."""
    global _COMPOSITION
    if _COMPOSITION is None:
        _COMPOSITION = FrontendComposition()
    return _COMPOSITION
