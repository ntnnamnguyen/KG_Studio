"""Tầng Data Transfer Objects (DTOs) dùng chung cho toàn hệ thống."""
from __future__ import annotations

from .curation import (
    CurationPreviewDTO,
    CurationQueryDTO,
    CurationResultDTO,
    CurationReviewRequestDTO,
    EdgeEditRequestDTO,
    EdgeReviewDecisionDTO,
    EntityEditRequestDTO,
    EntityMergePreviewDTO,
    EntityMergeRequestDTO,
)
from .edc import (
    AlignmentCandidateDTO,
    BulkReviewPreviewDTO,
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
    ProposalDecisionDTO,
    SchemaProposalDTO,
)
from .graph import EdgeDTO, EvidenceDTO, NodeDTO, StepTraceDTO
from .project import EDCPlusRSettingsDTO, ProjectSummaryDTO
from .prompts import (
    PreparedExtractionRequestDTO,
    PromptPreviewRequestDTO,
    PromptSaveRequestDTO,
    PromptVersionDTO,
)
from .queries import EdgeRowDTO, NodeRowDTO, PageDTO, ProjectHeaderDTO, ProposalRowDTO
from .training_records import CanonicalizationPairRecord, SFTInstructionRecord, SRTripletRecord

__all__ = [
    "AlignmentCandidateDTO",
    "BulkReviewPreviewDTO",
    "BulkReviewRequestDTO",
    "BulkReviewResultDTO",
    "CanonicalizationPairRecord",
    "CurationPreviewDTO",
    "CurationQueryDTO",
    "CurationResultDTO",
    "CurationReviewRequestDTO",
    "EDCPlusRSettingsDTO",
    "EdgeDTO",
    "EdgeEditRequestDTO",
    "EdgeReviewDecisionDTO",
    "EdgeRowDTO",
    "EntityEditRequestDTO",
    "EntityMergePreviewDTO",
    "EntityMergeRequestDTO",
    "EvidenceDTO",
    "NodeDTO",
    "NodeRowDTO",
    "PageDTO",
    "PreparedExtractionRequestDTO",
    "ProjectHeaderDTO",
    "ProjectSummaryDTO",
    "PromptPreviewRequestDTO",
    "PromptSaveRequestDTO",
    "PromptVersionDTO",
    "ProposalDecisionDTO",
    "ProposalRowDTO",
    "SFTInstructionRecord",
    "SRTripletRecord",
    "SchemaProposalDTO",
    "StepTraceDTO",
]
