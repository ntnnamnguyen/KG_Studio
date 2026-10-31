"""Tầng Data Transfer Objects (DTOs) dùng chung cho toàn hệ thống."""
from __future__ import annotations

from .edc import AlignmentCandidateDTO, SchemaProposalDTO
from .graph import EdgeDTO, EvidenceDTO, NodeDTO, StepTraceDTO
from .project import EDCPlusRSettingsDTO, ProjectSummaryDTO
from .prompts import (
    PreparedExtractionRequestDTO,
    PromptPreviewRequestDTO,
    PromptSaveRequestDTO,
    PromptVersionDTO,
)
from .training_records import CanonicalizationPairRecord, SFTInstructionRecord, SRTripletRecord

__all__ = [
    "AlignmentCandidateDTO",
    "CanonicalizationPairRecord",
    "EDCPlusRSettingsDTO",
    "EdgeDTO",
    "EvidenceDTO",
    "NodeDTO",
    "PreparedExtractionRequestDTO",
    "ProjectSummaryDTO",
    "PromptPreviewRequestDTO",
    "PromptSaveRequestDTO",
    "PromptVersionDTO",
    "SFTInstructionRecord",
    "SRTripletRecord",
    "SchemaProposalDTO",
    "StepTraceDTO",
]

