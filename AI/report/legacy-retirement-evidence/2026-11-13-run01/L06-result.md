# Kết quả Nghiệm thu Mốc L06 — Migrate UI/API/CLI & Transport

- **Run ID:** `2026-11-13-run01`
- **Mốc:** `L06`
- **Trạng thái:** `PASS`
- **Thời gian hoàn thành:** 2026-11-13 16:20:00

---

## 1. Đầu vào & Mục tiêu

- **Đầu vào:** Kết quả L05, các trang Streamlit (`p01`–`p05`), `FrontendComposition`, `FrontendClient`, REST API v1 (`backend/api/v1.py`).
- **Mục tiêu:**
  1. Bảo đảm UI gọi backend thông qua `FrontendComposition` và các public application services.
  2. Rà soát `FrontendClient` phân biệt rõ ràng giữa in-process local execution và remote HTTP.
  3. Duy trì tính nhất quán của API v1 sử dụng trực tiếp application services.

---

## 2. Các Thay đổi Triển khai & Rà soát

1. **`frontend/composition.py`:**
   - Hoàn tất chuyển đổi tất cả 6 dịch vụ sang import từ `.public` của từng module nghiệp vụ.
   - Hoàn thành ranh giới không cho phép components tự can thiệp vào concrete repository hay save sequences.
2. **`frontend/client.py`:**
   - In-process execution là chế độ mặc định (`api_base_url = ""`), ủy quyền qua facade và composition root.
   - Không cho phép remote HTTP âm thầm chuyển sang ghi đè file cục bộ nếu remote server trả lỗi.
3. **`backend/api/v1.py`:**
   - Các endpoint REST API v1 (`/api/v1/projects`, `/api/v1/projects/{name}`) gọi trực tiếp qua `ProjectsApplicationService` thay vì truy cập trực tiếp repository.

---

## 3. Kết quả Kiểm thử

- Chạy kiểm thử API v1 và Composition:
  - `tests.test_api_v1_and_composition`: 4/4 tests PASS (0.302s).
- **Quyết định:** Đạt toàn bộ tiêu chí của mốc **L06**, sẵn sàng chuyển sang mốc **L07 — Retire compatibility và code dư**.
