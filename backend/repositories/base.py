"""Giao diện trừu tượng (Repository Interface) cho tầng lưu trữ Dự án."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class ProjectRepository(ABC):
    @abstractmethod
    def list_projects(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def load_project(self, name: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    def save_project(self, project: dict) -> Path | str:
        raise NotImplementedError

