"""Kiểm thử chuẩn hóa quan hệ tiếng Việt tự nhiên (Clean Relation Name) trong trích xuất EDC mở."""
import unittest

from backend.domain.catalogs.service import prepare_edc
from backend.domain.extraction.validator import ingest_extraction, validate_extraction
from shared.constants import MODE_EDC
from shared.text_utils import clean_relation_name


class TestRelationCleaning(unittest.TestCase):
    def test_clean_relation_name_user_cases(self):
        """Kiểm tra chính xác 7 trường hợp người dùng phản ánh."""
        cases = {
            "có_tầng_2_diện_tích": "có tầng 2 diện tích",
            "cần_sự_đồng_ý_của": "cần sự đồng ý",
            "cần_đi_kèm": "cần đi kèm",
            "dự_kiến_ban_đầu_là": "dự kiến ban đầu",
            "dự_kiến_vốn_ban_đầu_là": "dự kiến vốn ban đầu",
            "giảm giá cho": "giảm giá",
            "giới_thiệu_về": "giới thiệu",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_relation_name(raw), expected)

    def test_clean_relation_name_edge_cases(self):
        """Kiểm tra các trường hợp biên, từ đơn, từ bảo vệ."""
        self.assertEqual(clean_relation_name(""), "")
        self.assertEqual(clean_relation_name("   "), "")
        self.assertEqual(clean_relation_name("CẦN_SỰ_ĐỒNG_Ý_CỦA"), "cần sự đồng ý")
        self.assertEqual(clean_relation_name("giới_thiệu_về_"), "giới thiệu")

        # Từ đơn không được xóa rỗng
        self.assertEqual(clean_relation_name("là"), "là")
        self.assertEqual(clean_relation_name("của"), "của")
        self.assertEqual(clean_relation_name("về"), "về")
        self.assertEqual(clean_relation_name("cho"), "cho")

        # Cụm từ bảo vệ
        self.assertEqual(clean_relation_name("thuộc về"), "thuộc về")
        self.assertEqual(clean_relation_name("trở về"), "trở về")
        self.assertEqual(clean_relation_name("quay về"), "quay về")
        self.assertEqual(clean_relation_name("hướng về"), "hướng về")

        # Các giới từ khác được bảo tồn
        self.assertEqual(clean_relation_name("tọa lạc tại"), "tọa lạc tại")
        self.assertEqual(clean_relation_name("kết hôn với"), "kết hôn với")
        self.assertEqual(clean_relation_name("đi đến"), "đi đến")

    def test_validate_extraction_cleans_open_mode(self):
        """Khi chạy open_mode=True, validate_extraction tự động làm sạch tên quan hệ."""
        raw_extraction = {
            "thuc_the": [
                {"ten": "Dự án A", "loai": "Dự án", "mo_ta": "Mô tả A"},
                {"ten": "Bộ phận B", "loai": "Tổ chức", "mo_ta": "Mô tả B"},
            ],
            "quan_he": [
                {
                    "nguon": "Dự án A",
                    "quan_he": "cần_sự_đồng_ý_của",
                    "dich": "Bộ phận B",
                    "trich_dan": "Dự án A cần sự đồng ý của Bộ phận B để triển khai.",
                },
                {
                    "nguon": "Dự án A",
                    "quan_he": "dự_kiến_ban_đầu_là",
                    "dich": "Bộ phận B",
                    "trich_dan": "Dự án A cần sự đồng ý của Bộ phận B để triển khai.",
                },
            ],
        }
        chunk = "Dự án A cần sự đồng ý của Bộ phận B để triển khai."
        clean, report = validate_extraction(raw_extraction, chunk, allowed_relations=[], open_mode=True)

        self.assertEqual(report["invalid_relations"], 0)
        self.assertEqual(len(clean["quan_he"]), 2)
        self.assertEqual(clean["quan_he"][0]["quan_he"], "cần sự đồng ý")
        self.assertEqual(clean["quan_he"][1]["quan_he"], "dự kiến ban đầu")

    def test_ingest_extraction_and_proposal_creation(self):
        """Kiểm tra toàn bộ luồng ingest_extraction và đề xuất schema EDC."""
        project = {
            "project_id": "test_clean_proj",
            "name": "Test Project",
            "extraction_mode": MODE_EDC,
            "relations": [],
            "entity_types": [],
            "nodes": [],
            "edges": [],
            "schema_proposals": [],
        }
        document = {"id": "doc_1", "name": "TaiLieu.txt"}
        chunk_text = "Hợp đồng này cần sự đồng ý của Ban Giám Đốc."
        extraction = {
            "thuc_the": [
                {"ten": "Hợp đồng này", "loai": "Văn bản", "mo_ta": ""},
                {"ten": "Ban Giám Đốc", "loai": "Tổ chức", "mo_ta": ""},
            ],
            "quan_he": [
                {
                    "nguon": "Hợp đồng này",
                    "quan_he": "cần_sự_đồng_ý_của",
                    "dich": "Ban Giám Đốc",
                    "trich_dan": "cần sự đồng ý của Ban Giám Đốc",
                }
            ],
            "dinh_nghia_quan_he": [
                {"ten": "cần_sự_đồng_ý_của", "dinh_nghia": "Yêu cầu có sự phê duyệt trước khi ký"}
            ],
            "dinh_nghia_loai": [
                {"ten": "Văn bản", "dinh_nghia": "Tài liệu giấy tờ"},
                {"ten": "Tổ chức", "dinh_nghia": "Cơ quan đơn vị"},
            ],
        }

        stats = ingest_extraction(
            project,
            extraction,
            document,
            chunk_text,
            chunk_number=1,
            model="test-model",
            prompt_id="prompt-1",
        )

        self.assertEqual(stats["added_edges"], 1)
        # Cạnh trong đồ thị đã được làm sạch
        edge = project["edges"][0]
        self.assertEqual(edge["relation"], "cần sự đồng ý")

        # Đề xuất quan hệ trong schema_proposals cũng có tên sạch
        prop = next(p for p in project["schema_proposals"] if p["kind"] == "relations")
        self.assertEqual(prop["name"], "cần sự đồng ý")
        # Định nghĩa từ payload vẫn được gắn đúng
        self.assertEqual(prop["definition"], "Yêu cầu có sự phê duyệt trước khi ký")


if __name__ == "__main__":
    unittest.main()

