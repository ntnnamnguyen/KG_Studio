"""Application Service cho phân hệ Training & Active Learning Dataset Exporter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.domain.dataset_exporter.exporter import ActiveLearningExporter
from shared.schemas.training_records import (
    CanonicalizationPairRecord,
    SFTInstructionRecord,
    SRTripletRecord,
)


class TrainingApplicationService:
    """Dịch vụ ứng dụng điều phối xuất dữ liệu huấn luyện và ranh giới tích hợp ML Lab."""

    def __init__(
        self,
        *,
        exporter: ActiveLearningExporter | None = None,
        export_dir: str | Path | None = None,
    ) -> None:
        self.exporter = exporter or ActiveLearningExporter(export_dir=export_dir)

    def export_project(self, project: dict) -> dict[str, Any]:
        """Xuất toàn bộ 3 tập dữ liệu huấn luyện (SR Triplets, Canonicalization, SFT Instructions)."""
        return self.exporter.export_project(project)

    def build_sr_triplets(self, project: dict) -> list[SRTripletRecord]:
        return self.exporter.build_sr_triplets(project)

    def build_canonicalization_pairs(self, project: dict) -> list[CanonicalizationPairRecord]:
        return self.exporter.build_canonicalization_pairs(project)

    def build_sft_instructions(self, project: dict) -> list[SFTInstructionRecord]:
        return self.exporter.build_sft_instructions(project)
