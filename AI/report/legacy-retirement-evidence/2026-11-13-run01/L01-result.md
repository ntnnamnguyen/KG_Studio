# Kết quả Nghiệm thu Mốc L01 — Chốt Ownership / Contracts & Mở rộng Guards

- **Run ID:** `2026-11-13-run01`
- **Mốc:** `L01`
- **Trạng thái:** `PASS`
- **Thời gian hoàn thành:** 2026-11-13 16:13:00

---

## 1. Đầu vào & Mục tiêu

- **Đầu vào:** Kết quả L00, danh mục C01–C12, cấu trúc 6 modules nghiệp vụ và các guards hiện có.
- **Mục tiêu:** Mở rộng và củng cố các ranh giới kiến trúc bằng AST test tự động, bảo đảm không có vi phạm cross-module private imports, frontend không import repository concrete, frontend chỉ import backend.modules qua `.public`, và có negative test chứng minh guard hoạt động chính xác.

---

## 2. Các Thay đổi & Củng cố Ranh giới

1. **Khắc phục Vi phạm Cross-Module Cũ:**
   - Trong `backend/modules/schema_intelligence/application/service.py`: Chuyển import `ProjectCommitCoordinator` từ đường dẫn private `.projects.application.commit_coordinator` sang đường dẫn public `.projects.public`.
2. **Khắc phục Vi phạm Frontend Composition Cũ:**
   - Trong `frontend/composition.py`: Chuyển cả 6 Application Services (`ProjectsApplicationService`, `SchemaIntelligenceApplicationService`, `ExtractionApplicationService`, `CurationApplicationService`, `GraphQAApplicationService`, `TrainingApplicationService`) từ import private `.application.service` sang import public `.public`.
3. **Mở rộng Bộ Guard Kiểm thử Biên Kiến trúc (`tests/test_architecture_boundaries.py`):**
   - **Quy tắc 5 (`test_cross_module_private_imports_are_forbidden`):** Bắt buộc các module nghiệp vụ khi gọi chéo nhau phải qua `.public` hoặc `.ports`.
   - **Quy tắc 6 (`test_frontend_must_not_import_backend_repositories_directly`):** Cấm `frontend/` import trực tiếp `backend.repositories.*`.
   - **Quy tắc 7 (`test_frontend_must_import_backend_modules_via_public_only`):** Cấm `frontend/` import private submodules của `backend.modules`.
   - **Negative Fixture (`test_guard_detects_unauthorized_cross_module_import_negative_fixture`):** Chứng minh rule và AST extractor fail-closed khi gặp import vi phạm.

---

## 3. Kết quả Kiểm thử & Đánh giá Cổng L01

- Chạy targeted guard tests:
  - Lệnh: `.\.venv-win\Scripts\python.exe tools\run_isolated_tests.py tests.test_architecture_boundaries`
  - Kết quả: **8/8 tests PASS** (0 failures, 0 errors, thời gian: 0.743s).
- **Quyết định:** Đạt toàn bộ tiêu chí của mốc **L01**, sẵn sàng chuyển sang mốc **L02 — Thống nhất wiring và public boundaries**.
