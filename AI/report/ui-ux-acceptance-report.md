# Báo cáo Triển khai & Nghiệm thu Cải tiến UI/UX (Đợt U0 – U7)

> **Tài liệu tham chiếu gốc:** [ui-ux-improvement-plan.md](../layout/ui-ux-improvement-plan.md)  
> **Trạng thái nghiệm thu kỹ thuật:** Hoàn tất triển khai toàn bộ 8 đợt **U0 – U7**; kiểm thử offline (`235 tests`) & kiến trúc boundary (`test_architecture_boundaries.py`) đạt **OK** (0 lỗi, 0 bỏ qua).  
> **Lưu ý trung thực nghiên cứu:** Các kiểm thử tự động (`AppTest` + `unittest`) xác nhận đúng hành vi hiển thị, phân tách trạng thái, điều hướng và tính toàn vẹn; **khía cạnh cảm nhận trực quan & usability trên người dùng thực tế chưa được đo đạc/kiểm thử (chưa xác minh usability với người dùng thực)**.

---

## 1. Tóm tắt Thay đổi Trước / Sau (Before vs After) theo Từng Đợt

| Đợt | Trọng tâm | Trước khi cải tiến (Before) | Sau khi cải tiến (After) |
| :--- | :--- | :--- | :--- |
| **U0** | Kiểm kê & Thiết kế | Thiếu bảng trạng thái chuẩn hóa, thuật ngữ đôi chỗ lệch ("Trang 4", "Chạy thử", `closed`), chưa có wireframe thống nhất 5 màn hình. | Tạo [ui-ux-state-inventory.md](../layout/ui-ux-state-inventory.md) và [ui-ux-wireframes.md](../layout/ui-ux-wireframes.md) khóa thuật ngữ, state keys và ma trận trạng thái 5 bước. |
| **U1** | Shell, Theme & Điều hướng | Chưa có `[theme]` trong `.streamlit/config.toml`; 5 nút pipeline ở header cạnh tranh trực tiếp với radio Sidebar; Sidebar lẫn input "Mở/Tạo dự án" chung và chứa form/slider LLM trùng lặp Bước 2. | Khai báo `[theme]` sáng rõ ràng (`primaryColor = "#1D4ED8"`), thêm `_inject_scoped_styles()` (`1rem`, `max-width: 1400px`, `:focus-visible`, responsive wrap `@media (max-width: 900px)`); Sidebar là điều hướng chính duy nhất, tách rõ Mở vs Tạo dự án (`➕ Tạo dự án mới`) và chỉ hiện thẻ tóm tắt AI đọc kèm nút mở Bước 2; `render_pipeline_header` chỉ hiển thị tóm tắt trạng thái, `render_step_next_action` dùng `type="secondary"`. |
| **U2** | Bước 1 — Tư liệu Nguồn | Chọn tệp và nạp dễ hiểu nhầm là đã lưu; upload hỗn hợp khó đọc trạng thái từng file sau rerun; bảng tài liệu dài 7 cột nặng chi tiết kỹ thuật. | Tách rõ bước chọn tệp (`chưa lưu vào dự án`) với bước lưu; báo cáo từng tệp (`_p01_upload_report_*`) giữ nguyên qua `st.rerun()` (tệp hợp lệ vẫn lưu nếu có tệp lỗi); bảng mặc định tinh gọn 4 cột (`Tên tệp`, `Trạng thái đọc`, `Nguồn tư liệu`, `Phạm vi`), đẩy metrics/cảnh báo/preview `3,000` ký tự vào expander chi tiết. |
| **U3** | Bước 2 — Thiết lập & Phương pháp | Đổi radio chế độ chưa phân biệt rõ giữa xem thử vs áp dụng thật; dễ sót hiểu `free_triples` không dùng danh mục/từ điển; Prompt/Diff/EDC+R phơi hết ra mặt chính; ML Lab ở Vùng 4 gây lồng expander. | Thêm `ENGINE_SPECS` mô tả mục đích/đầu ra/yêu cầu/giới hạn khi chọn radio mà chưa ghi đè `extraction_mode` (chỉ áp dụng khi bấm `btn_apply_proj_mode`); cảnh báo nổi bật ở Vùng 3 khi bật `Baseline B`; gom Prompt Editor, Preview, Diff & EDC+R vào expander Nghiên cứu; truyền `use_expander=False` cho `render_ml_lab_panel` ở Vùng 4. |
| **U4** | Bước 3 — Trích xuất & Step Traces | Lặp lại slider/lưu token TOML ở đầu Bước 3; tham số `chunk_size`/`overlap`/`workers` dàn trải trên nút chạy; chưa cảnh báo Dry-run vẫn tốn token/gọi AI; Step Traces lồng JSON thô rối mắt. | Thay bằng thẻ tóm tắt Kết nối AI & Phương pháp chỉ đọc (`p03_btn_goto_setup`); gom thông số phân đoạn/đa luồng vào expander `⚙️ Tùy chỉnh kỹ thuật`; thêm caption minh bạch ngay trên nút `btn_dry_run_one_chunk` & `btn_run_full_extraction`; tách thẻ tóm tắt lượt chạy ra ngoài và gom `Step Traces` (`use_expander=False`), `Prepared Request` & JSON gốc vào 1 expander kỹ thuật duy nhất. |
| **U5** | Bước 4 — Kiểm duyệt & Gộp thực thể | Người dùng dễ quên bộ lọc đang bật trên bảng EDC/Quan hệ; xem cạnh phải bấm đổi sang tab riêng mới có nút Duyệt/Từ chối và thiếu nút Trước/Sau để duyệt liên tục; xem trước gộp thực thể thiếu dòng đối chiếu Đích vs Node bị gộp & Từ điển. | Bổ sung banner tóm tắt bộ lọc & phạm vi chọn trên EDC & Edge table; lưu `ordered_edge_ids` trong state để thêm nút `◀️ Mục trước` / `Mục tiếp ▶️` theo `edge_id`; đưa khối ra quyết định (`⚖️ Ra quyết định kiểm duyệt cho cạnh này`) trực diện ngay dưới khung đối chiếu bằng chứng hai cột; thêm khung tóm tắt tác động Đích vs Bị gộp & bí danh `domain_gazetteer` ở Bước 3 Gộp thực thể. |
| **U6** | Bước 5 — Khai thác & Xuất đồ thị | Chưa có banner phân biệt thật nổi trạng thái Đã duyệt vs Baseline B vs File ngoài; tham số PCST/PPR/Alpha dàn hết trên khung Hỏi đáp; Graphviz thiếu ghi chú rõ giới hạn hiển thị không cắt file xuất và thiếu bảng quan hệ hỗ trợ bàn phím đi kèm. | Bổ sung banner màu theo nguồn đồ thị; tách phần hỏi đáp cơ bản khỏi expander `🔬 Tham số thuật toán & Chế độ đối sánh` và đặt nhãn 4 tab rõ Khám phá vs Nghiên cứu; nâng độ tương phản DOT trong `build_graph_dot` (`#EFF6FF`, `#1D4ED8`); thêm expander `Bảng quan hệ & Bằng chứng đầy đủ` hỗ trợ bàn phím; đổi `use_container_width=True` thành `width="stretch"` tại `graph_source.py`. |
| **U7** | Kiểm thử, Docs & Nghiệm thu | Chưa có bộ test AppTest riêng bao phủ các nâng cấp UI/UX U1–U6 và tài liệu hiện trạng UI cũ chưa cập nhật. | Bổ sung [tests/test_ui_ux_improvements.py](../../tests/test_ui_ux_improvements.py) (7 tests / AppTest 5 màn hình), cập nhật [current_ui_layout_spec.md](../layout/current_ui_layout_spec.md), [structure.md](../structure.md), chạy toàn bộ suite & `graphify update .`. |

