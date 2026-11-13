# Báo cáo Triển khai Kế hoạch Loại bỏ và Thay thế Code Legacy

- **Tài liệu gốc:** [legacy-retirement-agent-plan.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-agent-plan.md)
- **Thư mục Bằng chứng (Evidence):** [legacy-retirement-evidence/2026-11-13-run01/](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/)
- **Thời gian hoàn thành:** 2026-11-13 16:22:00
- **Trạng thái:** **HOÀN THÀNH TOÀN BỘ (L00–L09) — 100% PASS**

---

## 1. Tóm tắt Kết quả Thực hiện theo 10 Mốc (L00–L09)

1. **L00 — Baseline Tái lập & Inventory:**
   - Sửa đóng gói runner kiểm thử cô lập `tools/run_isolated_tests.py` theo đúng allowlist công khai: bổ sung `.streamlit` và template mẫu `data/hanoi_historical_gazetteer.json`.
   - Kết quả: Khắc phục triệt để lỗi harness cũ, đạt **239/239 PASS** ngay từ baseline.
   - Tạo đầy đủ 6 artifacts tài liệu evidence trong `AI/report/legacy-retirement-evidence/2026-11-13-run01/`.
2. **L01 — Chốt Ownership / Contracts & Mở rộng Guards:**
   - Chuyển cross-module private import trong `schema_intelligence/application/service.py` sang `.public`.
   - Mở rộng bộ kiểm thử biên kiến trúc `tests/test_architecture_boundaries.py` từ 4 lên **8 bài test**, bổ sung Quy tắc 5 (cấm cross-module private import), Quy tắc 6 (cấm frontend import repo), Quy tắc 7 (frontend chỉ gọi qua `.public`), kèm negative fixture fail-closed.
3. **L02 — Thống nhất Wiring & Public Boundaries:**
   - Khai báo `CommitCoordinatorPort` trong `backend/modules/projects/ports.py` và re-export tại `public.py`.
   - Bổ sung `get_project_lock(project_id)` vào `ProjectCommitCoordinator`.
   - `GraphQAApplicationService` nhận `Neo4jPort` qua dependency injection, loại bỏ import và khởi tạo concrete `Neo4jGateway()`.
   - `KGStudioFacade` ủy quyền việc khởi tạo cho `AppContainer` tại Composition Root, xóa sạch nhánh code tự dựng lại repositories/services.
   - `frontend/composition.py` và `backend/bootstrap.py` import 100% qua `.public` của 6 modules.
4. **L03 — Thay Đường Ghi & Khóa Legacy:**
   - `ProjectsApplicationService` và `ExtractionApplicationService` sử dụng trực tiếp khóa tiến trình từ `coordinator.get_project_lock(project_id)`, xóa bỏ các dict khóa riêng rẽ.
   - Xóa bỏ hoàn toàn fallback ghi âm thầm thiếu coordinator trong `_commit_curation_operation` và `apply_proposal_decisions`, chuyển sang ném `RuntimeError` rõ ràng (No-Bypass Persist Policy).
   - `_save_project_safe` trong `ExtractionApplicationService` đồng bộ projection dưới khóa an toàn.
5. **L04 — Thay Đọc Projection & Cache Thiếu Độ Mới:**
   - Các phương thức phân trang read projection (`query_edges_page`, `query_nodes_page`, `query_proposals_page`) nhận biết và đính kèm cờ `sync_pending` và `sync_error` vào kết quả trả về, ngăn ngừa việc hiển thị dữ liệu stale như dữ liệu mới.
6. **L05 — Tách I/O & Orchestration khỏi Domain:**
   - Rà soát 5 lát cắt nghiệp vụ (Schema Intelligence, Extraction, Curation, Graph QA, Training).
   - Giữ nguyên các hàm thuật toán thuần túy trong `domain/`, chuyển orchestration sang application services và cô lập I/O qua adapters/ports. Toàn bộ 13 cạnh allowlist được kiểm soát chặt chẽ.
7. **L06 — Migrate UI/API/CLI & Transport:**
   - UI kết nối qua `FrontendComposition` và các public application services.
   - REST API v1 (`backend/api/v1.py`) gọi trực tiếp application services.
   - Toàn bộ 7 kịch bản AppTest UI (U1–U7) đạt kết quả PASS.
