# Báo cáo Triển khai Kế hoạch Thu gọn và Dùng chung Mã nguồn KG Studio

- **Thời gian thực hiện:** 31/10/2026
- **Kế hoạch tham chiếu:** [code-cleanup-plan.md](code-cleanup-plan.md)
- **Bản đồ kiến trúc cập nhật:** [structure.md](../structure.md)
- **Bộ kiểm thử:** 62/62 bài test PASS (100%), thời gian chạy ~2.1s
- **Môi trường Python:** Python 3.13.2 (Windows venv: `D:\DATN\CrawData\KG_Studio_MVP\.venv-win\Scripts\python.exe`)

---

## 1. Mục tiêu và Nguyên tắc Triển khai

Triển khai đầy đủ các nội dung đã được xác lập trong [code-cleanup-plan.md](code-cleanup-plan.md) theo chiến lược phân kỳ an toàn:
1. **Khóa hành vi bằng characterization test** trước và sau từng thay đổi.
2. **Bảo toàn 100% logic nghiệp vụ, định dạng dữ liệu (JSON/SQLite/Snapshots) và hợp đồng public exports.**
3. **Không phá vỡ bất kỳ ranh giới kiến trúc hay biện pháp an toàn/bảo mật nào đang có.**
4. **Tách module lớn theo nguyên lý đơn trách nhiệm (Single Responsibility Principle)** mà vẫn giữ trọn vẹn điểm truy cập facade tương thích ngược.

---

## 2. Chi tiết Kết quả Thực hiện theo Từng Đợt

### Đợt 1: Dọn Private Code, Khối Không thể tới và Import Dư thừa

Đã rà soát AST và kiểm tra references toàn diện trên toàn bộ codebase trước khi chỉnh sửa:
- **`frontend/pages/p04_edc_alignment.py`**:
  - Đã loại bỏ hàm private `_render_batch_history_and_restore()` không còn nơi gọi (do giao diện đã hội tụ vào Curation Hub trực tiếp sử dụng `render_decision_batch_history`).
  - Loại bỏ các import không sử dụng: `from typing import Any`, `render_decision_batch_history`, `reset_edc_state_if_project_changed`.
  - Giữ nguyên re-export `compute_edc_overview_counts` và entrypoint `render_edc_alignment_page` vì các file test và router vẫn tham chiếu hợp đồng này.
- **`frontend/pages/p05_curation_merge.py`**:
  - Đã loại bỏ hàm private `_render_curation_batch_history()` không còn sử dụng.
  - Loại bỏ các import chỉ phục vụ hàm chết (`typing.Any`, `render_decision_batch_history`, `reset_curation_state_if_project_changed`, `reset_edc_state_if_project_changed`).
  - Giữ nguyên `compute_curation_overview_counts` và `render_curation_merge_page`.
- **`shared/config_loader.py`**:
  - Tại hàm `default_catalogs()`: Đã xóa dòng mã chết không thể tới sau câu lệnh `return` (`return {key: knowledge[key] for key in CATALOG_KEYS}`).
  - Xóa import `CATALOG_KEYS` không sử dụng.
  - **Giữ chuẩn 100% giá trị trả về hiện hành**: `return {"relations": [], "entity_types": []}`.
- **`backend/facade.py`**:
  - Đã loại bỏ trường nội bộ `self._previews` write-only (chỉ gán vào dict khi preview EDC mà không có nơi đọc, gây nguy cơ rò rỉ bộ nhớ qua thời gian).
  - Dọn dẹp import prompt DTOs chưa được dùng trực tiếp tại facade: `ensure_project_prompt_history`, `PromptPreviewRequestDTO`, `PromptSaveRequestDTO`, `PromptVersionDTO`.
- **Làm sạch import dư thừa tại các module**:
  - `frontend/components/edc_alignment_panel.py`: Xóa `st`, `get_facade`, `get_client`, `edc_prompt`, `DEFAULT_EDC_PROMPT`, `EDCPlusRSettingsDTO`.
  - `frontend/components/curation_table.py` & `edc_review_table.py`: Xóa `import math` dư thừa sau khi đã dùng `paginate_items` chung.
  - `backend/domain/prompts/service.py`: Xóa `import copy`, `from typing import Any`, `PromptVersionDTO`.
  - `frontend/state/session.py`: Xóa `import json`, `STATUS_REJECTED`, `sha`.
  - `run_app.py`: Xóa `from pathlib import Path`.

---

### Đợt 2: Dùng Chung Helper Thuần Rủi Ro Thấp

