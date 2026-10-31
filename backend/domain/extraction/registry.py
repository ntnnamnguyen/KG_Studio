"""Registry quản lý các Extraction Engines theo thiết kế Pluggable."""
from __future__ import annotations

from .base_engine import BaseExtractionEngine
from .engines.edc_one_pass import EDCOnePassEngine
from .engines.edc_plus_r import EDCPlusREngine
from .engines.fixed_catalog import FixedCatalogEngine


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, BaseExtractionEngine] = {}
        self.register(FixedCatalogEngine())
        self.register(EDCOnePassEngine())
        self.register(EDCPlusREngine())

    def register(self, engine: BaseExtractionEngine) -> None:
        self._engines[engine.mode_id] = engine

    def get(self, mode_id: str) -> BaseExtractionEngine:
        clean = (mode_id or "closed").strip()
        if clean not in self._engines:
            return self._engines["closed"]
        return self._engines[clean]

    def available_modes(self) -> list[dict]:
        return [{"mode_id": eng.mode_id, "display_name": eng.display_name} for eng in self._engines.values()]


default_registry = EngineRegistry()

