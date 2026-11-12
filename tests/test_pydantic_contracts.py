"""Contract tests cho Pydantic v2 models (Gate P6).
Kiểm tra:
1. Unknown fields (extra='ignore' không làm crash DTO).
2. Default / optional / None handling.
3. Serialization & Deserialization parity (.to_dict() / .from_dict() vs model_dump() / model_validate()).
4. Unicode và ký tự đặc biệt tiếng Việt.
5. List ordering và ID integrity.
"""
from __future__ import annotations

import unittest

from shared.schemas.curation import (
    CurationResultDTO,
    CurationReviewRequestDTO,
    EntityMergeRequestDTO,
)
from shared.schemas.edc import (
    BulkReviewRequestDTO,
    BulkReviewResultDTO,
    ProposalDecisionDTO,
)


class TestPydanticContracts(unittest.TestCase):
    def test_01_extra_fields_ignored_safely(self) -> None:
        raw_payload = {
            "project_id": "proj_abc",
            "kind": "entity_types",
            "request_id": "req_123",
            "UNKNOWN_EXTRA_FIELD": "some_value",
            "FUTURE_METADATA": {"nested": True},
            "decisions": [
                {
                    "proposal_id": "p_01",
                    "action": "approve",
                    "canonical_name": "Đình làng",
                    "EXTRA_IN_DECISION": 999,
                }
            ],
        }
        # Deserialization must succeed without raising ValidationError
        dto = BulkReviewRequestDTO.from_dict(raw_payload)
        self.assertEqual(dto.project_id, "proj_abc")
        self.assertEqual(len(dto.decisions), 1)
        self.assertEqual(dto.decisions[0].canonical_name, "Đình làng")

    def test_02_unicode_and_vietnamese_characters_preserved(self) -> None:
        vietnamese_text = "Thành phố Đà Nẵng — Di tích lịch sử & Văn hóa Cố đô Huế"
        req = EntityMergeRequestDTO(
            project_id="pid_vn",
            keep_id="node_hue",
            member_ids=["node_hue", "node_danang"],
            canonical_name=vietnamese_text,
            canonical_description="Mô tả di tích có dấu tiếng Việt chuẩn: ă, â, đ, ê, ô, ơ, ư",
        )
        as_dict = req.to_dict()
        self.assertEqual(as_dict["canonical_name"], vietnamese_text)
        reloaded = EntityMergeRequestDTO.from_dict(as_dict)
        self.assertEqual(reloaded.canonical_name, vietnamese_text)
        self.assertEqual(reloaded.canonical_description, req.canonical_description)

    def test_03_default_and_none_values(self) -> None:
        res = BulkReviewResultDTO(
            batch_id="b1",
            request_id="r1",
            applied_count=5,
        )
        self.assertEqual(res.status, "")
        self.assertEqual(res.sync_status, "synced")
        self.assertEqual(res.vector_index_status, "valid")
        self.assertEqual(res.item_results, [])

        res_dict = res.to_dict()
        self.assertEqual(res_dict["applied_count"], 5)
        self.assertEqual(res_dict["sync_status"], "synced")

    def test_04_list_ordering_preserved(self) -> None:
        pids = [f"e_{i}" for i in [5, 2, 8, 1, 9]]
        res = BulkReviewResultDTO(
            batch_id="b_order",
            affected_edge_ids=pids,
        )
        as_dict = res.to_dict()
        self.assertEqual(as_dict["affected_edge_ids"], pids)
        reloaded = BulkReviewResultDTO.from_dict(as_dict)
        self.assertEqual(reloaded.affected_edge_ids, pids)


if __name__ == "__main__":
    unittest.main()
