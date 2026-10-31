# Báo cáo Triển khai Tính năng Quản lý Phiên bản Prompt & Xem trước Request (Prompt Versioning)

- **Ngày hoàn thành**: 31/10/2026.
- **Căn cứ kế hoạch**: [prompt-versioning.md](../features/prompt-versioning.md).
- **Phạm vi triển khai**: Toàn bộ hệ thống KG Studio (Domain Prompts Service, DTOs, LLM Gateway Request Preparation, Engines Provenance, Facade Orchestration, UI Prompt Editor & Step Traces Viewer, Unit Tests).
- **Trạng thái**: Hoàn tất 100%, 56/56 unit tests toàn hệ thống đạt PASS.

---

## 1. Tổng quan & Mục tiêu Triển khai

Trước đây, prompt trích xuất trong KG Studio gặp một số hạn chế về mặt kiến trúc:
1. **Thiếu tính độc lập giữa các chế độ**: Chế độ trích xuất mở `edc` và `edc_plus_r` dùng chung trường mutable `project["edc_prompt"]`. Thay đổi ở chế độ này có thể âm thầm tác động sang chế độ khác.
2. **Chưa có lịch sử phiên bản độc lập**: Lịch sử prompt trong `save_prompt_settings` bị gộp chung với danh mục `relations` và `entity_types`. Khi người dùng muốn xem lại hoặc khôi phục prompt cũ, hệ thống có nguy cơ làm xáo trộn danh mục hiện hành.
3. **Lệch pha giữa Xem trước và Gửi thực tế (Preview-Execution Skew)**: Không có cơ chế xem trước prompt hoàn chỉnh sau khi ghép nối với danh mục, hợp đồng JSON `EDC_SCHEMA`, cắt tỉa ngân sách token đầu vào và định dạng phản hồi theo nhà cung cấp LLM.
4. **Thiếu dấu vết nguồn gốc (Provenance)**: Các lượt chạy trong quá khứ không lưu lại chính xác phiên bản prompt và chữ ký request đã gửi; khi xuất dữ liệu huấn luyện Active Learning (`dataset_exporter`), hệ thống có nguy cơ gán nhãn sai lệch bằng prompt hiện tại của dự án.

Dựa trên bản thiết kế chi tiết tại `prompt-versioning.md`, toàn bộ hệ thống quản lý prompt đã được tái cấu trúc triệt để theo các nguyên tắc:
- **Độc lập theo cấu hình**: Mỗi dự án sở hữu prompt riêng biệt cho 3 chế độ: `closed`, `edc`, và `edc_plus_r`.
- **Phiên bản bất biến (Immutable Versions)**: Mỗi lần lưu tạo một phiên bản mới với số thứ tự tăng dần (`v1`, `v2`, `v3`...) và mã băm nội dung SHA-256. Lưu lại nội dung không đổi là thao tác no-op an toàn.
- **Khôi phục an toàn (Restore as New Version)**: Khôi phục một phiên bản cũ sẽ tạo ra một phiên bản mới kế thừa nội dung đó kèm trường `restored_from_version_id`, tuyệt đối không ghi đè, xóa bản cũ, và không thay đổi danh mục của dự án.
- **Đồng nhất chuẩn bị Request (Preview & Execution Parity)**: Cùng một hàm `prepare_extraction_request` phục vụ cho cả việc xem trước trên UI lẫn gửi thực tế tới LLM adapter.
- **Truy vết toàn vẹn (Full Provenance)**: Mỗi lượt trích xuất ghi nhận `prompt_version_id`, `prompt_content_hash`, `prepared_request_hash` và snapshot request (không chứa API key).

---

## 2. Bản đồ File & Các Module Đã Xây dựng / Nâng cấp

