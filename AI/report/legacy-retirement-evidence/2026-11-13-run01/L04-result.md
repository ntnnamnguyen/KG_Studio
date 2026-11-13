# Kết quả Nghiệm thu Mốc L04 — Thay Đọc Projection & Cache Thiếu Độ Mới

- **Run ID:** `2026-11-13-run01`
- **Mốc:** `L04`
- **Trạng thái:** `PASS`
- **Thời gian hoàn thành:** 2026-11-13 16:18:00

---

## 1. Đầu vào & Mục tiêu

- **Đầu vào:** Kết quả L03, `ProjectsApplicationService` queries, `SQLiteProjectRepository` phân trang, vector cache.
- **Mục tiêu:**
  1. Thiết lập hợp đồng độ mới (Freshness Contract) tường minh cho các truy vấn phân trang read projection (`query_edges_page`, `query_nodes_page`, `query_proposals_page`).
  2. Phản ánh trạng thái `sync_pending` và `sync_error` trực tiếp trong kết quả trả về của các truy vấn để caller nhận biết dữ liệu projection có thể bị chậm (stale) so với bản authoritative JSON.
  3. Duy trì tính nhất quán khi đồng bộ lại qua `resync_sqlite`.

---

## 2. Các Thay đổi Triển khai

1. **`ProjectsApplicationService` Freshness Awareness:**
   - Khi nhận tham số là một đối tượng `project` (dict), các phương thức `query_edges_page`, `query_nodes_page`, `query_proposals_page` kiểm tra và đính kèm trạng thái `sync_pending` và `sync_error` vào kết quả phân trang.
   - Khi không có `read_projection`, trả về cấu trúc phân trang rỗng chuẩn hóa kèm `sync_pending: False` thay vì sinh lỗi không xác định.
2. **Khôi phục Tính Đồng bộ (`resync_sqlite`):**
   - Giữ nguyên cơ chế đồng bộ lại toàn bộ các thực thể, quan hệ và đề xuất sang SQLite, xóa cờ `sync_pending` trên đĩa và cập nhật in-memory đối tượng `project` an toàn dưới khóa `get_project_lock(proj_id)`.

---

## 3. Kết quả Kiểm thử & Đánh giá Cổng L04

- **Kiểm thử Hiệu năng & Điều phối:**
  - `tests.test_performance_optimizations`: 12/12 tests PASS.
  - `tests.test_commit_coordinator`: 6/6 tests PASS.
  - Tổng cộng: **18/18 tests PASS** (0 failures, 0 errors, 0.235s).
- **Quyết định:** Đạt toàn bộ tiêu chí của mốc **L04**, sẵn sàng chuyển sang mốc **L05 — Tách I/O/orchestration khỏi domain**.
