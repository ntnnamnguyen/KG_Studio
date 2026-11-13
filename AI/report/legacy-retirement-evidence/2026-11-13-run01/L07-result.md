# Kết quả Nghiệm thu Mốc L07 — Retire Compatibility & Code Dư

- **Run ID:** `2026-11-13-run01`
- **Mốc:** `L07`
- **Trạng thái:** `PASS`
- **Thời gian hoàn thành:** 2026-11-13 16:21:00

---

## 1. Đầu vào & Mục tiêu

- **Đầu vào:** Kết quả L06, bảng ứng viên C01–C12, `deletion-ledger.md`.
- **Mục tiêu:**
  1. Kiểm tra toàn bộ callers sau khi refactor, bảo đảm không còn lời gọi nào tới các symbol/fallback đã bị loại bỏ.
  2. Ghi nhận quyết định cho từng ứng viên trong `deletion-ledger.md`.
  3. Xác nhận tính toàn vẹn của các public facade (`session.py`, `KGStudioFacade`) và các package markers `__init__.py`.

---

## 2. Kết quả Rà soát & Audit Callers

1. **Không còn bất kỳ tham chiếu nào tới 4 file UI monolithic cũ:**
   - Cả 4 file `curation_table.py`, `evidence_panel.py`, `edc_review_table.py`, `edc_bulk_actions.py` đã bị xóa hoàn toàn khỏi đĩa và được thay thế bằng các package có `__all__` tương thích 100%.
2. **Không còn fallback bypass coordinator trong nghiệp vụ Curation và Schema:**
   - Cả 2 service `CurationApplicationService` và `SchemaIntelligenceApplicationService` đã được bọc guard kiểm tra `commit_coordinator`, cấm hoàn toàn hành vi âm thầm mutate bộ nhớ khi thiếu coordinator.
3. **Các Facade Tương thích Ngược có Chủ đích:**
   - `frontend/state/session.py` (159 LOC) được bảo lưu có chủ đích làm Compatibility Facade để phục vụ 30 callers và test suite mà không gây xáo trộn import.
   - `backend/domain/catalogs/service.py` và `backend/domain/curation/service.py` được bảo lưu làm re-export facade cho các hàm thuần túy với danh sách `__all__` tường minh.

---

## 3. Kết luận Cổng L07

- [x] Không còn reference không chủ đích tới symbol/fallback đã xóa.
- [x] Toàn bộ quyết định retire / replace / keep_public đã được ghi nhận chi tiết trong `deletion-ledger.md`.
- **Quyết định:** Đạt toàn bộ tiêu chí của mốc **L07**, sẵn sàng chuyển sang mốc **L08 — Chuẩn hóa comments và tài liệu**.
