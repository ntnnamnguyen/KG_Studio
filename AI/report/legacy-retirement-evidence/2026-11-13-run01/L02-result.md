# Kết quả Nghiệm thu Mốc L02 — Thống nhất Wiring & Public Boundaries

- **Run ID:** `2026-11-13-run01`
- **Mốc:** `L02`
- **Trạng thái:** `PASS`
- **Thời gian hoàn thành:** 2026-11-13 16:15:00

---

## 1. Đầu vào & Mục tiêu

- **Đầu vào:** Kết quả L01, các ứng viên C03, C04, C05.
- **Mục tiêu:**
  1. Loại bỏ việc tự khởi tạo repository/service trùng lặp trong constructor của `KGStudioFacade`, chuyển toàn bộ về ủy quyền cho `AppContainer` (Composition Root).
  2. Bổ sung `CommitCoordinatorPort` vào ports của `projects` và public API.
  3. Cung cấp phương thức công khai `get_project_lock(project_id: str) -> threading.RLock` trên `ProjectCommitCoordinator`.
  4. Loại bỏ việc khởi tạo tự phát `Neo4jGateway()` bên trong constructor của `GraphQAApplicationService`, chuyển sang nhận `Neo4jPort` qua dependency injection.
  5. Thống nhất toàn bộ imports của `backend/bootstrap.py` sử dụng `.public` của 6 modules.

---

## 2. Các Thay đổi Triển khai

1. **`backend/modules/projects/ports.py` & `public.py`:**
   - Định nghĩa `CommitCoordinatorPort` mô tả hợp đồng điều phối transaction commit và lock cho dự án.
   - Re-export `CommitCoordinatorPort` trong `public.py`.
2. **`backend/modules/projects/application/commit_coordinator.py`:**
   - Bổ sung phương thức `get_project_lock(self, project_id: str) -> threading.RLock` trả về khóa tiến trình chuẩn hóa.
3. **`backend/modules/graph_qa/application/service.py`:**
   - Chuyển `__init__` nhận `neo4j_gateway: Neo4jPort | None = None` từ port trừu tượng thay vì import concrete gateway.
   - Thêm guard kiểm tra `self.neo4j_gateway is None` trong `sync_neo4j` và `test_neo4j`.
4. **`backend/facade.py`:**
   - Xóa bỏ toàn bộ nhánh `else:` tự import `JsonProjectRepository`, `SQLiteProjectRepository`, `VectorIndexRepository` và tự dựng 6 services.
   - Ủy quyền fallback construction sang `AppContainer` tại Composition Root.
5. **`backend/bootstrap.py`:**
   - Chuyển toàn bộ 6 import Application Services sang import từ `backend.modules.<m>.public`.

---

## 3. Kết quả Kiểm thử & Đánh giá Cổng L02

- Chạy kiểm thử ranh giới và composition:
  - Lệnh: `.\.venv-win\Scripts\python.exe tools\run_isolated_tests.py tests.test_architecture_boundaries tests.test_api_v1_and_composition`
  - Kết quả: **12/12 tests PASS** (0 failures, 0 errors, 0.992s).
- **Quyết định:** Đạt toàn bộ tiêu chí của mốc **L02**, sẵn sàng chuyển sang mốc **L03 — Thay đường ghi và khóa legacy**.
