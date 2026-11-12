"""Composition Root cho toàn bộ hệ thống KG Studio.
Khởi tạo và cấu hình các concrete storage/gateway adapters, inject vào các Application Services.
Không chứa logic nghiệp vụ và không thực hiện I/O nặng khi import.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.integrations.embedder_gateway import EmbedderGateway, default_embedder
from backend.integrations.llm import LLMGateway
from backend.integrations.neo4j_gateway import Neo4jGateway
from backend.modules.projects.application.service import ProjectsApplicationService
from backend.modules.schema_intelligence.application.service import SchemaIntelligenceApplicationService
from backend.modules.extraction.public import ExtractionApplicationService, FreeTriplesEngine
from backend.domain.extraction.registry import EngineRegistry
from backend.modules.curation.application.service import CurationApplicationService
from backend.modules.graph_qa.application.service import GraphQAApplicationService
from backend.modules.training.application.service import TrainingApplicationService
from backend.repositories.json_repo import JsonProjectRepository
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from shared.config_loader import load_config, resolve_path

_CONTAINER: AppContainer | None = None


class AppContainer:
    """Dependency Injection Container (Composition Root)."""

    def __init__(
        self,
        json_repo: JsonProjectRepository | None = None,
        sqlite_repo: SQLiteProjectRepository | None = None,
        vector_repo: VectorIndexRepository | None = None,
        embedder_gateway: EmbedderGateway | None = None,
        neo4j_gateway: Neo4jGateway | None = None,
    ) -> None:
        cfg = load_config()
        storage_cfg = cfg.get("storage", {}) if isinstance(cfg.get("storage"), dict) else {}
        self.data_dir = resolve_path(storage_cfg.get("data_dir", cfg.get("data_dir", "data")))
        self.projects_dir = resolve_path(storage_cfg.get("projects_dir", cfg.get("projects_dir", "data/projects")))
        self.db_path = resolve_path(storage_cfg.get("sqlite_db", cfg.get("sqlite_db", "data/kg_studio.db")))
        self.vector_indices_dir = resolve_path(storage_cfg.get("vector_indices_dir", cfg.get("vector_index_dir", "data/vector_indices")))
        self.training_exports_dir = resolve_path(storage_cfg.get("training_exports_dir", cfg.get("training_exports_dir", "data/training_exports")))
        self.model_registry_dir = resolve_path(storage_cfg.get("model_registry_dir", cfg.get("model_registry_dir", "data/model_registry")))

        self.json_repo = json_repo or JsonProjectRepository(self.projects_dir)
        self.sqlite_repo = sqlite_repo or SQLiteProjectRepository(self.db_path)
        self.vector_repo = vector_repo or VectorIndexRepository(index_root=self.vector_indices_dir)
        self.embedder_gateway = embedder_gateway or default_embedder
        self.neo4j_gateway = neo4j_gateway or Neo4jGateway()
        self.llm_gateway = LLMGateway

        # Application Services
        self.projects_service = ProjectsApplicationService(
            project_store=self.json_repo,
            read_projection=self.sqlite_repo,
            vector_repo=self.vector_repo,
        )
        self.schema_service = SchemaIntelligenceApplicationService(
            commit_coordinator=self.projects_service.commit_coordinator,
            vector_repo=self.vector_repo,
        )
        extraction_registry = EngineRegistry()
        extraction_registry.register(FreeTriplesEngine(llm_gateway=self.llm_gateway))
        self.extraction_service = ExtractionApplicationService(
            engine_registry=extraction_registry,
            llm_gateway=self.llm_gateway,
            schema_service=self.schema_service,
            project_store=self.json_repo,
            commit_coordinator=self.projects_service.commit_coordinator,
        )
        self.curation_service = CurationApplicationService(
            commit_coordinator=self.projects_service.commit_coordinator,
            project_store=self.json_repo,
        )
        self.graph_qa_service = GraphQAApplicationService(
            neo4j_gateway=self.neo4j_gateway,
            baseline_source=self.extraction_service,
        )
        self.training_service = TrainingApplicationService(
            export_dir=self.training_exports_dir,
        )


def get_container() -> AppContainer:
    """Trả về singleton container của hệ thống."""
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = AppContainer()
    return _CONTAINER


def reset_container(container: AppContainer | None = None) -> AppContainer | None:
    """Reset singleton container (dùng trong kiểm thử cô lập)."""
    global _CONTAINER
    prev = _CONTAINER
    _CONTAINER = container
    return prev