- **Loader JSONL dùng chung cho ML Lab (`ml_lab/trainers/dataset_io.py`)**:
  - Gom hai hàm `_load_jsonl()` có thân AST trùng nhau giữa `train_canonicalizer.py` và `train_schema_retriever.py` thành `load_jsonl()` trong `ml_lab/trainers/dataset_io.py`.
  - Cả hai trainer và `benchmark.py` đều sử dụng tiện ích này, bảo đảm tính năng: trả về danh sách rỗng nếu file không tồn tại, bỏ qua dòng trắng, giữ nguyên thứ tự dòng, hỗ trợ UTF-8 có dấu tiếng Việt, và báo lỗi JSONDecodeError chuẩn xác nếu gặp dòng JSON hỏng.
- **Thao tác danh sách ID lựa chọn UI (`frontend/state/selection_core.py`)**:
  - Trích xuất các hàm thao tác ID thuần túy: `toggle_id_in_list()`, `append_unique_ids()`, `reconcile_id_selection()`.
  - Áp dụng vào cả hai phân hệ: đề xuất EDC (`toggle_proposal_selection`, `select_page_proposals`, `reconcile_selection_with_filter`) và cạnh quan hệ (`toggle_edge_selection`, `select_page_edges`, `reconcile_edge_selection_with_filter`).
  - **Giữ riêng rẽ điều kiện nghiệp vụ**: đề xuất EDC chỉ chọn `pending` theo đúng `kind`; cạnh quan hệ chỉ chọn `Chờ duyệt` hoặc `Cần kiểm tra`.
  - Bảo toàn 100% thứ tự ID, kiểu `list[str]`, và chuỗi thông báo chính xác ("mục" đối với đề xuất, "cạnh" đối với quan hệ).

---

### Đợt 3: Phân Rã Module Lớn (Curation Domain Decomposition)

Tệp `backend/domain/curation/service.py` trước đây có kích thước **2.099 dòng**, chứa lẫn lộn từ kiểm tra bằng chứng, đối chiếu văn bản, ràng buộc schema, duyệt cạnh, hồ sơ node, bậc kết nối, gợi ý trùng lặp đến gộp thực thể.

Đã phân rã thành kiến trúc phân tầng rõ trách nhiệm bên trong `backend/domain/curation/`:

```
backend/domain/curation/
├── __init__.py        # Re-export trọn vẹn package
├── common.py          # Tra cứu thực thể, quan hệ, tài liệu và chuẩn hóa chuỗi cơ sở (NFC/Display text, Aliases, Doc fingerprint, redirects)
├── evidence.py        # Đối chiếu câu trích dẫn bằng chứng, định vị span ký tự, xử lý ambiguous và direct slice
├── validation.py      # Kiểm tra ràng buộc schema EDC, điều kiện duyệt đơn/lô, kiểm tra tính xuất đồ thị Trang 6
├── review.py          # Duyệt đơn, duyệt lô hàng loạt, chỉnh sửa quan hệ kèm bảo vệ phiên bản (revision protection & batch receipt)
├── entities.py        # Quản lý hồ sơ thực thể, bậc đồ thị in/out, inverted index phát hiện nghi trùng O(N) và thống kê review_stats
├── merge.py           # Xem trước và thực thi gộp N thực thể, bảo toàn cạnh, ghi nhận endpoint history và cập nhật node_redirects
└── service.py         # Facade công khai, re-export 100% API cũ để đảm bảo backward compatibility tuyệt đối
```

**Bảo đảm tính toàn vẹn:**
- Bộ nhớ đệm `_DUPLICATE_SUGGESTIONS_CACHE` được khai báo trong `entities.py` và gán alias tại `service.py`, bảo đảm mọi bài kiểm thử hoặc công cụ benchmark truy cập cùng một đối tượng bộ nhớ duy nhất.
- Tất cả các caller hiện có (`facade.py`, `curation_table.py`, `evidence_panel.py`, `entity_merge_panel.py`, `test_curation_merge.py`, `benchmark_performance.py`...) tiếp tục import từ `backend.domain.curation.service` với 0% thay đổi.

---

### Đợt 4: Chuẩn Hóa Điều Phối Giao Dịch và SQLite Sync Safe

Trong `backend/facade.py`, logic đồng bộ SQLite an toàn và kiểm tra xung đột phiên làm việc trước đây bị lặp lại nhiều lần. Đã chuẩn hóa thành 2 helper phương thức chuyên biệt trong `KGStudioFacade`:

1. **`_sync_sqlite_safe(project: dict, result_dto=None) -> tuple[str, str]`**:
   - Tự động gọi `sqlite_repo.sync_from_project_dict(project)`.
   - Nếu thành công: xóa cờ `sync_pending`, xóa `sync_error`, cập nhật `result_dto.sync_status = "synced"`.
   - Nếu gặp lỗi: đánh dấu `sync_pending = True`, ghi `sync_error`, gán `result_dto.sync_status = "sync_pending"` mà **không làm crash hay rollback commit JSON đã thành công**.
   - Dùng chung cho: `load_project`, `save_project`, `restore_snapshot`, `apply_proposal_decisions`, và `_commit_curation_operation`.
