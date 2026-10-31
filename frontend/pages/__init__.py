"""Tầng các trang màn hình độc lập (Pages Layer) của KG Studio Pro."""
from __future__ import annotations

from .p01_projects_docs import render_projects_docs_page
from .p02_catalogs_prompts import render_catalogs_prompts_page
from .p03_extraction import render_extraction_page
from .p04_curation_hub import render_curation_hub_page
from .p04_edc_alignment import render_edc_alignment_page
from .p05_curation_merge import render_curation_merge_page
from .p06_graph_export import render_graph_export_page

__all__ = [
    "render_catalogs_prompts_page",
    "render_curation_hub_page",
    "render_curation_merge_page",
    "render_edc_alignment_page",
    "render_extraction_page",
    "render_graph_export_page",
    "render_projects_docs_page",
]
