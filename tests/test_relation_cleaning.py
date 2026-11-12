"""Kiểm thử chuẩn hóa quan hệ tiếng Việt tự nhiên (Clean Relation Name) trong trích xuất EDC mở."""
import unittest

from backend.domain.catalogs.service import prepare_edc
from backend.domain.extraction.validator import ensure_node, ingest_extraction, validate_extraction
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


class TestEnsureNodeUpgrade(unittest.TestCase):
    def test_alias_matching(self):
        """Khớp thực thể qua danh sách bí danh (aliases) thay vì chỉ tên chính."""
        project = {
            "nodes": [
                {
                    "id": "n_thd",
                    "name": "Trần Hưng Đạo",
                    "kind": "Nhân vật",
                    "aliases": ["Trần Quốc Tuấn", "Hưng Đạo Đại Vương"],
                    "documents": ["doc1"],
                }
            ]
        }
        nid = ensure_node(project, name="Trần Quốc Tuấn", kind="Nhân vật", doc_id="doc2", strict_kind=True)
        self.assertEqual(nid, "n_thd")
        self.assertEqual(len(project["nodes"]), 1)
        self.assertIn("doc2", project["nodes"][0]["documents"])

    def test_strict_kind_upgrade_from_unknown(self):
        """Trong strict_kind, nâng cấp từ UNKNOWN_KIND lên loại cụ thể và không sinh node trùng."""
        project = {
            "nodes": [
                {
                    "id": "n_tran",
                    "name": "nhà Trần",
                    "kind": "Chưa xác định",
                    "aliases": [],
                    "documents": ["doc1"],
                }
            ]
        }
        nid = ensure_node(project, name="nhà Trần", kind="Triều đại", strict_kind=True)
        self.assertEqual(nid, "n_tran")
        self.assertEqual(len(project["nodes"]), 1)
        self.assertEqual(project["nodes"][0]["kind"], "Triều đại")

    def test_strict_kind_incoming_unknown_links_to_specific(self):
        """Trong strict_kind, thực thể có kind=UNKNOWN_KIND liên kết thành công vào node đã có loại cụ thể."""
        project = {
            "nodes": [
                {
                    "id": "n_tran",
                    "name": "nhà Trần",
                    "kind": "Triều đại",
                    "aliases": [],
                    "documents": ["doc1"],
                }
            ]
        }
        nid = ensure_node(project, name="nhà Trần", kind="Chưa xác định", strict_kind=True)
        self.assertEqual(nid, "n_tran")
        self.assertEqual(len(project["nodes"]), 1)
        self.assertEqual(project["nodes"][0]["kind"], "Triều đại")

    def test_strict_kind_type_conflict_creates_new_node(self):
        """Trong strict_kind, hai thực thể có hai loại cụ thể khác nhau sẽ không gộp nhầm."""
        project = {
            "nodes": [
                {
                    "id": "n_hn_loc",
                    "name": "Hà Nội",
                    "kind": "Địa danh",
                    "aliases": [],
                    "documents": ["doc1"],
                }
            ]
        }
        nid = ensure_node(project, name="Hà Nội", kind="Tổ chức", strict_kind=True)
        self.assertNotEqual(nid, "n_hn_loc")
        self.assertEqual(len(project["nodes"]), 2)

    def test_casing_and_description_enrichment(self):
        """Chuẩn hóa viết hoa cho tên và làm giàu mô tả khi có thông tin chi tiết hơn."""
        project = {
            "nodes": [
                {
                    "id": "n_hn",
                    "name": "hà nội",
                    "kind": "Địa danh",
                    "description": "Thành phố",
                    "aliases": [],
                    "documents": ["doc1"],
                }
            ]
        }
        nid = ensure_node(project, name="Hà Nội", kind="Địa danh", description="Thành phố thủ đô của Việt Nam")
        self.assertEqual(nid, "n_hn")
        self.assertEqual(project["nodes"][0]["name"], "Hà Nội")
        self.assertEqual(project["nodes"][0]["description"], "Thành phố thủ đô của Việt Nam")

    def test_node_redirect_resolution(self):
        """Tự động phân giải qua node_redirects về canonical node."""
        project = {
            "node_redirects": {"n_old": "n_canonical"},
            "nodes": [
                {
                    "id": "n_old",
                    "name": "Đại Cồ Việt",
                    "kind": "Quốc gia",
                    "aliases": [],
                    "documents": [],
                },
                {
                    "id": "n_canonical",
                    "name": "Đại Việt",
                    "kind": "Quốc gia",
                    "aliases": ["Đại Cồ Việt"],
                    "documents": [],
                },
            ],
        }
        nid = ensure_node(project, name="Đại Cồ Việt", kind="Quốc gia")
        self.assertEqual(nid, "n_canonical")

    def test_generic_component_entity_document_scoping_prevents_god_node(self):
        """Thực thể yếu / bộ phận chung như 'cổng' ở 2 tài liệu khác nhau KHÔNG bị gộp nhầm thành 1 node."""
        project = {"nodes": []}
        # Tài liệu 1 (Đình Bát Tràng) trích xuất 'cổng'
        nid_1 = ensure_node(project, name="cổng", kind="kiến trúc", doc_id="doc_bat_trang")
        # Tài liệu 2 (Đình Kim Liên) trích xuất 'cổng'
        nid_2 = ensure_node(project, name="cổng", kind="kiến trúc", doc_id="doc_kim_lien")

        self.assertNotEqual(nid_1, nid_2, "Cổng của 2 đình khác nhau phải có 2 Node ID riêng biệt")
        self.assertEqual(len(project["nodes"]), 2)
        self.assertTrue(project["nodes"][0].get("is_component"))
        self.assertTrue(project["nodes"][1].get("is_component"))

        # Trong cùng Tài liệu 1, đoạn văn sau nhắc lại 'cổng' -> tái sử dụng đúng nid_1
        nid_1_again = ensure_node(project, name="cổng", kind="kiến trúc", doc_id="doc_bat_trang")
        self.assertEqual(nid_1_again, nid_1)
        self.assertEqual(len(project["nodes"]), 2)

    def test_proper_named_entity_global_scoping(self):
        """Thực thể tên riêng độc lập (như 'Chùa Một Cột') được gộp toàn cục qua các tài liệu khác nhau."""
        project = {"nodes": []}
        nid_1 = ensure_node(project, name="Chùa Một Cột", kind="di tích", doc_id="doc_1")
        nid_2 = ensure_node(project, name="Chùa Một Cột", kind="di tích", doc_id="doc_2")

        self.assertEqual(nid_1, nid_2, "Tên riêng toàn cục phải được gộp thành 1 Node")
        self.assertEqual(len(project["nodes"]), 1)
        self.assertEqual(set(project["nodes"][0]["documents"]), {"doc_1", "doc_2"})
        self.assertFalse(project["nodes"][0].get("is_component", False))


if __name__ == "__main__":
    unittest.main()

