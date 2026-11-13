"""Public API cho phân hệ Projects (Modular Monolith)."""
from __future__ import annotations

from .application.commit_coordinator import ProjectCommitCoordinator
from .application.service import ProjectsApplicationService
from .ports import CommitCoordinatorPort, ProjectStorePort, ReadProjectionPort

__all__ = [
    "ProjectsApplicationService",
    "ProjectCommitCoordinator",
    "CommitCoordinatorPort",
    "ProjectStorePort",
    "ReadProjectionPort",
]