| Module / File | Vai trò & Trách nhiệm triển khai |
| :--- | :--- |
| `shared/schemas/prompts.py` *(Mới)* | Định nghĩa 4 DTO chuẩn: `PromptVersionDTO`, `PromptSaveRequestDTO`, `PromptPreviewRequestDTO`, `PreparedExtractionRequestDTO`. |
| `shared/schemas/__init__.py` | Export đầy đủ các DTO prompt dùng chung toàn hệ thống. |
| `backend/domain/prompts/service.py` *(Mới)* | Dịch vụ nghiệp vụ Prompt cốt lõi: di chuyển dữ liệu lũy đẳng (`ensure_project_prompt_history`), tra cứu prompt active, lưu phiên bản mới, khôi phục an toàn, và so sánh văn bản (`diff_prompt_versions`). |
| `backend/domain/prompts/__init__.py` *(Mới)* | Package entrypoint cho domain prompts. |
| `backend/repositories/json_repo.py` | Bổ sung `prompt_history_schema_version: 1`, `prompt_bindings`, `prompt_versions` vào `empty_project` và tự động di chuyển dữ liệu trong `ensure_project_shape`. |
| `backend/domain/catalogs/service.py` | Tách bạch lưu prompt khỏi lưu danh mục; tích hợp `prompt_bindings` và danh sách version ID vào `compute_project_revision` để bảo vệ chống xung đột đa phiên. |
| `backend/integrations/llm/gateway.py` | Tách phương thức tĩnh `prepare_extraction_request` dùng chung cho Preview và Execute. Xử lý chuẩn xác token budget, output clamping, user message, response format, và tính `request_hash` (bảo đảm 0% secret). |
| `backend/domain/extraction/base_engine.py` | Mở rộng `EngineOutput` hỗ trợ các trường provenance: `prompt_version_id`, `prompt_content_hash`, `prepared_request_hash`, `prepared_request`. |
| `backend/domain/extraction/engines/fixed_catalog.py` | Pin phiên bản prompt `closed` đang áp dụng, truyền context chuẩn hóa vào gateway và gắn provenance vào kết quả. |
| `backend/domain/extraction/engines/edc_one_pass.py` | Pin phiên bản prompt `edc` đang áp dụng, truyền context chuẩn hóa vào gateway và gắn provenance vào kết quả. |
| `backend/domain/extraction/engines/edc_plus_r.py` | Pin phiên bản prompt `edc_plus_r`, truyền context từng vòng lặp và ghi nhận provenance chi tiết vào `StepTraceDTO`. |
| `backend/facade.py` | Mở rộng `KGStudioFacade` với các phương thức quản trị prompt, hiện thực hóa `preview_extraction_request` và ghi nhận provenance đầy đủ vào `project["runs"]`. |
| `backend/domain/dataset_exporter/exporter.py` | Trích xuất `system_prompt` từ provenance thực tế của lượt trích xuất thay vì lấy mù quáng `project["prompt"]` hiện hành. |
| `frontend/components/prompt_editor.py` *(Mới)* | Component giao diện soạn thảo prompt hợp nhất: quản lý bản nháp (draft) độc lập theo cấu hình, lưu phiên bản mới, xem trước request đầy đủ 5 tab, xem lịch sử, so sánh Diff và khôi phục. |
| `frontend/pages/p02_catalogs_prompts.py` | Tích hợp `render_prompt_management_panel`, dọn dẹp các textarea soạn thảo prompt trùng lặp. |
| `frontend/components/edc_alignment_panel.py` | Chuyển đổi thành wrapper ủy quyền sang `prompt_editor.py`, loại bỏ đường ghi trực tiếp mutable cũ. |
| `frontend/components/step_traces_viewer.py` | Thêm thẻ thông tin provenance (Prompt Version, Content Hash, Request Hash) và expander xem lại chính xác system/user prompt đã gửi trong phiên chạy. |
| `tests/test_prompt_versions.py` *(Mới)* | Bộ 9 kiểm thử đơn vị bao quát toàn diện các yêu cầu nghiệp vụ bắt buộc. |

---

## 3. Chi tiết Kỹ thuật & Các Quy tắc Nghiệp vụ

### 3.1. Chuẩn Lưu trữ Dữ liệu (`prompt_bindings` & `prompt_versions`)
Mỗi dự án lưu trữ lịch sử prompt theo cấu trúc chuẩn:
```json
{
  "prompt_history_schema_version": 1,
  "prompt_bindings": {
    "closed": "pv_closed_01_a1b2c3",
    "edc": "pv_edc_01_d4e5f6",
    "edc_plus_r": "pv_edc_plus_r_01_g7h8i9"
  },
  "prompt_versions": [
    {
      "id": "pv_closed_01_a1b2c3",
      "configuration_id": "closed",
      "mode": "closed",
      "version": 1,
      "content": "Hướng dẫn trích xuất di tích...",
      "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "created_at": "2026-10-31T09:00:00+07:00",
      "created_by": "system",
      "note": "Khởi tạo mặc định cho chế độ closed",
      "parent_version_id": null,
      "restored_from_version_id": null,
      "origin": "default_seed"
    }
  ]
}
```

