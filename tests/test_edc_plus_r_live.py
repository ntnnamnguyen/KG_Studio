"""Test kịch bản toàn diện luồng EDC + R (Iterative Refinement + Schema Retrieval + Target Alignment)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.domain.catalogs.service import apply_relations
from backend.domain.extraction.base_engine import ChunkContext
from backend.domain.extraction.engines.edc_plus_r import EDCPlusREngine
from shared.constants import MODE_EDC_PLUS_R
from shared.schemas.project import EDCPlusRSettingsDTO
from tests.test_standalone_architecture import FakeOpenAIClient


class TestEDCPlusRLive(unittest.TestCase):
    def test_edc_plus_r_full_lifecycle(self):
        project = {
            "project_id": "test_edc_plus_r_lifecycle",
            "name": "Test EDC+R Lifecycle",
            "extraction_mode": MODE_EDC_PLUS_R,
            "edc_plus_r_settings": EDCPlusRSettingsDTO(
                embedder_model="hybrid_vn:default",
                top_k_relations=5,
                top_k_entity_types=5,
                auto_align_threshold=0.85,
                candidate_threshold=0.45,
                refinement_loops=2,
                enable_llm_verifier=False,
            ).to_dict(),
            "entity_types": [
                {
                    "name": "di_tích",
                    "description": "Công trình lịch sử.",
                    "definition": "Di tích lịch sử, kiến trúc, văn hóa nghệ thuật.",
                },
                {
                    "name": "địa_điểm",
                    "description": "Địa danh hành chính.",
                    "definition": "Tỉnh, thành phố, quận huyện, làng xã.",
                },
                {
                    "name": "nhân_vật",
                    "description": "Nhân vật lịch sử.",
                    "definition": "Vua, tướng lĩnh, anh hùng dân tộc.",
                },
            ],
            "relations": [],
            "schema_proposals": [],
            "nodes": [],
            "edges": [],
            "documents": [],
        }

        # 1. Khởi tạo Catalog chuẩn (Canonical Schema)
        apply_relations(
            project,
            [
                {
                    "name": "tọa_lạc_tại",
                    "description": "Vị trí địa lý của di tích.",
                    "definition": "Di tích nguồn có vị trí tọa lạc tại địa điểm hoặc khu vực đích.",
                },
                {
                    "name": "xây_dựng_năm",
                    "description": "Năm khởi dựng.",
                    "definition": "Công trình kiến trúc được xây dựng hoặc khởi công vào năm đích.",
                },
                {
                    "name": "thờ_phụng",
                    "description": "Đối tượng được thờ.",
                    "definition": "Di tích nguồn là nơi thờ phụng nhân vật lịch sử hoặc thần linh đích.",
                },
            ],
        )

        # 2. Tạo tài liệu trích xuất
        doc_text = (
            "Đền thờ Hoàng đế Quang Trung tọa lạc tại xứ Đống Đa, Hà Nội. "
            "Công trình được xây dựng vào năm 1989 để kỷ niệm 200 năm chiến thắng Ngọc Hồi - Đống Đa. "
            "Nơi đây là điểm thờ phụng Hoàng đế Quang Trung cùng các tướng lĩnh nghĩa quân Tây Sơn."
        )
        doc = {"id": "doc_01", "name": "quang_trung.txt", "text": doc_text}
        project["documents"].append(doc)
        chunk_rec = {
            "chunk_number": 1,
            "text": doc_text,
            "start_char": 0,
            "end_char": len(doc_text),
            "page_from": 1,
            "chunk_hash": "ch_01",
        }

        # 3. Giả lập 2 vòng lặp Refinement LLM
        # Vòng 1: Rút 2 quan hệ:
        #   - 'tọa_lạc_tại' (đã có trong catalog)
        #   - 'xây_dựng_vào_năm' (chưa có, ngữ nghĩa gần với 'xây_dựng_năm' -> kỳ vọng auto-align)
        loop1 = {
            "thuc_the": [
                {"ten": "Đền thờ Hoàng đế Quang Trung", "loai": "di_tích", "mo_ta": "Công trình kỷ niệm"},
                {"ten": "xứ Đống Đa", "loai": "địa_điểm", "mo_ta": "Địa danh lịch sử"},
                {"ten": "1989", "loai": "mốc_thời_gian", "mo_ta": "Năm khánh thành"},
            ],
            "quan_he": [
                {
                    "nguon": "Đền thờ Hoàng đế Quang Trung",
                    "quan_he": "tọa_lạc_tại",
                    "dich": "xứ Đống Đa",
                    "trich_dan": "Đền thờ Hoàng đế Quang Trung tọa lạc tại xứ Đống Đa",
                },
                {
                    "nguon": "Đền thờ Hoàng đế Quang Trung",
                    "quan_he": "xây_dựng_vào_năm",
                    "dich": "1989",
                    "trich_dan": "Công trình được xây dựng vào năm 1989",
                },
            ],
            "dinh_nghia_quan_he": [
                {
                    "ten": "xây_dựng_vào_năm",
                    "dinh_nghia": "Công trình kiến trúc được xây dựng hoặc khánh thành vào năm đích.",
                },
            ],
            "dinh_nghia_loai": [
                {"ten": "mốc_thời_gian", "dinh_nghia": "Năm, tháng hoặc thời kỳ diễn ra sự kiện."},
            ],
        }

        # Vòng 2: Mở rộng tiếp:
        #   - 'thờ_tự' (gần với 'thờ_phụng' -> kỳ vọng auto-align hoặc suggest)
        #   - 'kỷ_niệm_sự_kiện' (quan hệ mới hoàn toàn -> novel proposal)
        loop2 = {
            "thuc_the": loop1["thuc_the"]
            + [
                {"ten": "Hoàng đế Quang Trung", "loai": "nhân_vật", "mo_ta": "Vị anh hùng dân tộc"},
                {
                    "ten": "chiến thắng Ngọc Hồi - Đống Đa",
                    "loai": "sự_kiện_lịch_sử",
                    "mo_ta": "Chiến thắng mùa xuân Kỷ Dậu 1789",
                },
            ],
            "quan_he": loop1["quan_he"]
            + [
                {
                    "nguon": "Đền thờ Hoàng đế Quang Trung",
                    "quan_he": "thờ_tự",
                    "dich": "Hoàng đế Quang Trung",
                    "trich_dan": "Nơi đây là điểm thờ phụng Hoàng đế Quang Trung",
                },
                {
                    "nguon": "Đền thờ Hoàng đế Quang Trung",
                    "quan_he": "kỷ_niệm_sự_kiện",
                    "dich": "chiến thắng Ngọc Hồi - Đống Đa",
                    "trich_dan": "kỷ niệm 200 năm chiến thắng Ngọc Hồi - Đống Đa",
                },
            ],
            "dinh_nghia_quan_he": loop1["dinh_nghia_quan_he"]
            + [
                {
                    "ten": "thờ_tự",
                    "dinh_nghia": "Di tích nguồn là nơi phụng thờ, tưởng nhớ nhân vật hoặc danh nhân đích.",
                },
                {
                    "ten": "kỷ_niệm_sự_kiện",
                    "dinh_nghia": "Công trình được tạo dựng nhằm tri ân, ghi nhớ chiến công hoặc biến cố lịch sử đích.",
                },
            ],
            "dinh_nghia_loai": loop1["dinh_nghia_loai"]
            + [
                {
                    "ten": "sự_kiện_lịch_sử",
                    "dinh_nghia": "Chiến dịch, biến cố hay phong trào lịch sử trong quá khứ.",
                },
            ],
        }

        fake_client = FakeOpenAIClient([loop1, loop2])
        engine = EDCPlusREngine()

        ctx = ChunkContext(
            project=project,
            document=doc,
            chunk_record=chunk_rec,
            provider="OpenAI / API tương thích",
            api_key="test",
            model="gpt-4o-mini",
            client=fake_client,
        )

        out = engine.process_chunk(ctx)

        # 4. Kiểm tra các bước thực thi (Step Traces)
        self.assertEqual(len(fake_client.chat.completions.calls), 2)
        self.assertEqual(len(out.step_traces), 5)  # 2 SR loops + 2 Ext loops + 1 Align step

        # Kiểm tra bước 1: Schema Retrieval
        sr_steps = [s for s in out.step_traces if "Schema Retrieval" in s["step_name"]]
        self.assertEqual(len(sr_steps), 2)
        # Vòng 2 có entity hints được truyền từ vòng 1
        self.assertTrue(len(sr_steps[1]["details"]["entity_hints"]) > 0)

        # Kiểm tra đồ thị sau khi Ingest
        self.assertEqual(len(project["nodes"]), 5)
        self.assertEqual(len(project["edges"]), 4)

        # Kiểm tra Target Alignment
        align_summary = out.alignment_summary
        self.assertIn("auto_aligned", align_summary)
        self.assertIn("suggested_for_review", align_summary)
        self.assertIn("novel_proposals", align_summary)

        # Kiểm tra đề xuất quan hệ
        proposals = {p["name"]: p for p in project["schema_proposals"]}
        self.assertIn("xây_dựng_vào_năm", proposals)
        self.assertIn("kỷ_niệm_sự_kiện", proposals)

        # Kiểm tra rằng cạnh có quan hệ auto-align đã được cập nhật hoặc có candidate
        edge_relations = sorted(str(e["relation"]) for e in project["edges"])
        self.assertGreater(len(edge_relations), 0)
        self.assertIn("tọa_lạc_tại", edge_relations)


if __name__ == "__main__":
    unittest.main()
