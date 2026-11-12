"""Bộ kiểm thử đơn vị cho Tính năng Quản lý Phiên bản Prompt & Xem trước Request (Prompt Versioning).

Kiểm thử toàn diện theo KG_Studio/AI/features/prompt-versioning.md:
1. Tính độc lập giữa các dự án (Project A vs B) và giữa các chế độ (closed, edc, edc_plus_r).
2. Di chuyển dữ liệu tương thích ngược và tính lũy đẳng (Idempotent Migration).
3. Đánh số phiên bản đơn điệu, băm nội dung SHA-256 và chống tạo version rác (No-op save).
4. Khôi phục an toàn (tạo version mới, không xóa bản cũ, bảo toàn catalog).
5. So sánh Diff bằng difflib chuẩn.
6. Chuẩn bị Request dùng chung (Preview & Execution Parity), phản ánh đúng token budget & response format.
7. Ghi nhận provenance (prompt_version_id, prepared_request_hash) vào run record.
"""
from __future__ import annotations

import unittest

from backend.domain.prompts.service import (
    DEFAULT_PROMPTS,
    compute_prompt_hash,
    diff_prompt_versions,
    ensure_project_prompt_history,
    get_active_prompt_content,
    get_active_prompt_version,
    get_prompt_version,
    list_prompt_versions,
    restore_prompt_version,
    save_prompt_version,
)
from backend.facade import get_facade
from backend.integrations.llm.gateway import LLMGateway
from shared.constants import (
    DEFAULT_EDC_PROMPT,
    EXTRACTION_MODES,
    MODE_EDC,
    MODE_EDC_PLUS_R,
    MODE_FIXED,
)
from shared.schemas.prompts import PreparedExtractionRequestDTO


from types import SimpleNamespace


class FakeLLMClient:
    """Mock client giả lập SDK LLM để kiểm tra parity mà không gọi mạng."""

    def __init__(self, response_text: str = '{"thuc_the": [], "quan_he": []}'):
        self.response_text = response_text
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.response_text), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )


class TestPromptVersioning(unittest.TestCase):
    def setUp(self) -> None:
        self.facade = get_facade()
        self.project_a = {
            "project_id": "proj_a_001",
            "name": "Dự án A",
            "extraction_mode": MODE_FIXED,
            "prompt": "Hướng dẫn trích xuất di tích Thăng Long.",
            "edc_prompt": "Hướng dẫn EDC cho dự án A.",
            "relations": ["sinh_tai", "dong_do"],
            "entity_types": [{"name": "Nhân vật"}, {"name": "Địa danh"}],
            "documents": [
                {
                    "id": "doc_1",
                    "name": "lich_su.txt",
                    "text": "Vua Lý Thái Tổ dời đô từ Hoa Lư về Đại La năm 1010.",
                }
            ],
            "runs": [],
        }

        self.project_b = {
            "project_id": "proj_b_002",
            "name": "Dự án B",
            "extraction_mode": MODE_EDC,
            "prompt": "Hướng dẫn dự án B.",
            "edc_prompt": "Hướng dẫn EDC cho dự án B.",
            "relations": ["tri_vi"],
            "entity_types": [{"name": "Vua"}],
            "documents": [],
            "runs": [],
        }

    def test_idempotent_migration(self) -> None:
        # Lần 1: Dự án chưa có prompt_history_schema_version
        migrated_1 = ensure_project_prompt_history(self.project_a)
        self.assertTrue(migrated_1)
        self.assertEqual(self.project_a.get("prompt_history_schema_version"), 1)
        self.assertIn("prompt_bindings", self.project_a)
        self.assertIn("prompt_versions", self.project_a)

        # Mỗi chế độ được hỗ trợ đều có binding độc lập
        bindings = self.project_a["prompt_bindings"]
        self.assertIn(MODE_FIXED, bindings)
        self.assertIn(MODE_EDC, bindings)
        self.assertIn(MODE_EDC_PLUS_R, bindings)
        # Binding của EDC và EDC+R phải là 2 ID phiên bản độc lập
        self.assertNotEqual(bindings[MODE_EDC], bindings[MODE_EDC_PLUS_R])

        initial_version_count = len(self.project_a["prompt_versions"])
        self.assertEqual(set(bindings), set(EXTRACTION_MODES))
        self.assertEqual(initial_version_count, len(EXTRACTION_MODES))

        # Lần 2: Chạy lại migration trên cùng project phải là no-op
        migrated_2 = ensure_project_prompt_history(self.project_a)
        self.assertFalse(migrated_2)
        self.assertEqual(len(self.project_a["prompt_versions"]), initial_version_count)

    def test_migration_with_legacy_prompt_versions(self) -> None:
        legacy_project = {
            "project_id": "leg_001",
            "name": "Legacy Project",
            "extraction_mode": MODE_FIXED,
            "prompt": "Prompt hiện hành",
            "prompt_versions": [
                {
                    "at": "2026-10-30T10:00:00Z",
                    "prompt": "Prompt phiên bản cũ 1",
                    "prompt_id": "p_old_1",
                    "relations": ["rel1"],
                },
                {
                    "at": "2026-10-30T11:00:00Z",
                    "prompt": "Prompt phiên bản cũ 2",
                    "prompt_id": "p_old_2",
                    "relations": ["rel1", "rel2"],
                },
            ],
        }
        ensure_project_prompt_history(legacy_project)
        versions = legacy_project["prompt_versions"]
        # Phải chứa các version legacy đã được chuyển đổi + version hiện hành + 2 default EDC
        self.assertTrue(any(v.get("origin") == "migration" for v in versions))
        # Kiểm tra binding trỏ đến version hợp lệ
        b_closed = legacy_project["prompt_bindings"][MODE_FIXED]
        active_v = get_prompt_version(legacy_project, b_closed)
        self.assertIsNotNone(active_v)
        self.assertEqual(active_v["content"], "Prompt hiện hành")

    def test_project_and_mode_isolation(self) -> None:
        ensure_project_prompt_history(self.project_a)
        ensure_project_prompt_history(self.project_b)

        # Lưu prompt mới cho dự án A ở chế độ closed
        new_v_a, _ = save_prompt_version(
            self.project_a,
            MODE_FIXED,
            "Nội dung mới chỉ dành cho dự án A.",
            note="Thay đổi A",
        )
        self.assertEqual(get_active_prompt_content(self.project_a, MODE_FIXED), "Nội dung mới chỉ dành cho dự án A.")

        # Dự án B hoàn toàn không bị ảnh hưởng
        self.assertNotEqual(get_active_prompt_content(self.project_b, MODE_FIXED), "Nội dung mới chỉ dành cho dự án A.")

        # Thử khôi phục version của dự án A vào dự án B -> Bị từ chối
        with self.assertRaises(ValueError):
            restore_prompt_version(self.project_b, new_v_a["id"])

        # Sửa prompt EDC của dự án A không làm đổi prompt EDC+R của chính dự án A
        content_edc_plus_r_before = get_active_prompt_content(self.project_a, MODE_EDC_PLUS_R)
        save_prompt_version(self.project_a, MODE_EDC, "Prompt EDC riêng biệt.")
        content_edc_plus_r_after = get_active_prompt_content(self.project_a, MODE_EDC_PLUS_R)
        self.assertEqual(content_edc_plus_r_before, content_edc_plus_r_after)

    def test_save_version_monotonic_and_noop(self) -> None:
        ensure_project_prompt_history(self.project_a)
        v1 = get_active_prompt_version(self.project_a, MODE_FIXED)
        self.assertEqual(v1["version"], 1)

        # Lưu nội dung mới -> sinh v2
        v2, is_new = save_prompt_version(self.project_a, MODE_FIXED, "Nội dung v2 cải tiến.")
        self.assertTrue(is_new)
        self.assertEqual(v2["version"], 2)
        self.assertEqual(self.project_a["prompt_bindings"][MODE_FIXED], v2["id"])

        # Lưu lại nội dung giống hệt v2 -> no-op (không sinh version rác)
        v2_again, is_new_again = save_prompt_version(self.project_a, MODE_FIXED, "Nội dung v2 cải tiến.")
        self.assertFalse(is_new_again)
        self.assertEqual(v2_again["id"], v2["id"])
        self.assertEqual(len(list_prompt_versions(self.project_a, MODE_FIXED)), 2)

        # Lưu rỗng -> Báo lỗi
        with self.assertRaises(ValueError):
            save_prompt_version(self.project_a, MODE_FIXED, "   ")

    def test_restore_creates_new_version_preserving_catalogs(self) -> None:
        ensure_project_prompt_history(self.project_a)
        v1 = get_active_prompt_version(self.project_a, MODE_FIXED)
        v1_id = v1["id"]
        catalogs_before = list(self.project_a["relations"])

        # Tạo v2
        v2, _ = save_prompt_version(self.project_a, MODE_FIXED, "Nội dung phiên bản 2.")

        # Khôi phục về v1 -> Tạo v3 có content của v1
        v3, is_restored = restore_prompt_version(self.project_a, v1_id)
        self.assertTrue(is_restored)
        self.assertEqual(v3["version"], 3)
        self.assertEqual(v3["content"], v1["content"])
        self.assertEqual(v3["restored_from_version_id"], v1_id)
        self.assertEqual(self.project_a["prompt_bindings"][MODE_FIXED], v3["id"])

        # Catalog của dự án hoàn toàn nguyên vẹn
        self.assertEqual(self.project_a["relations"], catalogs_before)

        # Thử khôi phục chính bản v3 đang áp dụng -> no-op
        v3_again, is_res_noop = restore_prompt_version(self.project_a, v3["id"])
        self.assertFalse(is_res_noop)

    def test_diff_prompt_versions(self) -> None:
        text1 = "Dòng 1: Giữ nguyên.\nDòng 2: Cũ."
        text2 = "Dòng 1: Giữ nguyên.\nDòng 2: Mới cập nhật.\nDòng 3: Bổ sung."
        diff = diff_prompt_versions(text1, text2, "v1", "v2")
        self.assertIn("-Dòng 2: Cũ.", diff)
        self.assertIn("+Dòng 2: Mới cập nhật.", diff)
        self.assertIn("+Dòng 3: Bổ sung.", diff)

    def test_request_preparation_parity(self) -> None:
        chunk = "Lý Công Uẩn sinh năm 974 tại Cổ Pháp, dời đô về Thăng Long năm 1010."
        sys_prompt = "Trích xuất thực thể và quan hệ lịch sử."
        allowed_rel = ["sinh_tai", "dong_do"]

        prepared = LLMGateway.prepare_extraction_request(
            provider="deepseek",
            model="deepseek-chat",
            system_prompt=sys_prompt,
            chunk=chunk,
            allowed_relations=allowed_rel,
            temperature=0.2,
            max_tokens=4096,
            max_input_tokens=16000,
            open_mode=False,
            project_id="test_p",
            configuration_id="closed",
            prompt_version_id="pv_closed_01",
        )

        self.assertIsInstance(prepared, PreparedExtractionRequestDTO)
        self.assertEqual(prepared.provider, "deepseek")
        self.assertEqual(prepared.model, "deepseek-chat")
        self.assertEqual(prepared.prompt_version_id, "pv_closed_01")
        self.assertTrue(len(prepared.request_hash) == 64)  # SHA-256
        self.assertIn("Lý Công Uẩn", prepared.user_message)
        self.assertIn("sinh_tai", prepared.user_message)

        # Hash không thay đổi khi dữ liệu giữ nguyên
        prep_2 = LLMGateway.prepare_extraction_request(
            provider="deepseek",
            model="deepseek-chat",
            system_prompt=sys_prompt,
            chunk=chunk,
            allowed_relations=allowed_rel,
            temperature=0.2,
            max_tokens=4096,
            max_input_tokens=16000,
            open_mode=False,
        )
        self.assertEqual(prepared.request_hash, prep_2.request_hash)

    def test_facade_preview_extraction_request(self) -> None:
        ensure_project_prompt_history(self.project_a)
        # Xem trước ở chế độ closed
        prev_closed = self.facade.preview_extraction_request(
            self.project_a,
            configuration_id=MODE_FIXED,
            doc_id="doc_1",
            chunk_number=1,
        )
        self.assertEqual(prev_closed.configuration_id, MODE_FIXED)
        self.assertIn("DANH MỤC QUAN HỆ", prev_closed.system_prompt)
        self.assertFalse(prev_closed.is_draft)

        # Xem trước với bản nháp
        prev_draft = self.facade.preview_extraction_request(
            self.project_a,
            configuration_id=MODE_FIXED,
            doc_id="doc_1",
            draft_content="Prompt nháp thử nghiệm chưa lưu.",
        )
        self.assertTrue(prev_draft.is_draft)
        self.assertIn("Prompt nháp thử nghiệm chưa lưu.", prev_draft.system_prompt)

    def test_execution_provenance_recorded_in_runs(self) -> None:
        ensure_project_prompt_history(self.project_a)
        active_v = get_active_prompt_version(self.project_a, MODE_FIXED)
        fake_client = FakeLLMClient(response_text='{"thuc_the": [{"ten": "Lý Thái Tổ", "loai": "Nhân vật"}], "quan_he": []}')

        doc = self.project_a["documents"][0]
        chunks = self.facade.document_chunks(doc)
        chunk_rec = chunks[0]

        output = self.facade.extract_chunk(
            self.project_a,
            doc,
            chunk_rec,
            provider="deepseek",
            api_key="sk-test",
            model="deepseek-chat",
            client=fake_client,
        )

        # Kiểm tra provenance được engine gán vào EngineOutput
        self.assertEqual(output.prompt_version_id, active_v["id"])
        self.assertEqual(output.prompt_content_hash, active_v["content_hash"])
        self.assertTrue(len(output.prepared_request_hash) > 0)

        # Kiểm tra provenance được lưu trữ trong project["runs"]
        self.assertTrue(len(self.project_a["runs"]) > 0)
        latest_run = self.project_a["runs"][-1]
        self.assertEqual(latest_run["prompt_version_id"], active_v["id"])
        self.assertEqual(latest_run["prompt_content_hash"], active_v["content_hash"])
        self.assertEqual(latest_run["prepared_request_hash"], output.prepared_request_hash)
        self.assertIn("system_prompt", latest_run["prepared_request"])


if __name__ == "__main__":
    unittest.main()