---

## 2. Danh sách Tệp Đã Tạo / Sửa Đổi trong Đợt U0–U7

### 2.1. Tài liệu Thiết kế & Bản đồ
- [AI/layout/ui-ux-state-inventory.md](../layout/ui-ux-state-inventory.md) *(mới)* — Kiểm kê state, ma trận 5 bước, feature preservation & danh sách `session_state` keys.
- [AI/layout/ui-ux-wireframes.md](../layout/ui-ux-wireframes.md) *(mới)* — Bảng thuật ngữ thống nhất & wireframe cho Shell + Bước 1–5.
- [AI/layout/current_ui_layout_spec.md](../layout/current_ui_layout_spec.md) *(cập nhật)* — Đồng bộ đặc tả layout hiện hành sau U1–U6.
- [AI/structure.md](../structure.md) *(cập nhật Mục 2.5 Frontend)* — Đồng bộ mô tả trách nhiệm các trang & components UI mới.
- [AI/report/ui-ux-acceptance-report.md](ui-ux-acceptance-report.md) *(mới — tệp này)*.

### 2.2. Cấu hình & Giao diện Streamlit (`frontend/` & `.streamlit/`)
- [.streamlit/config.toml](../../.streamlit/config.toml)
- [frontend/app.py](../../frontend/app.py)
- [frontend/components/pipeline_banner.py](../../frontend/components/pipeline_banner.py)
- [frontend/pages/p01_projects_docs.py](../../frontend/pages/p01_projects_docs.py)
- [frontend/pages/p02_catalogs_prompts.py](../../frontend/pages/p02_catalogs_prompts.py)
- [frontend/components/prompt_editor.py](../../frontend/components/prompt_editor.py)
- [frontend/components/ml_lab_panel.py](../../frontend/components/ml_lab_panel.py)
- [frontend/pages/p03_extraction.py](../../frontend/pages/p03_extraction.py)
- [frontend/components/step_traces_viewer.py](../../frontend/components/step_traces_viewer.py)
- [frontend/components/shared_curation_ui.py](../../frontend/components/shared_curation_ui.py)
- [frontend/components/edc_review_table.py](../../frontend/components/edc_review_table.py)
- [frontend/components/curation_table.py](../../frontend/components/curation_table.py)
- [frontend/components/evidence_panel.py](../../frontend/components/evidence_panel.py)
- [frontend/components/merge/entity_tab.py](../../frontend/components/merge/entity_tab.py)
- [frontend/components/graph_source.py](../../frontend/components/graph_source.py)
- [frontend/components/graph_view.py](../../frontend/components/graph_view.py)
- [frontend/components/export_tabs/g_retriever_tab.py](../../frontend/components/export_tabs/g_retriever_tab.py)
- [frontend/pages/p05_graph_export.py](../../frontend/pages/p05_graph_export.py)

