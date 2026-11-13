# Báo cáo Tái cấu trúc Mô-đun hóa Tầng Frontend (`components/` & `state/`)

- **Ngày hoàn thành:** 2026-11-13
- **Phạm vi:** Phân tách và tái cấu trúc 9 tệp lớn nhất trong `frontend/components/` và `frontend/state/` theo lộ trình 3 đợt (Đợt 1 → Đợt 2 → Đợt 3).
- **Trạng thái nghiệm thu:** Đã hoàn thành cả 3 đợt; toàn bộ 239 bài kiểm thử offline và 4 bài kiểm thử biên kiến trúc (`test_architecture_boundaries.py`) đạt **100% PASS** sau từng đợt và sau đợt cuối.

---

## 1. Tổng quan & Nguyên tắc Thiết kế

Việc tái cấu trúc được thực hiện nhằm xử lý tình trạng phình to mã nguồn tại tầng giao diện Streamlit (có tệp lên tới 1.214–1.383 dòng code do trộn lẫn tính toán thuần, quản lý `st.session_state`, và dựng UI Streamlit), đồng thời tuân thủ nghiêm ngặt các bất biến kiến trúc trong `AGENTS.md`:

1. **Giữ nguyên 100% hành vi & tương thích ngược:** Toàn bộ chữ ký hàm công khai, widget `key=...`, khóa `st.session_state`, và luồng gọi qua `FrontendClient` / `get_facade()` được bảo toàn tuyệt đối.
2. **Re-export tường minh qua `__all__`:** Không sử dụng `from ... import *` hoặc `__getattr__` delegation để che giấu phụ thuộc. Mọi package hoặc facade giữ tương thích đều khai báo `__all__` tường minh.
3. **Tách lớp Logic / View & State DAG:**
   - Logic lọc, sắp xếp, chuẩn bị dòng bảng, xem trước (preview), và thực thi hàng loạt được tách khỏi mã dựng widget Streamlit.
   - `frontend/state/session.py` được phân tách thành đồ thị phụ thuộc không chu trình (DAG): `core.py` + `curation_state.py` + `edc_state.py` + `llm_state.py` → `navigation.py` → `session.py` (facade re-export).
4. **Sửa lỗi trùng lặp phát hiện khi tách:** Loại bỏ khối `st.expander("🔍 Đọc Đoạn văn bản Chunk gốc của các Quan sát")` bị nhân đôi dưới nhánh `if cands:` trong `edc_review_table` khi tách sang `edc_review_table/drawer.py`.

---

## 2. Chi tiết Thực hiện 3 Đợt & Đối sánh Số dòng Code (LOC)

### 2.1. Tổng hợp Thực hiện Theo Đợt

- **Đợt 1 (Ưu tiên cao nhất — Khử 2 tệp >1.200 LOC):**
  - Chuyển `frontend/components/curation_table.py` (1.214 LOC) thành package `frontend/components/curation_table/` gồm `edge_logic.py`, `edge_view.py`, `entity_logic.py`, `entity_view.py` và `__init__.py` (re-export cả `paginate_items` cho consumer cũ).
  - Tách `frontend/state/session.py` (1.383 LOC) thành 5 module DAG (`core.py`, `curation_state.py`, `edc_state.py`, `llm_state.py`, `navigation.py`) và giữ `session.py` làm lớp facade re-export tường minh toàn bộ ký hiệu (bao gồm `_safe_set_widget_state` cho `p02_catalogs_prompts.py`).
