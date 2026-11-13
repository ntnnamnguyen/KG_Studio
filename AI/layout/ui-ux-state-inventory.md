# Kiểm kê Trạng thái, Tính năng & Session Keys (Đợt U0)

> **Ngày lập:** 2026-11-13  
> **Mục đích:** Điểm xuất phát kiểm kê toàn bộ trạng thái hiển thị, ma trận giữ nguyên tính năng (không mất điểm truy cập), `st.session_state` keys và phạm vi cấu hình trước khi triển khai các đợt U1–U6 theo [ui-ux-improvement-plan.md](ui-ux-improvement-plan.md).  
> **Cơ sở đo lường Usability (Baseline U0):** **Chưa xác minh usability với người dùng thực** (chưa có dữ liệu đo thời gian/số lỗi thao tác của 5–8 người dùng thử). Đã chạy kiểm chứng tự động baseline qua unittest + `AppTest` với kết quả **30/30 PASS** (`test_layout_pipeline`, `test_free_triples_ui`, `test_baseline_graph_ui`, `test_architecture_boundaries`, `test_curation_hub`).

---

## 1. Kiểm kê Trạng thái Hiện hành trên 5 Bước

| Bước / Màn hình | Trạng thái 1: Dự án rỗng | Trạng thái 2: Đã có dữ liệu bình thường | Trạng thái 3: Lỗi / Bị chặn / Cảnh báo | Trạng thái 4: Nghiên cứu / Baseline B |
| :--- | :--- | :--- | :--- | :--- |
| **Shell (`app.py`, `pipeline_banner.py`)** | Badge: Doc `○`, Setup `!`/`✓`, Ext `○`, Rev `○`, Exp `○`. Header và Sidebar đều render bộ điều hướng 5 bước cạnh tranh nhau. | Badge cập nhật động; `overall_next` chỉ sang bước tiếp theo. | Có thể xảy ra lỗi kết nối LLM nếu thiếu API key; nút `Mở / Tạo dự án` gộp chung gây mơ hồ khi nhập tên mới. | Baseline B đặt Setup=`✓`, bỏ qua bảng duyệt Bước 4 trong readiness, trỏ thẳng sang Bước 5 nếu đã có run `ok`. |
| **Bước 1 (`p01_projects_docs.py`)** | Next Action disable; hiện `st.info` rỗng và **ẩn** danh sách + nút tiếp theo. | Hiển thị `st.dataframe` 7 cột (nặng chỉ số kỹ thuật như số ký tự/ước tính đoạn), `expander` xem trước 3.000 ký tự, footer `[1, 2]`. | Hiện card `chunk_errors` (nếu có lỗi từ Bước 3) hoặc `pending+check > 0`. Khi nạp nhiều file, `success/warning` chỉ in tuần tự dễ bị đẩy trôi khi `st.rerun()`. | Không thay đổi theo engine. |
| **Bước 2 (`p02_catalogs_prompts.py`)** | `relations`/`entity_types` có thể rỗng; `gazetteer_panel` luôn giữ khung 1 dòng trống. | 4 vùng dọc; LLM Expander trùng widget chỉnh sửa với Sidebar; Prompt Editor mở thẳng text area kỹ thuật cùng EDC+R params và danh mục 3 tab; ML Lab lồng 2 expander liên tiếp. | Khi đổi radio chế độ nhưng chưa bấm `Áp dụng`, dễ gây nhầm chế độ đang áp dụng thật trên dự án. | `MODE_FREE_TRIPLES`: vẫn hiện 3 tab Danh mục & Từ điển dù engine Baseline B không sử dụng chúng khi chạy trích xuất. |
| **Bước 3 (`p03_extraction.py`)** | `not docs`: dừng sớm với `st.info`, ẩn toàn bộ tham số và nhật ký. | Khung chọn file co giãn (`280px` / `content`), tham số chunk/overlap/workers hiển thị trực tiếp, 2 nút Dry-run / Chạy toàn bộ, Nhật ký Step Traces & Raw JSON. | `p03_last_failed_tasks` hiện cảnh báo + nút chạy lại; thiếu API key báo `st.error` khi bấm nút. Chỉnh token trùng với Sidebar/Bước 2. | `MODE_FREE_TRIPLES`: hiện `st.info`, xuất JSON thô/diagnostics trong Nhật ký và tải `free_triples_baseline.json`; dẫn thẳng sang Bước 5. |
| **Bước 4 (`p04_curation_hub.py`)** | Metrics = 0; nút hành động chính ẩn; bảng hiển thị `st.info` rỗng. | 6 KPI + 3 phím tắt + `st.radio` 3 phân khu (`schema`, `edges`, `entities`). Bộ lọc mặc định `status="all"` trên edges (không ưu tiên hàng đợi cần kiểm tra). Đã gỡ Gazetteer khỏi Bước 4, chỉ giữ notice khi gộp. | `sync_pending` hiện banner resync SQLite; `_curation_return_context` hiện nút quay lại Phân khu Quan hệ; cạnh vướng danh mục hiện nút nhảy sang Phân khu 1. | Không dùng cho Baseline B (chỉ dùng cho đồ thị đã ingest `closed`, `edc`, `edc_plus_r`). |
| **Bước 5 (`p05_graph_export.py`)** | `approved` rỗng (0 nodes/0 edges); tab QA yêu cầu có cạnh mới chạy; tab Export hiện info rỗng. | Radio 3 nguồn (`approved`, `baseline`, `external`); 3 metrics; 4 tab (`Hỏi đáp`, `Benchmark`, `Sinh Dữ liệu`, `Bản đồ & Xuất`). Đang lộ nhiều cấu hình thuật toán (PCST/PPR/alpha) ngay ở cấp 1 của người mới. | Chọn >1 attempt cùng chunk trong Baseline B -> báo lỗi tường minh (không tự chọn nhầm). Không fallback từ `approved` rỗng sang đồ thị thô. | `baseline` hoặc `external`: ẩn Gói ZIP 11 tệp, Neo4j và khóa Tab `Sinh Dữ liệu Huấn luyện`. |

