"""Tổng hợp tất cả các API Routers cho FastAPI."""
from __future__ import annotations

from fastapi import APIRouter

from .curation import router as curation_router
from .edc import router as edc_router
from .extraction import router as extraction_router
from .graph import router as graph_router
from .projects import router as projects_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(projects_router)
api_v1_router.include_router(extraction_router)
api_v1_router.include_router(edc_router)
api_v1_router.include_router(curation_router)
api_v1_router.include_router(graph_router)

__all__ = ["api_v1_router"]