- **Đợt 2 (Ưu tiên trung bình — Các bảng, inspector EDC/Curation & phân hệ Merge):**
  - Chuyển `frontend/components/evidence_panel.py` (558 LOC) thành package `frontend/components/evidence_panel/` (`html_format.py`, `edge_inspector.py`, `entity_inspector.py`, `__init__.py`).
  - Chuyển `frontend/components/edc_review_table.py` (669 LOC) thành package `frontend/components/edc_review_table/` (`logic.py`, `drawer.py`, `table_view.py`, `__init__.py`).
  - Chuyển `frontend/components/edc_bulk_actions.py` (539 LOC) thành package `frontend/components/edc_bulk_actions/` (`logic.py`, `view.py`, `__init__.py`).
  - Trong `frontend/components/merge/`: tách `entity_logic.py` khỏi `entity_tab.py` (vẫn re-export tường minh `build_entity_merge_preview`, `execute_entity_merge_apply`, `_format_gazetteer_merge_notice` trong `entity_tab.py` để giữ tương thích test/consumer) và phân rã `entity_tab.py`, `relation_tab.py` thành các hàm `_render_*` đơn trách nhiệm.
- **Đợt 3 (Dọn sạch các component UI đơn tệp >400 LOC):**
  - Phân rã `render_prompt_management_panel` trong `frontend/components/prompt_editor.py` thành 5 helper (`_render_mode_selector_and_apply`, `_render_prompt_draft_editor`, `_render_prompt_request_preview`, `_render_prompt_version_history`, `_render_edc_plus_r_settings`), giữ nguyên `get_facade()` gọi trong hàm điều phối để bảo toàn test monkeypatch.
  - Phân rã `render_g_retriever_qa_tab` trong `frontend/components/export_tabs/g_retriever_tab.py` thành 5 helper (`_read_llm_runtime_params`, `_render_sample_questions_and_query_input`, `_render_retrieval_params_expander`, `_render_compare_all_methods_panel`, `_render_single_method_qa_result`), gom logic đọc cấu hình LLM về một helper dùng chung.

### 2.2. Bảng Đối sánh LOC Trước & Sau Khi Tái cấu trúc

| Đợt | Tệp Gốc (Trước) | LOC Trước | Cấu trúc Sau Tái cấu trúc | LOC Từng Tệp (Sau) | Số Hàm Top-Level | Ghi chú / Review Trách nhiệm |
| :--- | :--- | ---: | :--- | ---: | ---: | :--- |
| Đợt 1 | `frontend/components/curation_table.py` | 1.214 | `curation_table/__init__.py`<br>`curation_table/edge_logic.py`<br>`curation_table/edge_view.py`<br>`curation_table/entity_logic.py`<br>`curation_table/entity_view.py` | 33<br>380<br>479<br>130<br>296 | 0<br>8<br>3<br>2<br>1 | Tách rõ tính toán bảng/batch khỏi render UI; mỗi tệp < 480 LOC. |
| Đợt 1 | `frontend/state/session.py` | 1.383 | `state/core.py`<br>`state/curation_state.py`<br>`state/edc_state.py`<br>`state/llm_state.py`<br>`state/navigation.py`<br>`state/session.py` (facade) | 123<br>466<br>489<br>109<br>252<br>159 | 5<br>26<br>19<br>7<br>2<br>0 | Chuyển 1 tệp 1.383 LOC thành 5 module DAG < 490 LOC + facade `__all__`. |
| Đợt 2 | `frontend/components/evidence_panel.py` | 558 | `evidence_panel/__init__.py`<br>`evidence_panel/html_format.py`<br>`evidence_panel/edge_inspector.py`<br>`evidence_panel/entity_inspector.py` | 12<br>24<br>437<br>169 | 0<br>1<br>6<br>3 | Tách riêng formatter HTML, inspector cạnh và inspector hồ sơ thực thể. |
| Đợt 2 | `frontend/components/edc_review_table.py` | 669 | `edc_review_table/__init__.py`<br>`edc_review_table/logic.py`<br>`edc_review_table/drawer.py`<br>`edc_review_table/table_view.py` | 26<br>223<br>168<br>310 | 0<br>6<br>3<br>2 | Đã loại bỏ expander chunk gốc bị lặp trong nhánh `if cands:` ở `drawer.py`. |
| Đợt 2 | `frontend/components/edc_bulk_actions.py` | 539 | `edc_bulk_actions/__init__.py`<br>`edc_bulk_actions/logic.py`<br>`edc_bulk_actions/view.py` | 12<br>123<br>493 | 0<br>3<br>5 | Tách preview/apply logic khỏi 4 sub-renderer + 1 hàm điều phối UI. |
| Đợt 2 | `frontend/components/merge/entity_tab.py` | 572 | `merge/entity_logic.py`<br>`merge/entity_tab.py` | 96<br>512 | 3<br>4 | `entity_tab.py` hơi vượt ngưỡng 500 LOC (512 LOC) do giữ toàn bộ UI 3 bước gộp thực thể và khối re-export tương thích; logic nghiệp vụ preview/apply đã tách sang `entity_logic.py`, phần view đã chia thành 3 section helper + coordinator nên chưa cần chia nhỏ cơ học thêm (theo `AGENTS.md` Mục 3). |
| Đợt 2 | `frontend/components/merge/relation_tab.py` | 481 | `merge/relation_tab.py` | 491 | 5 | Tổ chức thành 4 section helper (`_render_ai_semantic_relation_section`, `_render_fuzzy_relation_matching_section`, `_render_manual_relation_and_dedup_section`, `_render_relation_merge_history_section`) + `render_relation_merge_tab`. |
| Đợt 3 | `frontend/components/prompt_editor.py` | 404 | `components/prompt_editor.py` | 468 | 6 | Tách hàm điều phối 341 LOC thành 5 helper chức năng rõ ràng + `render_prompt_management_panel`. |
| Đợt 3 | `frontend/components/export_tabs/g_retriever_tab.py` | 410 | `export_tabs/g_retriever_tab.py` | 449 | 7 | Tách hàm điều phối 329 LOC thành 5 helper + `build_subgraph_dot` + `render_g_retriever_qa_tab`. |