---

## 2. Ma trận Ánh xạ Chức năng (Feature Preservation Matrix)

> Bảo đảm **100% tính năng hiện tại vẫn có đường truy cập rõ ràng**, không bị xóa bỏ âm thầm trong U1–U6.

| Tính năng / Capability | Vị trí hiện tại (Before) | Vị trí đích sau Cải tiến (After U1–U6) | Ghi chú bảo toàn Contract / Owner |
| :--- | :--- | :--- | :--- |
| Chọn dự án có sẵn | Sidebar (`selectbox`) | Sidebar — khu **Dự án đang làm việc** (tách riêng với Tạo dự án) | `facade.list_projects()`, `active_project_name` |
| Tạo dự án mới theo tên | Sidebar (nút gộp `➕ Mở / Tạo dự án`) | Sidebar — Expander/Form riêng **➕ Tạo dự án mới** (tách rõ mở vs tạo mới) | `facade.load_project()`, `facade.save_project()` |
| Điều hướng 5 bước | Sidebar `st.radio` + Header `st.columns(5)` | **Sidebar `st.radio` làm điều hướng chính**; Header thành dải tóm tắt trạng thái dự án & bước (vẫn giữ hàm `render_pipeline_header` để tương thích callers/test) | `PIPELINE_STEPS`, `PAGE_LABELS`, `navigate_to_step()` |
| Sửa LLM Provider / Model / URL / Key / Tokens | Trùng ở **3 nơi** (Sidebar Expander, Bước 2 Vùng 1, Bước 3 Expander) | **Một nơi chỉnh sửa duy nhất tại Bước 2**; Sidebar & Bước 3 hiển thị tóm tắt trạng thái kết nối + nút nhảy sang Bước 2 | Giữ callbacks `on_sb_llm_*` & `on_p02_llm_*` trong `session.py` cho tương thích |
| Lưu cấu hình mặc định TOML / `.secrets.toml` | Sidebar + Bước 2 + Bước 3 | Tập trung tại Bước 2 kèm giải thích phạm vi (**Áp dụng cho mặc định toàn cục**, không ghi đè riêng từng project) | `save_llm_token_config_to_toml`, `save_api_key`, `delete_api_key` |
| Upload `.txt`/`.docx`/`.pdf` + Xem danh sách & preview văn bản | Bước 1 | Bước 1: luồng `Chọn tệp -> Kết quả từng tệp -> Danh sách gọn (Tên, Trạng thái, Nguồn) -> Chi tiết & Preview 3,000 ký tự` | `facade.add_document()`, `count_chunks()` |
| Chọn Engine (`closed`, `edc`, `edc_plus_r`, `free_triples`) | Bước 2 Radio 4 mục | Bước 2: mỗi engine có mô tả **Mục đích · Đầu ra · Yêu cầu · Giới hạn** + thẻ **Đang áp dụng** vs **Đang chọn xem trước** | Giữ nguyên 4 mode ID & `btn_apply_proj_mode` |
| Soạn Prompt, Draft, Preview Request, Diff History, Tham số `+R` | Bước 2 (hiện trực tiếp text area ngay đầu) | Bước 2: giữ trong **Khu Cài đặt Nâng cao / Nghiên cứu (Prompt & Tham số `+R`)**, mở theo lựa chọn `expanded` trong session; không áp dụng nháp khi đổi tab | Giữ `draft_prompt_*`, `btn_build_preview_*`, `btn_save_edcr_params` |
| Quản lý Loại thực thể, Quan hệ, Từ điển Bí danh | Bước 2 Vùng 3 (3 tab) | Bước 2 Vùng 3 (3 tab); hiển thị ghi chú rõ **chỉ có hiệu lực với engine dùng danh mục/liên kết thực thể** (không áp dụng cho Baseline B) | `gazetteer_panel.py`, `p02_catalogs_prompts.py` |
| ML Lab & Active Learning (`sr_triplets`, `canonicalization`, `sft`, QLoRA) | Bước 2 Vùng 4 (2 expander lồng nhau) | Bước 2 — khu **Phòng thí nghiệm Nghiên cứu (ML Lab)** cấp đơn (1 expander duy nhất, không lồng 2 cấp), giữ nguyên mọi nút & key | `render_ml_lab_panel()` |
| Chọn tài liệu, Dry-run, Chạy song song, Retry lỗi, Step Traces, Raw JSON | Bước 3 | Bước 3: luồng chính gọn (`Chọn tài liệu -> Tóm tắt cấu hình & phạm vi -> Chạy thử / Chạy chính -> Kết quả`); Chunk/Overlap/Workers vào khu **Tùy chỉnh kỹ thuật (Nâng cao)**; Step Traces/Raw JSON vào **Chi tiết kỹ thuật** | Giữ keys `btn_dry_run_one_chunk`, `btn_run_full_extraction`, `p03_btn_baseline_graph`, retry |
| Duyệt EDC 2 bảng + Bulk Actions + Auto Alignment + Batch History | Bước 4 Phân khu 1 | Bước 4 Phân khu 1: giữ đủ 2 bảng, `All-or-Nothing` / `Valid-Only`, Preview trước Apply, Auto Alignment (gắn nhãn rõ không phải quyết định người dùng) | `edc_review_table.py`, `edc_bulk_actions.py` |
| Duyệt Quan hệ + Đối chiếu Bằng chứng 2 cột + Sửa & Lịch sử | Bước 4 Phân khu 2 | Bước 4 Phân khu 2: mặc định lọc ưu tiên hàng đợi cần kiểm tra (`pending`/`check`), thêm nút **Mục trước / Mục tiếp theo**, quyết định gần bằng chứng, sửa & lịch sử vào tab phụ | `curation_table.py`, `evidence_panel.py` |
| Quản lý Hồ sơ Thực thể & Gộp Thực thể/Quan hệ/Loại/Khử trùng | Bước 4 Phân khu 3 | Bước 4 Phân khu 3: giữ 2 chế độ + 4 tab gộp, hiển thị rõ đối tượng giữ lại/bị gộp/ảnh hưởng cạnh/từ điển; xác nhận cụ thể cho hành động xóa | `entity_tab.py`, `relation_tab.py`, `entity_type_tab.py`, `triple_dedup_tab.py` |
| Hỏi đáp, Graphviz, Benchmark, Training QA Studio, Xuất JSON/ZIP/Neo4j | Bước 5 | Bước 5: chọn nguồn tường minh (`approved` / `baseline` theo tài liệu->đoạn->lần / `external`); **Chế độ Khám phá** (tìm đối tượng/hỏi đáp + bảng + bằng chứng + xuất) tách rõ với **Khu Nghiên cứu** (PCST/PPR/Naive, Benchmark, Training Studio, Neo4j) | Giữ nguyên `GraphSnapshotDTO`, keys `_gret_*`, `p05_*`, `btn_prep_zip` |

