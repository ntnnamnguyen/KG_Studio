# Quyết định Kiến trúc & Chiến lược Tương thích (Decisions)

- **Run ID:** `2026-11-13-run01`

---

## D01: Thống nhất Quản lý Lock Quá trình (Process-Wide RLock) về `ProjectCommitCoordinator`
- **Vấn đề:** `ExtractionApplicationService` tự giữ từ điển `_project_locks` độc lập, trong khi `ProjectsApplicationService` và `ProjectCommitCoordinator` có lock riêng, dẫn đến nguy cơ xung đột khi ghi đồng thời giữa extraction và curation.
- **Quyết định:** Bổ sung phương thức công khai `get_project_lock(self, project_id: str) -> threading.RLock` vào `ProjectCommitCoordinator` và khai báo trong `CommitCoordinatorPort`. `ExtractionApplicationService` và `CurationApplicationService` bắt buộc dùng lock được cấp từ coordinator.
- **Ranh giới:** RLock chỉ bảo vệ an toàn trong cùng tiến trình (In-Process Execution); không tuyên bố an toàn đa tiến trình ngầm khi chưa có cơ chế file-lock/IPC chuyên biệt.

## D02: Loại bỏ Hoàn toàn Fallback Ghi Không Coordinator (No-Bypass Persist Policy)
- **Vấn đề:** Các phương thức như `_commit_curation_operation` và `apply_proposal_decisions` có nhánh `else:` âm thầm ghi trực tiếp vào `project_store.save_project(project)` hoặc mutate bộ nhớ mà không qua commit/revision guard.
- **Quyết định:** Khi thực hiện thao tác thay đổi dữ liệu có lưu trữ (persistent command), nếu không có `commit_coordinator`, hệ thống bắt buộc ném ngoại lệ rõ ràng (`RuntimeError`). Các trường hợp chạy thử hoặc mô phỏng thuần túy (dry-run, preview) phải sử dụng API riêng biệt (`preview_*`).

## D03: Chuẩn hóa Dependency Injection Container làm SSOT Wiring
- **Vấn đề:** `KGStudioFacade` tự import repositories và dựng lại các services trong nhánh `else:` của constructor khi không nhận container. `GraphQAApplicationService` tự khởi tạo `Neo4jGateway()`.
- **Quyết định:** `AppContainer` trong `backend/bootstrap.py` là Composition Root duy nhất. `KGStudioFacade` ủy quyền việc khởi tạo cho `AppContainer`. `GraphQAApplicationService` nhận `Neo4jGateway` hoặc `Neo4jPort` qua injection từ `AppContainer`.

## D04: Bắt buộc Giao tiếp Liên Module qua Public APIs
- **Vấn đề:** `frontend/composition.py` và một số test import trực tiếp từ các file private nội bộ (ví dụ: `.application.service`).
- **Quyết định:** Mọi lời gọi liên module và từ frontend vào backend bắt buộc đi qua `backend.modules.<m>.public`. Mở rộng AST Guard trong `tests/test_architecture_boundaries.py` để tự động phát hiện và chặn vi phạm.

## D05: Cơ chế Tương thích Ngược (Compatibility Facade Policy)
- **Quyết định:** Giữ các facade như `frontend/state/session.py` và `KGStudioFacade` với các re-export tường minh (`__all__`), không sử dụng wildcard import (`import *`) hoặc `__getattr__` delegation. Chỉ gỡ bỏ facade sau khi toàn bộ callers và test seams đã chuyển đổi hoàn toàn.