2. **`_check_revision_conflict(proj_id, proj_name, project, expected_revision) -> None`**:
   - Chuẩn hóa kiểm tra optimistic locking cho cả EDC và Curation, phát hiện kịp thời nếu có phiên làm việc khác đã commit lên đĩa sau thời điểm preview.

---

### Đợt 5: Nghiệm Thu, Kiểm Thử Toàn Diện & Cập Nhật Tài Liệu

- **Bổ sung bộ test mới (`tests/test_code_cleanup.py`)** gồm 6 bài test:
  1. `test_default_catalogs_returns_empty_contract`: Kiểm tra hợp đồng danh mục mặc định rỗng.
  2. `test_ml_lab_load_jsonl_semantics`: Kiểm tra tính toàn vẹn của `load_jsonl` khi file trống, thiếu hoặc chứa tiếng Việt có dấu.
  3. `test_selection_core_helpers_order_and_types`: Kiểm tra thứ tự và kiểu dữ liệu của `toggle_id_in_list`, `append_unique_ids`, `reconcile_id_selection`.
  4. `test_curation_service_and_submodules_identity`: Kiểm tra tính đồng nhất tham chiếu của `curation/service.py` với các module con và cache.
  5. `test_facade_sqlite_sync_safe_and_revision_protection`: Kiểm tra hành vi an toàn của `_sync_sqlite_safe` và `_check_revision_conflict`.
  6. `test_facade_has_no_write_only_previews_leak`: Xác nhận facade không còn tồn tại thuộc tính `_previews`.
- **Chạy toàn bộ 62 test cases**:
  ```powershell
  Set-Location D:\DATN\CrawData\KG_Studio
  & 'D:\DATN\CrawData\KG_Studio_MVP\.venv-win\Scripts\python.exe' -m unittest discover -s tests -t . -v
  ```
  **Kết quả:** 62 tests, 0 failures, 0 errors, 0 skipped. Thời gian: ~2.1 giây.
- **Kiểm tra cú pháp toàn dự án**:
  ```powershell
  & 'D:\DATN\CrawData\KG_Studio_MVP\.venv-win\Scripts\python.exe' -m compileall -q .
  ```
  **Kết quả:** 0 lỗi cú pháp.
- **Kiểm tra CLI**:
  ```powershell
  & 'D:\DATN\CrawData\KG_Studio_MVP\.venv-win\Scripts\python.exe' run_app.py --check-config
  ```
  **Kết quả:** Exit code 0, cấu hình hợp lệ.
- **Cập nhật tài liệu kiến trúc**:
  Đã cập nhật [structure.md](../structure.md) ghi nhận đầy đủ cấu trúc phân rã của `curation/`, tiện ích `selection_core.py`, `dataset_io.py`, và bộ test 62 ca kiểm thử.

---

## 3. Bảng Tổng Hợp Chỉ Số Trước và Sau Dọn Dẹp

| Chỉ số / Thành phần | Trước khi dọn dẹp | Sau khi dọn dẹp | Đánh giá |
| :--- | :---: | :---: | :--- |
| **Số dòng `backend/domain/curation/service.py`** | 2.099 dòng | 108 dòng | Giảm 95% độ phức tạp của file facade; chia thành 6 module con mạch lạc |
| **Hàm private không dùng & mã không thể tới** | 3 vị trí | 0 | Đã dọn sạch `_render_batch_history_and_restore`, `_render_curation_batch_history`, dead `return` |
| **Trạng thái write-only leak RAM** | `facade._previews` | Đã loại bỏ | Tránh memory leak khi preview số lượng lớn |
| **Trùng lặp đọc tệp JSONL trong ML Lab** | 2 implementations | 1 module dùng chung (`dataset_io.py`) | Thống nhất cách xử lý lỗi và UTF-8 |
| **Trùng lặp thao tác danh sách ID giao diện** | 2 bộ code riêng trong `session.py` | 1 bộ core (`selection_core.py`) | Giữ nguyên điều kiện nghiệp vụ riêng của từng bảng |
| **Xử lý lỗi đồng bộ SQLite** | Lặp lại 5 lần trong `facade.py` | 1 hàm `_sync_sqlite_safe()` | Đồng nhất hành vi báo pending và không làm mất commit JSON |
| **Tổng số bài test tự động** | 56 tests | 62 tests | Tăng 6 bài kiểm chứng độ tương đồng logic, 100% PASS |

---

## 4. Kết luận

Toàn bộ các yêu cầu của [code-cleanup-plan.md](code-cleanup-plan.md) đã được thực thi triệt để. Mã nguồn của KG Studio Pro trở nên gọn gàng, rõ trách nhiệm, dễ bảo trì, loại bỏ được các vùng nhớ write-only không cần thiết trong khi vẫn duy trì độ tin cậy, an toàn dữ liệu và tính tương thích ngược 100%.