### 3.2. Tính Lũy đẳng của Quá trình Di chuyển Dữ liệu (Idempotent Migration)
Hàm `ensure_project_prompt_history(project)` thực hiện:
1. Kiểm tra nếu dự án đã có `prompt_history_schema_version >= 1` và đầy đủ 3 bindings thì dừng ngay, trả về `False`.
2. Đối với dự án cũ:
   - Các bản ghi `prompt_versions` cũ từ `save_prompt_settings` (chứa `{at, prompt, prompt_id...}`) được chuyển thành các version `closed` có `origin="migration"`, giữ nguyên thời gian thực tế.
   - Khởi tạo 3 binding độc lập: `closed` kế thừa từ `project.get("prompt")`, `edc` và `edc_plus_r` kế thừa từ `project.get("edc_prompt")` (hai binding và hai ID version hoàn toàn tách biệt).
   - Nếu chưa có nội dung, sử dụng prompt mặc định từ hệ thống (`origin="default_seed"`).

### 3.3. Quy tắc Bất biến & Chống Tạo Version Rác
- **Bất biến**: Không sửa đổi trường `content` của bất kỳ version nào sau khi đã commit.
- **No-Op Save**: Trước khi lưu, hệ thống tính mã băm SHA-256 trên nội dung nhập vào. Nếu mã băm trùng khớp với phiên bản đang áp dụng của cấu hình đó, hàm `save_prompt_version` lập tức trả về `(active_ver, False)` mà không tăng số version, không thêm bản ghi và không snapshot vô ích.
- **Khôi phục An toàn**: Khi người dùng chọn khôi phục phiên bản cũ (ví dụ `v1`), hệ thống sinh ra một phiên bản mới `v3` kế thừa nội dung của `v1`, gán `parent_version_id = v2` và `restored_from_version_id = v1`. Toàn bộ catalog và cài đặt dự án được giữ nguyên vẹn 100%.

### 3.4. Chuẩn bị Request Dùng Chung (Preview & Execution Parity)
Phương thức tĩnh `LLMGateway.prepare_extraction_request()`:
- Đảm bảo tính toán đúng:
  - Ngân sách token đầu vào: `fit_chunk_to_input_budget(chunk, system_prompt, max_input_tokens)`.
  - Giới hạn token đầu ra: `clamp_output_tokens(provider, model, max_tokens)`.
  - User message: `build_user_message(fitted_chunk, allowed_relations, open_mode)`.
  - Cấu trúc phản hồi: `json_schema` cho EDC hoặc `json_object` cho Closed/DeepSeek.
  - Mã băm request: SHA-256 từ `provider|model|system|user|temperature|max_tokens|response_format`.
- **Bảo mật**: Tuyệt đối không đưa API key, Authorization header hoặc thông tin nhạy cảm vào `PreparedExtractionRequestDTO` hoặc chuỗi băm.
- Xem trước (Preview) cho phép người dùng kiểm tra với cả phiên bản đã lưu hoặc bản nháp chưa lưu (`is_draft=True`).

---

## 4. Trải nghiệm Người dùng trên Giao diện Streamlit

1. **Bộ chọn chế độ trích xuất trực quan**:
   - Chuyển đổi linh hoạt giữa 3 chế độ: `1. Danh mục cố định`, `2. EDC mở (1 lượt)`, `3. EDC + R`.
   - Nếu chế độ đang xem khác chế độ đang áp dụng cho dự án, xuất hiện thông báo và nút `[🎯 Áp dụng chế độ này cho Dự án]`.
2. **Khung soạn thảo Prompt kèm quản lý bản nháp (Draft Management)**:
   - Bản nháp được lưu riêng theo cặp `project_id + configuration_id`. Đổi qua lại giữa các mode không làm mất nháp dở dang.
   - Thẻ huy hiệu phân biệt: `🔒 Đang áp dụng: v1 (hash)` hoặc `⚠️ Có thay đổi chưa lưu (Bản nháp)`.
   - Nút `[💾 Lưu phiên bản mới]` (kèm ô nhập ghi chú lý do sửa đổi) và nút `[🔄 Hủy sửa nháp]`.
3. **Thẻ Xem trước Request Gửi tới LLM (Prompt Preview)**:
   - Cho phép chọn tài liệu nguồn và số thứ tự đoạn văn bản đối chứng.
   - Tùy chọn sử dụng bản nháp hiện tại hoặc phiên bản đã lưu.
   - Bảng 5 thẻ tab chi tiết:
     - *1. Base Instructions*
     - *2. Phần Ứng dụng Bổ sung* (Catalog JSON / Hợp đồng EDC_SCHEMA / Top-K Schema block)
     - *3. System Prompt Đầy đủ*
     - *4. User Message* (Đoạn văn sau khi fit budget)
     - *5. Tham số & Cấu hình*