---

## 3. Kiểm kê Session Keys, Selection, Draft, Pagination & Phạm vi Cấu hình

### 3.1. Phân tầng Phạm vi Cấu hình
1. **Global Config (`config/default.toml` + `config/.secrets.toml`):** Lưu `provider`, `model`, `base_url`, `max_input_tokens`, `max_output_tokens`, `chunk_size` và API keys riêng từng provider. **Không tự gán vào riêng từng project JSON.**
2. **Session UI State (`st.session_state`):**
   - Điều hướng & shell: `active_project_name`, `_loaded_name`, `project`, `active_page`, `active_step`.
   - Cấu hình LLM phiên hiện tại: `llm_provider`, `llm_model`, `llm_base_url`, `llm_api_key`, `llm_max_input_tokens`, `llm_max_output_tokens`, `extraction_chunk_size`, `extraction_workers`, cặp widget keys `sb_llm_*` & `p02_llm_*` (được giữ tương thích cho tests).
   - Trạng thái giao diện nâng cao / mở rộng: các cờ nhớ trạng thái xem Nâng cao / Nghiên cứu theo phiên (không tự ghi vào file project).
3. **Project Authoritative State (`data/projects/<slug>/project.json`):** `extraction_mode`, `prompt_versions`, `entity_types`, `relations`, `relation_notes`, `domain_gazetteer`, `edc_plus_r_settings`, `documents`, `runs`, `nodes`, `edges`, `schema_proposals`, `chunk_errors`.
4. **Run Provenance (bất biến theo từng lượt chạy trong `project["runs"]`):** `run_id`, `prompt_version_id`, `prompt_content_hash`, `prepared_request_hash`, `prepared_request`, `extraction_mode`, `model`, `input_tokens`, `output_tokens`.

