"""Kiểm thử thiết kế lai 2 tầng đối chiếu bằng chứng: Tầng 1 (4 nấc khớp từ) & Tầng 2 (Lexical Cosine gợi ý)."""
from __future__ import annotations

import unittest
import unicodedata

from backend.domain.curation.service import (
    evidence_context,
    evidence_in_chunk,
    find_all_quote_spans,
    select_edge_evidence_span,
    update_edge,
)
from backend.domain.curation.validation import validate_edge_for_approval
from backend.domain.extraction.validator import validate_extraction
from shared.constants import STATUS_CHECK, STATUS_PENDING


class TwoTierEvidenceMatchingTests(unittest.TestCase):
    """Đảm bảo khớp đúng các biến thể dấu câu/bullet/bảng/ellipsis/NFD mà không tự cho qua câu bịa."""

    def test_layer1_near_verbatim_variants_and_anti_hallucination_guards(self) -> None:
        # 1. Dấu chấm cuối khác dấu chấm phẩy gốc (Dong_Ngoc_Long.docx)
        doc_dnl = "Không nên khẳng định. S3 giới thiệu tiếp cận tuyến từ Phú Yên bằng đường bộ hoặc theo suối Tuyết Sơn; S1 mô tả thêm."
        q_dnl = "S3 giới thiệu tiếp cận tuyến từ Phú Yên bằng đường bộ hoặc theo suối Tuyết Sơn."
        spans_dnl = find_all_quote_spans(doc_dnl, q_dnl)
        self.assertEqual(len(spans_dnl), 1)
        self.assertEqual(spans_dnl[0][2], "near_verbatim")
        self.assertEqual(
            doc_dnl[spans_dnl[0][0] : spans_dnl[0][1]],
            "S3 giới thiệu tiếp cận tuyến từ Phú Yên bằng đường bộ hoặc theo suối Tuyết Sơn",
        )
        self.assertTrue(evidence_in_chunk(q_dnl, doc_dnl))

        # 2. Khoảng trắng thừa trước dấu hai chấm / chấm
        doc_space = "Trống đồng và tập hợp lưỡi cày đồng Mả Tre : Minh chứng cho tiềm lực kinh tế."
        q_space = "Trống đồng và tập hợp lưỡi cày đồng Mả Tre: Minh chứng cho tiềm lực kinh tế."
        spans_space = find_all_quote_spans(doc_space, q_space)
        self.assertEqual(len(spans_space), 1)
        self.assertEqual(spans_space[0][2], "near_verbatim")

        # 3. Bullet + xuống dòng + ký tự khung bảng ASCII
        doc_box = "│ LỚP THỨ HAI: KHU THÀNH ĐẠT   │\n│ • (Cổng Bí Văn, Cổng Súc Văn, KHUÊ VĂN CÁC) │"
        q_box = "LỚP THỨ HAI: KHU THÀNH ĐẠT (Cổng Bí Văn, Cổng Súc Văn, KHUÊ VĂN CÁC)"
        spans_box = find_all_quote_spans(doc_box, q_box)
        self.assertEqual(len(spans_box), 1)
        self.assertEqual(spans_box[0][2], "near_verbatim")

        # 4. Ellipsis hợp lệ trong phạm vi <= 600 ký tự
        doc_el = "Nàng lập am tu hành trong 9 năm, chứng kiến 18 cửa địa ngục và dốc lòng niệm Phật cho đến khi đắc đạo thành Bồ Tát Quan Thế Âm."
        q_el = "Nàng lập am tu hành trong 9 năm... cho đến khi đắc đạo thành Bồ Tát Quan Thế Âm"
        spans_el = find_all_quote_spans(doc_el, q_el)
        self.assertEqual(len(spans_el), 1)
        self.assertEqual(spans_el[0][2], "ellipsis_match")
        self.assertTrue(evidence_in_chunk(q_el, doc_el))

        # 5. Chặn ellipsis vượt quá 600 ký tự giữa 2 đoạn xa nhau
        doc_far = "Chùa Một Cột nằm ở quận Ba Đình. " + ("Nội dung khác dài dòng. " * 35) + "Được xây dựng năm 1049."
        self.assertEqual(find_all_quote_spans(doc_far, "Chùa Một Cột nằm ở quận Ba Đình... Được xây dựng năm 1049."), [])

        # 6. Chặn ellipsis ngắn nguy hiểm (< 5 từ tổng)
        self.assertEqual(find_all_quote_spans("Hà Nội có nhiều di tích cổ kính và văn hóa.", "Hà Nội ... văn hóa"), [])

        # 7. Chặn paraphrase / sai sự thật & đảo trật tự từ
        self.assertEqual(
            find_all_quote_spans("Chùa Hà có lịch sử hàng trăm năm gắn với làng Dịch Vọng.", "Chùa Hà có tuổi đời tròn một nghìn năm tại Dịch Vọng."),
            [],
        )
        self.assertEqual(
            find_all_quote_spans("Vua Lý Thái Tông cho xây dựng chùa Một Cột.", "Chùa Một Cột cho xây dựng vua Lý Thái Tông."),
            [],
        )

    def test_nfd_document_preserves_exact_raw_offsets(self) -> None:
        raw_doc = unicodedata.normalize("NFD", "Đoạn mở đầu có tiếng Việt. Chùa Một Cột nằm ở Hà Nội; phần kết.")
        nfc_quote = unicodedata.normalize("NFC", "Chùa Một Cột nằm ở Hà Nội.")
        spans = find_all_quote_spans(raw_doc, nfc_quote)
        self.assertEqual(len(spans), 1)
        s, e, method = spans[0]
        self.assertEqual(method, "near_verbatim")
        self.assertEqual(raw_doc[s:e], unicodedata.normalize("NFD", "Chùa Một Cột nằm ở Hà Nội"))

    def test_layer2_lexical_cosine_suggestions_on_unmatched_evidence(self) -> None:
        doc_text = (
            "Lịch sử đền Kim Liên ghi nhận nhiều dấu mốc quan trọng.\n"
            "Bia cao hơn 2m, do Đông阁 Đại học sĩ Lê Tung soạn thảo văn bia.\n"
            "Vườn Sinh thái & Bền vững (Sustainable & Biophilic Garden): Đặc điểm:\n"
            "- Vườn đứng (Vertical Garden): Thiết kế mảng xanh thẳng đứng."
        )
        project = {
            "project_id": "p_ev",
            "name": "p_ev",
            "relations": ["soạn thảo"],
            "relation_catalog": [{"name": "soạn thảo"}],
            "entity_types": [{"name": "Di tích"}, {"name": "Nhân vật"}],
            "documents": [{"id": "d1", "name": "test.docx", "text": doc_text, "hash": "h1"}],
            "nodes": [
                {"id": "n1", "name": "Lê Tung", "kind": "Nhân vật"},
                {"id": "n2", "name": "Văn bia đền Kim Liên", "kind": "Di tích"},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "n1",
                    "target": "n2",
                    "relation": "soạn thảo",
                    "evidence": "do Đông các Đại học sĩ Lê Tung soạn thảo văn bia",
                    "evidence_found": False,
                    "doc_id": "d1",
                    "start_char": 0,
                    "end_char": len(doc_text),
                    "status": STATUS_CHECK,
                },
                {
                    "id": "e2",
                    "source": "n1",
                    "target": "n2",
                    "relation": "soạn thảo",
                    "evidence": "Vườn Sinh thái & Bền vững đặc điểm gồm Vườn đứng (Vertical Garden) mảng xanh thẳng đứng",
                    "evidence_found": False,
                    "doc_id": "d1",
                    "start_char": 0,
                    "end_char": len(doc_text),
                    "status": STATUS_CHECK,
                },
            ],
        }

        # Ca Hán tự Đông阁: Layer 1 phải giữ found=False, nhưng Layer 2 gợi ý đúng câu bia gốc
        ctx_fast = evidence_context(project, project["edges"][0], include_snippets=False)
        self.assertFalse(ctx_fast["found"])
        self.assertEqual(ctx_fast["suggestions"], [])

        ctx_ui = evidence_context(project, project["edges"][0], include_snippets=True)
        self.assertFalse(ctx_ui["found"])
        self.assertTrue(ctx_ui["suggestions"])
        top_sug = ctx_ui["suggestions"][0]
        self.assertIn("Đông阁 Đại học sĩ Lê Tung soạn thảo văn bia", top_sug["text"])
        self.assertGreaterEqual(top_sug["score_pct"], 50)
        self.assertEqual(doc_text[top_sug["start_char"] : top_sug["end_char"]], top_sug["text"])

        # Ca 2 dòng liền kề (tiêu đề + bullet): cửa sổ 2 dòng giúp gợi ý lấy trọn cả dòng bullet
        ctx_list = evidence_context(project, project["edges"][1], include_snippets=True)
        self.assertFalse(ctx_list["found"])
        self.assertTrue(ctx_list["suggestions"])
        self.assertIn("Đặc điểm:", ctx_list["suggestions"][0]["text"])
        self.assertIn("Vườn đứng (Vertical Garden)", ctx_list["suggestions"][0]["text"])

        # Áp dụng câu gợi ý ở e1 -> cập nhật thành khớp nguyên văn
        updated = update_edge(project, "e1", evidence=top_sug["text"], note="Dùng gợi ý #1")
        self.assertTrue(updated["evidence_found"])
        self.assertEqual(updated["match_method"], "exact")
        val = validate_edge_for_approval(project, updated, is_batch=False, check_existing_override=True)
        self.assertTrue(val["ok"])

    def test_validate_extraction_and_verified_span_locking_for_near_verbatim(self) -> None:
        chunk = "Đoạn 1: S3 giới thiệu tiếp cận tuyến từ Phú Yên bằng đường bộ hoặc theo suối Tuyết Sơn; S1 mô tả thêm."
        extraction = {
            "thuc_the": [
                {"ten": "Phú Yên", "loai": "địa điểm", "mo_ta": ""},
                {"ten": "suối Tuyết Sơn", "loai": "địa điểm", "mo_ta": ""},
            ],
            "quan_he": [
                {
                    "nguon": "Phú Yên",
                    "quan_he": "dẫn đến",
                    "dich": "suối Tuyết Sơn",
                    "trich_dan": "S3 giới thiệu tiếp cận tuyến từ Phú Yên bằng đường bộ hoặc theo suối Tuyết Sơn.",
                },
                {
                    "nguon": "Phú Yên",
                    "quan_he": "dẫn đến",
                    "dich": "suối Tuyết Sơn",
                    "trich_dan": "Câu này bịa hoàn toàn không có trong văn bản",
                },
            ],
        }
        clean, report = validate_extraction(extraction, chunk, ["dẫn đến"], open_mode=False)
        self.assertEqual(report["evidence_mismatch"], 1)
        self.assertEqual(clean["quan_he"][0]["evidence_found"], True)
        self.assertEqual(clean["quan_he"][0]["status"], STATUS_PENDING)
        self.assertEqual(clean["quan_he"][1]["evidence_found"], False)
        self.assertEqual(clean["quan_he"][1]["status"], STATUS_CHECK)

        # Kiểm tra khóa span verified_start_char..verified_end_char với near_verbatim vẫn khớp ổn định
        dup_chunk = f"{chunk}\n\nLặp lại: {chunk}"
        spans = find_all_quote_spans(dup_chunk, clean["quan_he"][0]["trich_dan"])
        self.assertEqual(len(spans), 2)
        proj = {
            "project_id": "p_lock",
            "relations": ["dẫn đến"],
            "relation_catalog": [{"name": "dẫn đến"}],
            "entity_types": [{"name": "địa điểm"}],
            "documents": [{"id": "d1", "name": "a.txt", "text": dup_chunk}],
            "nodes": [],
            "edges": [
                {
                    "id": "elock",
                    "source": "n1",
                    "target": "n2",
                    "relation": "dẫn đến",
                    "evidence": clean["quan_he"][0]["trich_dan"],
                    "doc_id": "d1",
                    "status": STATUS_PENDING,
                }
            ],
        }
        locked = select_edge_evidence_span(proj, "elock", spans[1][0], spans[1][1])
        self.assertTrue(locked["found"])
        self.assertFalse(locked["ambiguous"])
        self.assertEqual(locked["match_method"], "near_verbatim")
        self.assertEqual(locked["match_label"], "Khớp gần nguyên văn")