---

## 3. Sổ cái Xóa / Chuyển đổi File (Deletion & Migration Ledger)

Tuân thủ điều kiện bắt buộc trước khi xóa tại `AGENTS.md` Mục 6, toàn bộ caller/import trong `app.py`, `frontend/`, `tests/`, `backend/`, `shared/`, `ml_lab/`, `tools/` đã được kiểm tra bằng AST trước khi thay thế các tệp `.py` đơn lẻ bằng package:

| Path / Symbol Bị Xóa hoặc Chuyển Đổi | Lý do | Consumers Đã Kiểm tra | Thay Thế Chính thức | Điều kiện Tương thích Ngược | Kết quả Test Xác minh |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `frontend/components/curation_table.py` (file đơn) | Thay thế bằng package tách lớp logic/view | `p04_curation_hub.py`, `test_curation_hub.py`, `test_curation_merge.py` (`paginate_items`), `test_ui_ux_improvements.py`, `test_performance_optimizations.py` | `frontend/components/curation_table/` (`__init__.py`, `edge_logic.py`, `edge_view.py`, `entity_logic.py`, `entity_view.py`) | `__init__.py` khai báo `__all__` export đầy đủ toàn bộ public symbols + `paginate_items`. | 239 tests PASS (sau Đợt 1, Đợt 2, Đợt 3) |
| `frontend/components/evidence_panel.py` (file đơn) | Thay thế bằng package tách formatter, edge & entity inspector | `p04_curation_hub.py`, `test_ui_ux_improvements.py`, `test_curation_hub.py` | `frontend/components/evidence_panel/` (`__init__.py`, `html_format.py`, `edge_inspector.py`, `entity_inspector.py`) | `__init__.py` re-export tường minh `format_highlighted_evidence_html`, `render_edge_evidence_and_inspector_panel`, `render_entity_profile_inspector`. | 239 tests PASS (sau Đợt 2, Đợt 3) |
| `frontend/components/edc_review_table.py` (file đơn) | Thay thế bằng package tách logic, drawer, table_view | `p04_curation_hub.py`, `test_edc_bulk_review.py`, `test_ui_ux_improvements.py` | `frontend/components/edc_review_table/` (`__init__.py`, `logic.py`, `drawer.py`, `table_view.py`) | `__init__.py` re-export tường minh toàn bộ helper lọc/phân trang/hiển thị và drawer/table renderer. | 239 tests PASS (sau Đợt 2, Đợt 3) |
| `frontend/components/edc_bulk_actions.py` (file đơn) | Thay thế bằng package tách logic & view | `p04_curation_hub.py`, `test_edc_bulk_review.py` | `frontend/components/edc_bulk_actions/` (`__init__.py`, `logic.py`, `view.py`) | `__init__.py` re-export tường minh `build_preview_for_scope`, `execute_batch_apply`, `quick_apply_proposal_batch`, `render_edc_bulk_actions`. | 239 tests PASS (sau Đợt 2, Đợt 3) |
| `frontend/state/session.py` (chuyển từ monolithic 1.383 LOC sang re-export facade 159 LOC) | Loại bỏ god-module state nhưng vẫn giữ nguyên import path cho toàn bộ pages & tests | `app.py`, `p01`–`p05`, `pipeline_banner.py`, `edc_review_table/`, `edc_bulk_actions/`, `curation_table/`, `evidence_panel/`, `merge/`, `tests/` (bao gồm `_safe_set_widget_state` tại `p02_catalogs_prompts.py`) | 5 module DAG: `core.py`, `curation_state.py`, `edc_state.py`, `llm_state.py`, `navigation.py` | `session.py` khai báo `__all__` tường minh cho 100% symbol gốc. Gỡ shim sau khi toàn bộ consumer chuyển import trực tiếp sang 5 module con. | 239 tests PASS (sau Đợt 1, Đợt 2, Đợt 3) |
| Khối expander `"🔍 Đọc Đoạn văn bản Chunk gốc của các Quan sát"` lặp lần 2 dưới `if cands:` trong `edc_review_table.py` | Trùng lặp copy-paste y hệt khối đã render ở nhánh `if obs:` | Kiểm tra trực tiếp trong nhánh `if cands:` của `render_proposal_detail_drawer` | Giữ 1 khối duy nhất trong nhánh `if obs:` tại `edc_review_table/drawer.py` | Không cần shim; giữ đúng 1 expander đọc chunk gốc cho mỗi proposal. | 239 tests PASS (sau Đợt 2, Đợt 3) |