8. **L07 — Retire Compatibility & Code Dư:**
   - Kiểm tra toàn bộ codebase sau refactor, bảo đảm không còn bất kỳ lời gọi nào tới code cũ.
   - Hoàn thiện bảng [deletion-ledger.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/deletion-ledger.md) cho tất cả 12 ứng viên C01–C12.
9. **L08 — Chuẩn hóa Comments & Cập nhật Hiện trạng:**
   - Cập nhật mục hiện trạng nợ migration trong [AGENTS.md](file:///d:/DATN/CrawData/KG_Studio/AGENTS.md) phản ánh các nợ đã được giải quyết bằng chứng kiểm thử.
   - Cập nhật tài liệu kiến trúc [AI/structure.md](file:///d:/DATN/CrawData/KG_Studio/AI/structure.md).
10. **L09 — Nghiệm thu Cuối & Đồng bộ Knowledge Graph:**
    - Chạy full isolated suite: **243/243 tests PASS** trong 9.565s.
    - Chạy `graphify update .`: Tái dựng thành công **2.977 nodes, 8.727 edges, 158 communities**.

---

## 2. Bảng Sổ cái Xóa / Chuyển đổi (Deletion Ledger Tổng hợp)

| ID | Vị trí / Ký hiệu Cũ | Thay thế / Chuẩn hóa Mới | Kết quả Kiểm thử |
| :--- | :--- | :--- | :--- |
| **C01** | `ExtractionApplicationService` tự giữ lock riêng và save trực tiếp | `ProjectCommitCoordinator.get_project_lock`, save đồng bộ projection | 26 extraction tests PASS |
| **C02** | Fallback ghi không coordinator trong curation/schema | Bắt buộc `commit_coordinator`; raise `RuntimeError` khi thiếu | 36 curation tests PASS, 8 EDC tests PASS |
| **C03** | `GraphQAApplicationService` tự khởi tạo `Neo4jGateway()` | Nhận `Neo4jPort` qua dependency injection từ `AppContainer` | 8 boundary tests PASS |
| **C04** | `KGStudioFacade` constructor tự dựng hạ tầng song song | Ủy quyền khởi tạo cho `AppContainer` tại Composition Root | 12 architecture & api tests PASS |
| **C05** | `frontend/composition.py` import private implementation | 100% import từ `backend.modules.<m>.public` | Quy tắc 7 AST Guard PASS |
| **C06** | 13 cạnh allowlist Domain -> Infrastructure | Cô lập I/O qua ports/adapters, bảo toàn thuật toán thuần | Quy tắc 3 AST Guard PASS |
| **C07** | Re-exports trong `catalogs/service.py` & `curation/service.py` | Giữ `__all__` tường minh làm compatibility facade cho helpers | 243 tests PASS |
| **C08** | UI components direct domain imports | Tách logic hiển thị khỏi tính toán thuần; presenter không mutate | 243 tests PASS |
| **C09** | `FrontendClient` local/remote transport | In-process mặc định qua facade; remote HTTP không local-mutate | 4 api tests PASS |
| **C10** | `frontend/state/session.py` (facade 159 LOC) | Re-export 100% symbols tường minh cho 30 consumers | 243 tests PASS |
| **C11** | 4 file UI monolithic cũ (`curation_table.py`, etc.) & expander lặp | Đã xóa sạch 4 file đơn và khối duplicate; thay bằng packages con | 243 tests PASS |
| **C12** | Comments/docstrings chưa chính xác | Chuẩn hóa docstring kỹ thuật giải thích rõ contract và giới hạn | 243 tests PASS |

---

## 3. Danh mục Hồ sơ Bằng chứng (Evidence Artifacts)

Mọi báo cáo chi tiết, log và ma trận kiểm thử được lưu trữ đầy đủ tại:
- [baseline.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/baseline.md)
- [candidates.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/candidates.md)
- [contracts.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/contracts.md)
- [decisions.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/decisions.md)
- [deletion-ledger.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/deletion-ledger.md)
- [feature-test-matrix.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/feature-test-matrix.md)
- [final-acceptance.md](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/final-acceptance.md)
- Các mốc nghiệm thu: [L00](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L00-result.md), [L01](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L01-result.md), [L02](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L02-result.md), [L03](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L03-result.md), [L04](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L04-result.md), [L05](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L05-result.md), [L06](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L06-result.md), [L07](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L07-result.md), [L08](file:///d:/DATN/CrawData/KG_Studio/AI/report/legacy-retirement-evidence/2026-11-13-run01/L08-result.md).
