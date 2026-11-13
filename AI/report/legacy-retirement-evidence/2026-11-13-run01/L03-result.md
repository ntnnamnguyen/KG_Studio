# Kết quả Nghiệm thu Mốc L03 — Thay Đường Ghi & Khóa Legacy

- **Run ID:** `2026-11-13-run01`
- **Mốc:** `L03`
- **Trạng thái:** `PASS`
- **Thời gian hoàn thành:** 2026-11-13 16:17:00

---

## 1. Đầu vào & Mục tiêu

- **Đầu vào:** Kết quả L02, các ứng viên C01, C02.
- **Mục tiêu:**
  1. Hợp nhất cơ chế khóa tiến trình (Process-wide Lock): `ProjectsApplicationService` và `ExtractionApplicationService` sử dụng trực tiếp `coordinator.get_project_lock(project_id)`, loại bỏ từ điển khóa riêng rẽ.
  2. Xóa bỏ hoàn toàn fallback ghi trực tiếp bypass coordinator trong `CurationApplicationService._commit_curation_operation` và `SchemaIntelligenceApplicationService.apply_proposal_decisions`.
  3. Cập nhật `ExtractionApplicationService._save_project_safe` đồng bộ trạng thái projection dưới khóa thống nhất.

---

## 2. Các Thay đổi Triển khai

1. **Thống nhất Lock Contract:**
   - Trong `ProjectsApplicationService`: `get_project_lock(project_id)` chuyển sang ủy quyền trực tiếp cho `self.commit_coordinator.get_project_lock(project_id)`, xóa bỏ `self._locks` cục bộ.
   - Trong `ExtractionApplicationService`: `get_project_lock(project_id)` ưu tiên lấy lock từ `self.commit_coordinator.get_project_lock(project_id)`.
2. **Khử Bỏ Fallback Ghi Không Coordinator (No-Bypass Policy):**
   - Trong `CurationApplicationService._commit_curation_operation`: Nếu `self.commit_coordinator is None`, ném `RuntimeError` rõ ràng cấm fallback ghi trực tiếp.
   - Trong `SchemaIntelligenceApplicationService.apply_proposal_decisions`: Nếu `self.commit_coordinator is None`, ném `RuntimeError` rõ ràng cấm mutate bộ nhớ thiếu coordinator.
3. **Đồng bộ Projection An toàn Trong Extraction:**
   - Trong `ExtractionApplicationService._save_project_safe`: Thực thi lưu tài liệu và đồng bộ SQLite projection trong khối khóa `with self.get_project_lock(proj_id):`.

---

## 3. Kết quả Kiểm thử & Đánh giá Cổng L03

- **Kiểm thử Điều phối Transaction & Khóa:**
  - `tests.test_commit_coordinator`: 6/6 tests PASS (0.023s) — kiểm tra thành công optimistic revision conflict, idempotency replay, atomic rollback và SQLite sync pending.
  - `tests.test_curation_hub`, `tests.test_curation_merge`, `tests.test_gazetteer_feedback_loop`: 36/36 tests PASS (1.570s).
  - `tests.test_edc_bulk_review`: 8/8 tests PASS (0.406s).
  - `tests.test_free_triples_baseline`, `tests.test_free_triples_ui`: 26/26 tests PASS (1.664s).
- **Quyết định:** Đạt toàn bộ tiêu chí của mốc **L03**, sẵn sàng chuyển sang mốc **L04 — Thay đọc projection và cache thiếu độ mới**.
