"""Quản lý tiến trình ngầm (Background Jobs / Workers)."""
from __future__ import annotations

from .job_manager import JobManager, default_job_manager

__all__ = ["JobManager", "default_job_manager"]