---

## 4. Kết quả Kiểm chứng & Đồng bộ Hệ thống

### 4.1. Bộ kiểm thử tự động (`unittest`)

Thực thi bằng trình thông dịch chuẩn của dự án `.\.venv-win\Scripts\python.exe`:

| Mốc Kiểm chứng | Lệnh thực thi | Kết quả | Thời gian |
| :--- | :--- | :--- | :--- |
| Sau **Đợt 1** | `.\.venv-win\Scripts\python.exe -m unittest discover -s tests -t .` | `Ran 239 tests` — **OK** (0 failures, 0 errors) | 86.043s |
| Sau **Đợt 2** | `.\.venv-win\Scripts\python.exe -m unittest discover -s tests -t .` | `Ran 239 tests` — **OK** (0 failures, 0 errors) | 23.558s |
| Sau **Đợt 3** (Final) | `.\.venv-win\Scripts\python.exe -m unittest discover -s tests -t .` | `Ran 239 tests` — **OK** (0 failures, 0 errors) | 26.039s |
| Kiểm tra biên kiến trúc | `.\.venv-win\Scripts\python.exe -m unittest tests/test_architecture_boundaries.py` | `Ran 4 tests` — **OK** | 0.643s |

### 4.2. Cập nhật Tài liệu & Knowledge Graph

- **Tài liệu kiến trúc:** Đã cập nhật mục 2.5 trong [AI/structure.md](file:///d:/DATN/CrawData/KG_Studio/AI/structure.md#L298-L320) phản ánh chính xác cấu trúc package mới tại `frontend/state/` và `frontend/components/`.
- **Knowledge Graph (`graphify update .`):**
  - Đã chạy `graphify update .` thành công (mã thoát `0`).
  - Kết quả cập nhật đồ thị AST: `AST cache: 204/235 files served from cache (86%); 31 to extract`, tái dựng `2836 nodes, 8480 edges, 131 communities` vào `graphify-out/`.
