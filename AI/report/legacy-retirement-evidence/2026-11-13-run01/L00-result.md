# Kết quả Nghiệm thu Mốc L00 — Baseline Tái lập & Inventory

- **Run ID:** `2026-11-13-run01`
- **Mốc:** `L00`
- **Trạng thái:** `PASS`
- **Thời gian hoàn thành:** 2026-11-13 16:11:00

---

## 1. Đầu vào & Bối cảnh Kiểm chứng

- **Git HEAD:** `c92a6d6f689177c98e3ec998ce2cf2c6d8389b38`
- **Python Runtime:** 3.13.2 (Windows)
- **Mục tiêu:** Tái lập baseline kiểm thử cô lập chính xác, tạo cấu trúc thư mục artifacts lưu trữ evidence, audit đầy đủ inventory C01–C12, kiểm tra hoạt động của Graphify và isolated test runner.

---

## 2. Các Công việc Đã Hoàn thành

1. **Đóng gói Runner Kiểm thử Cô lập (`tools/run_isolated_tests.py`):**
   - Đã khai báo allowlist chính xác cho thư mục `.streamlit/` (chứa `config.toml` phục vụ kiểm thử theme) và tệp template từ điển mẫu công khai `data/hanoi_historical_gazetteer.json` vào shadow workspace tạm.
   - Không sao chép toàn bộ thư mục `data/` hay secrets, bảo đảm tính cô lập tuyệt đối và an toàn dữ liệu.
2. **Chạy Baseline Test Suite:**
   - Lệnh: `.\.venv-win\Scripts\python.exe tools\run_isolated_tests.py`
   - Kết quả: **239/239 tests PASS** (0 failures, 0 errors, 9.594s). Lỗi 1 failure / 1 error phát hiện ở lần audit cũ do thiếu theme và template mẫu đã được giải quyết triệt để.
3. **Kiểm tra Công cụ Graphify:**
   - Đã chạy `graphify query "legacy coordinator lock"` thành công, kết quả trả về 2.836 nodes và 8.480 edges.
4. **Tạo Bộ Artifacts Chuẩn trong `AI/report/legacy-retirement-evidence/2026-11-13-run01/`:**
   - `baseline.md`: Hồ sơ phiên bản, môi trường, test results và working tree inventory.
   - `candidates.md`: Phân loại và hiện trạng chi tiết của 12 ứng viên C01–C12.
   - `contracts.md`: Hợp đồng 6 public modules và Coordinator Commit Lifecycle.
   - `decisions.md`: 5 quyết định kiến trúc cốt lõi D01–D05.
   - `deletion-ledger.md`: Sổ cái ghi nhận các file/khối code đã xóa/chuyển đổi.
   - `feature-test-matrix.md`: Ma trận ánh xạ 9 nhóm tính năng sang các bài test tương ứng.

---

## 3. Đánh giá Cổng Kiểm soát L00 (Gate Review)

- [x] Baseline tái lập hoàn toàn trên môi trường cô lập, 100% test đạt kết quả OK.
- [x] Không còn lỗi che giấu hành vi cần bảo vệ.
- [x] Đã hoàn thành inventory và bộ tài liệu lưu trữ evidence.
- **Quyết định:** Đạt điều kiện chuyển sang mốc **L01 — Chốt ownership/contracts và mở rộng guards**.