### 2.3. Kiểm thử (`tests/`)
- [tests/test_ui_ux_improvements.py](../../tests/test_ui_ux_improvements.py) *(mới)* — Bộ kiểm thử AppTest & hồi quy cho U1–U6 + smoke test toàn bộ 5 bước.

---

## 3. Ràng buộc Bảo toàn Kiến trúc & Hợp đồng Tương thích

- **Không sửa Backend / Schema / Algorithms:** Không thay đổi cấu trúc lưu trữ `project.json`, `domain_gazetteer`, SQLite projection, engines (`fixed`, `edc`, `edc_plus_r`, `free_triples`), `GraphSnapshotDTO`, hay logic commit qua `ProjectCommitCoordinator`.
- **Tuân thủ `AGENTS.md` Modular Monolith:** Toàn bộ giao tiếp UI vẫn đi qua `get_facade()`, `get_ui_composition()` và `get_client()`, không import hạ tầng hoặc ghi đĩa trực tiếp từ component UI.
- **Bảo toàn Keys & Callbacks cho Testing & Tương thích ngược:**
  - Giữ các callbacks `on_sb_llm_key_change` / `on_p02_llm_key_change` trong `frontend/state/session.py` (`test_secrets_manager.py` pass).
  - Giữ các widget keys cốt lõi: `btn_next_action_*`, `btn_build_preview_*`, `btn_dry_run_one_chunk`, `p03_btn_baseline_graph`, `p03_download_free_triples_results`, `p05_graph_source_*`, `p05_baseline_runs_*`, `btn_all_*`, `btn_clear_*`, `p05_graph_json`, `btn_prep_zip`, `_gret_method_*`, `_gret_btn_run_bench_*`.
- **Không dùng Nested Expander:** Đảm bảo an toàn bằng tham số `use_expander=False` ở `render_ml_lab_panel` (Bước 2 Vùng 4) và `render_step_traces` (Bước 3 Nhật ký).

---

## 4. Kết quả Kiểm chứng Thực tế (Command Outputs)

Tất cả các lệnh bên dưới được chạy bằng môi trường Python thực tế của dự án (`.venv-win`) và `graphify` CLI sau lần chỉnh sửa code cuối cùng:

| Hạng mục kiểm chứng | Lệnh thực thi | Kết quả quan sát |
| :--- | :--- | :--- |
| **Suite UI/UX mới (U1–U7 + E2E 5 bước)** | `.\.venv-win\Scripts\python.exe -m unittest tests.test_ui_ux_improvements` | `Ran 7 tests in 3.849s` — **OK** |
| **Toàn bộ Offline Test Suite & Architecture Guard** | `.\.venv-win\Scripts\python.exe -m unittest discover -s tests` | `Ran 235 tests in 27.827s` — **OK** (0 failures, 0 errors, 0 skipped; bao gồm `test_architecture_boundaries.py`, `test_baseline_graph_ui.py`, `test_free_triples_ui.py`, `test_layout_pipeline.py`, `test_curation_hub.py`, `test_secrets_manager.py`, `test_provenance_view.py`, `test_ui_ux_improvements.py`). |
| **Cập nhật Knowledge Graph mã nguồn** | `graphify update .` | Thoát mã `0`: `Rebuilt: 2674 nodes, 8103 edges, 111 communities` trong `graphify-out/`. |

---

## 5. Giới hạn Hiện tại & Khuyến nghị Bước Tiếp theo

1. **Chưa xác minh usability với người dùng thực:** Cần thực hiện 1 phiên quan sát/đo thời gian thao tác với người dùng nghiên cứu di sản thực tế (đặc biệt trên tác vụ Bước 1 upload lỗi hỗn hợp, Bước 4 điều hướng `Mục trước / Mục tiếp` & gộp thực thể, và Bước 5 hỏi đáp PCST) để đo mức giảm thời gian và tỷ lệ lỗi thao tác.
2. **Streamlit HTML Widget Limit:** Bảng `st.data_editor` và Sơ đồ `st.graphviz_chart` phụ thuộc vào renderer mặc định của Streamlit `1.66.1`; nếu sau này nâng cấp trải nghiệm tìm kiếm sâu trên đồ thị lớn (>200 cạnh), có thể cân nhắc bổ sung thành phần lọc theo node/quan hệ ngay trên Tab 2 của Bước 5 trước khi dựng DOT/bảng.
3. **Thao tác Live LLM / Neo4j:** Chưa chạy kiểm thử live API LLM / Neo4j thật trong đợt này (chỉ kiểm thử offline bằng fake adapters/AppTest theo đúng quy tắc kiểm thử trong `AGENTS.md`).