### 3.2. Inventory Keys Phức hợp theo Project / Widget
- **Prompt & Preview (Bước 2):** `draft_prompt_{proj_id}_{mode}`, `last_preview_{mode}`, `show_diff_{mode}`, `ml_last_export`.
- **Trích xuất (Bước 3):** `p03_doc_sel_{doc_id}`, `p03_filter_doc_text`, `p03_slider_workers`, `p03_chk_extract_all`, `p03_num_max_chunks`, `p03_last_failed_tasks`.
- **Kiểm duyệt EDC (Bước 4):** `_edc_active_project_id`, `_edc_tables[entity_types|relations]` chứa `selected_ids` (ID-based), `focused_proposal_id`, `drafts`, `active_preview`, `preview_decisions`, `preview_request_id`, `filters` (`status="pending"`, `page_size=50`, `page=1`, `last_filter_sig`), `flash_messages`, `filter_prune_notice`.
- **Kiểm duyệt Quan hệ, Thực thể & Gộp (Bước 4):** `_curation_active_project_id`, `_curation_active_section`, `_curation_return_context`, `curation_hub_active_tab`, `_hub_request_tab`, `hub_entity_submode_radio`, `_curation_sections[edges|entities|merge]` chứa `selected_ids`, `focused_edge_id`, `focused_node_id`, `member_ids`, `active_preview`, `filters` (`page_size=25`, `page=1`, `last_filter_sig`).
- **Khai thác & Xuất (Bước 5):** `p05_graph_source_{pid}`, `p05_baseline_runs_{pid}`, `_p06_external_graph_{pid}`, `_p06_edge_limit_{pid}`, `_export_cache_{pid}_{fingerprint}`, `_gret_method_{pid}`, `_gret_bench_result_{pid}`, `_gret_last_result_{pid}`, `_gret_query_input_{pid}`.