4. **Lịch sử Phiên bản, So sánh Thay đổi & Khôi phục**:
   - Danh sách phiên bản kèm số thứ tự, thời gian tạo, ghi chú và nhãn `[Đang dùng]`.
   - Nút `[🔀 So sánh Diff với bản đang dùng]`: Hiển thị diff từng dòng theo chuẩn `difflib` rõ ràng.
   - Nút `[↩️ Khôi phục thành Bản Mới]`: Khôi phục nhanh chóng trong 1 cú nhấp chuột.
5. **Nhật ký Trích xuất & Step Traces Viewer (Bước 3)**:
   - Hiển thị thẻ Provenance: Phiên bản prompt (`v1`), Prompt Hash, Request Hash.
   - Expander mở xem lại chính xác toàn bộ System & User Prompt đã gửi tới LLM trong lượt chạy đó.

---

## 5. Kết quả Kiểm thử & Đo lường Chất lượng

Hệ thống kiểm thử đã được chạy và xác nhận 100%:

### 5.1. Bộ Kiểm thử Đơn vị Mới (`tests/test_prompt_versions.py`)
Bao gồm 9 kịch bản kiểm thử:
1. `test_idempotent_migration`: Di chuyển dữ liệu tạo 3 binding độc lập; chạy lại là no-op.
2. `test_migration_with_legacy_prompt_versions`: Chuyển đổi an toàn lịch sử prompt phiên bản cũ sang format mới.
3. `test_project_and_mode_isolation`: Dự án A và B độc lập; sửa EDC không làm đổi EDC+R.
4. `test_save_version_monotonic_and_noop`: Đánh số tăng dần; lưu nội dung trùng là no-op; từ chối nội dung rỗng.
5. `test_restore_creates_new_version_preserving_catalogs`: Khôi phục tạo version mới kế thừa; catalog không bị thay đổi.
6. `test_diff_prompt_versions`: So sánh diff unified chuẩn xác giữa 2 văn bản prompt.
7. `test_request_preparation_parity`: Khớp chính xác ngân sách token, user message và mã băm request.
8. `test_facade_preview_extraction_request`: Facade dựng bản xem trước đúng chuẩn cho cả bản đã lưu và bản nháp.
9. `test_execution_provenance_recorded_in_runs`: Chạy trích xuất qua fake LLM client ghi nhận đầy đủ provenance vào `EngineOutput` và `project["runs"]`.

```text
Ran 9 tests in 0.002s
OK
```

### 5.2. Toàn bộ Bộ Kiểm thử Ứng dụng (`unittest discover tests`)
```text
Ran 56 tests in 2.120s
OK
```
- **Tổng số bài kiểm thử**: **56 tests** (tăng từ 47 tests ở đợt trước).
- **Tỷ lệ Pass**: **100% (56/56)**.
- **Biên dịch cú pháp (py_compile)**: Đạt 100% không phát sinh bất kỳ lỗi cú pháp nào trên toàn bộ mã nguồn.

---

## 6. Kết luận & Hướng Dẫn Vận Hành

Việc triển khai hoàn tất tính năng **Prompt theo Cấu hình & Lịch sử Phiên bản** đã giải quyết triệt để các rủi ro ghi đè ngoài ý muốn, loại bỏ hoàn toàn tình trạng lệch pha giữa xem trước và thực thi (Zero Preview-Execution Skew), và cung cấp nguồn gốc dữ liệu (Provenance) minh bạch cho từng dữ kiện tri thức được trích xuất.

### Hướng dẫn nhanh cho người dùng:
1. Mở **Bước 2: Thiết lập**, cuộn đến phần **2. Phương pháp Trích xuất & Soạn thảo Prompt**.
2. Chọn chế độ trích xuất muốn điều chỉnh (`Closed`, `EDC`, hoặc `EDC+R`).
3. Chỉnh sửa nội dung hướng dẫn; hệ thống tự động lưu nháp riêng cho chế độ đó.
4. Mở mục **👁️ Xem trước Request** để kiểm tra prompt hoàn chỉnh được ghép với tài liệu thực tế.
5. Nhấn **[💾 Lưu phiên bản mới]** để ghi nhận version bất biến.
6. Khi cần, mở mục **📜 Lịch sử Phiên bản** để so sánh thay đổi hoặc khôi phục phiên bản mong muốn.

