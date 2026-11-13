# Đặc tả Hiện trạng Layout & Giao diện Người dùng (KG Studio Pro)

> **Mục đích tài liệu:** Cung cấp bản đặc tả chính xác về **bố cục tổng thể, tỷ lệ cột (`st.columns`), độ rộng/chiều cao widget, quy ước CSS/HTML và các trạng thái động** của giao diện Streamlit hiện tại trong KG Studio, giúp AI Agent đọc nhanh và nắm rõ thực trạng UI trước khi sửa đổi hoặc mở rộng.  
> **Phạm vi đối chiếu mã nguồn:** Toàn bộ `app.py`, `.streamlit/config.toml`, `frontend/app.py`, `frontend/pages/*`, `frontend/components/*`, và `frontend/state/session.py` (cập nhật sau đợt triển khai U0–U7).

---

## 1. Khung Toàn cục, Cấu hình Trang & Quy ước Độ rộng

### 1.1. Cấu hình Viewport & CSS Toàn cục
- **Entrypoint:** [app.py](../../app.py) gọi `frontend.app.main()`.
- **Page Config ([frontend/app.py](../../frontend/app.py#L36-L70)):**
  - `st.set_page_config(page_title=..., page_icon=..., layout="wide")` — sử dụng toàn bộ chiều rộng trình duyệt (**Wide Mode**).
  - **Ẩn điều hướng đa trang gốc của Streamlit:** Kết hợp `showSidebarNavigation = false` trong [.streamlit/config.toml](../../.streamlit/config.toml) và `[data-testid='stSidebarNav'] { display: none !important; }` trong `_inject_scoped_styles()`.
- **Theme & Scoped CSS:**
  - [.streamlit/config.toml](../../.streamlit/config.toml) khai báo `[theme]` sáng rõ ràng (`base = "light"`, `primaryColor = "#1D4ED8"`, `backgroundColor = "#FFFFFF"`, `secondaryBackgroundColor = "#F8FAFC"`, `textColor = "#0F172A"`, `font = "sans serif"`).
  - `_inject_scoped_styles()` thiết lập cỡ chữ `1rem` (`line-height: 1.58`), `max-width: 1400px` cho `[data-testid='stMainBlockContainer']`, viền `:focus-visible` (`2px solid #1D4ED8`), và `@media (max-width: 900px)` wrap an toàn cho `[data-testid='stHorizontalBlock']`.

### 1.2. Khung Bố cục 2 Vùng (Shell Architecture)

```text
+-----------------------+---------------------------------------------------------------------+
| SIDEBAR (Điều hướng   | MAIN CANVAS (layout="wide", max-width 1400px)                        |
| & Ngữ cảnh dự án)     |                                                                     |
|                       | +-----------------------------------------------------------------+ |
| [Title & Caption]     | | TOP PIPELINE SUMMARY CARD (container(border=True))              | |
| 1. 📂 Mở dự án        | | Dự án · Phương pháp · Tiến độ bước (1..5/5) + 5 chip trạng thái | |
| 2. ➕ Tạo dự án mới   | +-----------------------------------------------------------------+ |
|   (expander)          | ────────────────────────── st.divider() ─────────────────────────── |
| ───────────────────── |                                                                     |
| 3. Quy trình 5 Bước   | +-----------------------------------------------------------------+ |
|   st.radio dọc +      | | STEP NEXT ACTION BANNER (container(border=True))                | |
|   badge [✓/●/○/!]     | | st.columns([3.5, 1.5]) -> Mô tả trái | CTA phụ (secondary) phải | |
| ───────────────────── | +-----------------------------------------------------------------+ |
| 4. 🤖 Kết nối AI      |                                                                     |
|   (Thẻ chỉ đọc + nút  | [NỘI DUNG TRANG ĐANG CHỌN: p01 .. p05]                              |
|    mở Bước 2)         |                                                                     |
+-----------------------+---------------------------------------------------------------------+
```

### 1.3. Quy ước Độ rộng & Chiều cao Widget xuyên suốt
| Thuộc tính | Cách dùng thực tế trong codebase | Ghi chú cho AI Agent |
| :--- | :--- | :--- |
| **Độ rộng giãn hết khung** | `width="stretch"` (hoặc `width='stretch'`) đồng nhất trên toàn bộ button, dataframe, data_editor | Đã bỏ `use_container_width=True` tại `graph_source.py`. |
| **Chiều rộng Sidebar** | Mặc định của Streamlit (không override CSS) | Trên màn hình nhỏ/mobile Streamlit tự thu gọn thành drawer. |
| **Tỷ lệ cột chia trọng số** | `st.columns([...])` nhận vector số thực | Ví dụ `[3.5, 1.5]` tương ứng **70% / 30%** vùng chứa cha; `st.columns(n)` chia **100%/n** đều nhau. |
| **Container có viền** | `st.container(border=True)` | Dùng để nhóm từng card hành động, card thống kê hoặc khu vực chức năng độc lập. |
| **Chiều cao cố định / động** | Chỉ đặt `height=` ở hộp văn bản xem trước, danh sách tài liệu Bước 3, và box HTML chứng cứ | Cụ thể: `p01` text_area (`220px`), `p02` prompt (`160px`, history `140px`), `p03` list tài liệu (`280px` khi >4 file hoặc `"content"`), `evidence_panel` text_area (`90px`), `entity_tab` desc (`80px`), `provenance_view` HTML box (`max-height: 360px`). |

---

## 2. Thành phần Cố định: Sidebar & Pipeline Header

### 2.1. Sidebar ([frontend/app.py](../../frontend/app.py))
Sắp xếp theo thứ tự dọc cố định:
1. **Header:** `st.title` + `st.caption` từ `CONFIG["app"]`.
2. **Quản lý dự án (tách rõ mở & tạo):** `st.selectbox("📂 Mở dự án có sẵn")` + `st.expander("➕ Tạo dự án mới", expanded=False)` kiểm tra tên rỗng/trùng trước khi tạo.
3. **Điều hướng 5 bước (`st.divider()`):** `st.radio` dọc là **thanh điều hướng chính duy nhất**, hiển thị kèm badge chữ rõ ràng (`✓ Xong`, `● Chờ`, `! Lưu ý`, `○ Trống`). Đổi lựa chọn kích hoạt `st.rerun()`.
4. **Thẻ Kết nối AI chỉ đọc:** Tóm tắt `provider`, `model`, `in_tokens`, `out_tokens`, trạng thái API key và nút `⚙️ Chỉnh kết nối ở Bước 2` (không còn form/slider chỉnh LLM trùng lặp ở Sidebar).

### 2.2. Top Pipeline Summary & Next Action Callout ([pipeline_banner.py](../../frontend/components/pipeline_banner.py))
- **`render_pipeline_header`:**
  - Hiển thị thẻ tóm tắt `container(border=True)` với `Dự án`, `Phương pháp`, bước hiện tại `(idx+1/5)` và 5 chip trạng thái bằng icon + chữ (không render 5 nút điều hướng cạnh tranh với Sidebar).
- **`render_step_next_action`:**
  - `st.container(border=True)` chia `st.columns([3.5, 1.5])`; nút gợi ý đầu trang sử dụng `type="secondary"` (nhường `type="primary"` cho nút tác vụ chính và footer của từng màn hình).

---

## 3. Trang 1: Nguồn Tư liệu & Quản lý Văn bản (`p01_projects_docs.py`)

**Tệp nguồn:** [p01_projects_docs.py](../../frontend/pages/p01_projects_docs.py) (`render_projects_docs_page`).

### 3.1. Cấu trúc Bố cục & Tỷ lệ
1. `st.subheader` + `st.caption`.
2. **Next Action Banner:** `st.columns([3.5, 1.5])`.
3. **Thẻ Tiếp tục Công việc (Conditional Banner).**
4. **Khu vực Tải lên (`📥 Thêm Tài liệu Mới`):**
   - `st.file_uploader` (`.txt`, `.docx`, `.pdf`, `accept_multiple_files=True`), full width.
   - Caption rõ ràng khi đã chọn tệp trên trình duyệt (`chưa lưu vào dự án`) + nút primary `📥 Bước B — Đọc & thêm các tệp đã chọn vào dự án`.
   - Thẻ báo cáo từng tệp (`_p01_upload_report_*`) giữ kết quả qua `st.rerun()`, tệp hợp lệ vẫn lưu kể cả khi có tệp lỗi.
5. **Danh sách Tài liệu & Kiểm tra văn bản (`📚 Tài liệu trong Dự án`):**
   - Bảng mặc định tinh gọn 4 cột (`Tên tệp`, `Trạng thái đọc`, `Nguồn tư liệu`, `Phạm vi`).
   - `st.expander("🔍 Chi tiết tài liệu & Xem trước văn bản đã bóc tách")`: chứa 3 metrics kỹ thuật, danh sách cảnh báo từng tệp, và `st.text_area(..., height=220, disabled=True)` kèm cảnh báo tường minh giới hạn 3,000 ký tự xem trước.
6. **Footer điều hướng:** `st.columns([1, 2])` (**33.3% cột trái để trống / 66.7% cột phải** nút `➡️ Chuyển sang Bước 2`).

### 3.2. Ma trận Trạng thái Trang 1
| Trạng thái | Điều kiện kích hoạt | Thay đổi hiển thị trên giao diện |
| :--- | :--- | :--- |
| **Dự án mới / Rỗng** | `len(docs) == 0` | Next Action bị disable; **không** hiện Thẻ Tiếp tục; hiển thị `st.info("Dự án chưa có tài liệu nào...")` và **ẩn** bảng tài liệu, trình xem trước lẫn Footer Bước 2 (`return` sớm ở dòng 80). |
| **Có file chờ nạp** | `bool(uploaded)` | Nút primary `📥 Nạp các tệp đã chọn vào dự án` xuất hiện ngay dưới expander metadata. |
| **Có đoạn lỗi tồn đọng** | `docs` khác rỗng và `project["chunk_errors"]` khác rỗng | Hiện card cảnh báo vàng `st.warning` + nút nhảy sang Bước 3 (`[3.5, 1.5]`). |
| **Có dữ kiện chờ duyệt** | `not errors` và `pending + check > 0` | Hiện card xanh `st.info` + nút nhảy sang Bước 4 (`[3.5, 1.5]`). |

---

## 4. Trang 2: Thiết lập Phương pháp, Danh mục & Từ điển (`p02_catalogs_prompts.py`)

**Tệp nguồn:** [p02_catalogs_prompts.py](../../frontend/pages/p02_catalogs_prompts.py), [prompt_editor.py](../../frontend/components/prompt_editor.py), [gazetteer_panel.py](../../frontend/components/gazetteer_panel.py), [ml_lab_panel.py](../../frontend/components/ml_lab_panel.py).

### 4.1. Cấu trúc Bố cục theo 4 Vùng Dọc

```text
[Header + Next Action Banner (3.5 : 1.5)]
├── VÙNG 1: Expander "🤖 1. Kết nối Mô hình Ngôn ngữ" (SSOT Cấu hình — default.toml / .secrets.toml / session)
│     ├── Hàng 1: [1.5 : 2.5]  -> Provider (37.5%) | Model ID (62.5%)
│     ├── Hàng 2: [2.0 : 2.0]  -> Base URL (50%)   | API Key password (50%)
│     ├── Hàng 3: [1.0 : 1.0]  -> Slider Input Tokens (50%) | Slider Output Tokens (50%)
│     └── Hàng 4: [1.2 : 1.2 : 1.4 : 1.4] -> Test (23%) | Auto (23%) | Lưu TOML (27%) | Lưu/Xóa Key (27%)
│
├── VÙNG 2: render_prompt_management_panel()
│     ├── Bộ chọn mode: [3.5 : 1.5] -> Radio ngang 4 mode + Thẻ ENGINE_SPECS | Cảnh báo & Nút Áp dụng
│     └── Expander "⚙️ Tùy chỉnh Nâng cao & Nghiên cứu (Prompt, Preview, Version, EDC+R)" (expanded=False)
│           ├── Khung soạn Prompt, Expander/Container Preview Request & Diff Lịch sử Phiên bản
│           └── Box Cấu hình EDC+R [chỉ hiện khi selected_mode == "edc_plus_r"]
│
├── VÙNG 3: 📚 Danh mục Lược đồ & Từ điển Tri thức (cảnh báo khi mode == MODE_FREE_TRIPLES)
│     ├── Tab 1: Loại thực thể  -> Upload JSON -> [1:1] (khi có file) -> st.data_editor -> Download
│     ├── Tab 2: Loại quan hệ    -> Upload JSON -> [1:1] (khi có file) -> st.data_editor -> Download
│     ├── Tab 3: Từ điển Bí danh & Địa danh (render_gazetteer_setup_tab)
│     │     ├── [2.2 : 1.2] (65% : 35%) -> File Uploader (JSON/CSV) | Spacer 1.75rem + Nạp Mẫu Hà Nội
│     │     ├── [1 : 1] -> Nút Nạp đè / Gộp thêm [chỉ hiện khi up_gaz != None]
│     │     ├── st.data_editor (full width, dynamic rows: alias, canonical_name, kind, source)
│     │     ├── [2 : 1] (67% : 33%) -> Lưu Từ điển Bí danh (primary) | Xóa sạch từ điển (khi có mục)
│     │     └── [1 : 1] (50% : 50%) -> Tải JSON | Tải CSV (chỉ hiện khi có entries)
│     └── Thanh Lưu Schema Chung: [2 : 1] (67% : 33%) -> Lưu Toàn bộ Danh mục | Xóa sạch (khi có mục)
│
├── VÙNG 4: Expander "🧪 Phòng Thí nghiệm Active Learning & ML Lab" (expanded=False)
│     └── render_ml_lab_panel(..., use_expander=False): st.columns(3) [3 nút Export/Train] + st.columns(2) [Bench/LoRA]
│
└── Footer: [1 : 2] (33% trống | 67% nút ➡️ Chuyển sang Bước 3)
```

### 4.2. Ma trận Trạng thái Trang 2
- **Khác biệt chế độ đang xem vs chế độ đang áp dụng (`selected_mode != current_applied_mode`):** Cột phải `col_apply` (30%) hiện cảnh báo + nút `🎯 Áp dụng chế độ này cho Dự án`. Khi khớp nhau, cột `col_apply` để trống.
- **Chế độ `MODE_FREE_TRIPLES` (Baseline B):** Hiện thêm `st.info` giải thích baseline ngay dưới bộ chọn mode.
- **Chế độ `MODE_EDC_PLUS_R`:** Xuất hiện khối `container(border=True)` cấu hình Schema Retriever (`embedder`, `top_k`, ngưỡng alignment, số vòng lặp, checkbox LLM verifier). Các mode khác ẩn hoàn toàn khối này.
- **Trạng thái Draft Prompt (`has_unsaved_changes`):** Header phải đổi từ `st.success` xanh sang `st.warning` vàng; nút `💾 Lưu phiên bản mới` chuyển thành `type="primary"`, nút `🔄 Hủy sửa nháp` mở khóa (`disabled=False`).
- **Tab 3 Từ điển (Nơi quản lý duy nhất):** Là điểm nhập/chỉnh sửa duy nhất cho `domain_gazetteer`. Khi dự án mới chưa có dữ liệu (`entries == []`), `data_editor` vẫn dựng sẵn khung 1 dòng mẫu trống cấu trúc cột (`alias`, `canonical_name`, `kind`, `source`) và ẩn các nút Xóa sạch / Download.

---

## 5. Trang 3: Bảng điều khiển Trích xuất & Step Traces (`p03_extraction.py`)

**Tệp nguồn:** [p03_extraction.py](../../frontend/pages/p03_extraction.py), [step_traces_viewer.py](../../frontend/components/step_traces_viewer.py).

### 5.1. Cấu trúc Bố cục
1. `st.subheader` hiển thị `mode` hiện hành + **Next Action Banner** (`[3.5, 1.5]`) + (nếu `free_triples`) `st.info`.
2. **Thẻ tóm tắt Kết nối AI & Phương pháp (chỉ đọc):** Hiển thị `mode`, `provider`, `model`, `in_tokens`, `out_tokens`, trạng thái key + nút `⚙️ Đổi cấu hình ở Bước 2` (`p03_btn_goto_setup`). Đã bỏ slider/nút lưu token trùng lặp.
3. **Khối Chọn Tài liệu (`container(border=True)`):** Toolbar lọc & chọn nhanh + bảng danh sách có thanh cuộn (`280px` khi `> 4` file).
4. **Khối Phạm vi & Điều khiển Trích xuất:**
   - Thông số `chunk_size`, `overlap`, `extract_all`/`max_chunks`, slider `workers` (`1..16`) nằm gọn trong expander `⚙️ Tùy chỉnh kỹ thuật (Phân đoạn & Đa luồng)`.
   - Khung tóm tắt phạm vi (`số file · tổng đoạn · phương pháp · số luồng`).
   - Hàng nút `btn_dry_run_one_chunk` & `btn_run_full_extraction` kèm caption minh bạch: Dry-run **vẫn gọi AI thực tế**, tốn token và ghi nhật ký.
5. **Nhật ký Trích xuất:** Thẻ tóm tắt trực quan (Trạng thái, Tài liệu, Đoạn, Token, Kết quả) ở ngoài; toàn bộ Provenance, Step Traces (`use_expander=False`), JSON/Metadata đối chứng và phản hồi gốc nằm gọn trong expander `🔧 Chi tiết kỹ thuật & Nhật ký Engine`.
6. **Footer (`container(border=True)`, `st.columns([3.5, 1.5])` — 70% | 30%).**

### 5.2. Ma trận Trạng thái Trang 3
| Trạng thái | Điều kiện | Ảnh hưởng Layout |
| :--- | :--- | :--- |
| **Chưa có tài liệu** | `not docs` | Dừng tại dòng 111 sau Token Expander; ẩn toàn bộ khối Chọn tài liệu, Tham số, Nhật ký và Footer. |
| **Tài liệu <= 4 vs > 4** | `len(displayed_docs)` | Khung danh sách tự co gọn `"content"` (<=4) hoặc khóa khung cuộn `280px` (>4). |
| **Mức luồng (`workers`)** | `1` / `2..5` / `6..10` / `11..16` | Cột phải `[2.2, 3.8]` đổi màu box tương ứng: `st.info` (1), `st.success` (2–5), `st.warning` (6–10), `st.error` (11–16). |
| **Đang chạy Extraction** | Khi nhấn Chạy toàn bộ | Xuất hiện `st.progress(0.0..1.0)` + `st.empty()` caption cập nhật live phía dưới nút. |
| **Có lỗi chunk phiên trước** | `p03_last_failed_tasks` khác rỗng | Hiện `st.warning` + nút full-width `🔄 Chạy lại các đoạn gặp lỗi` ngay dưới hàng nút chạy. |
| **Chế độ Baseline B (`free_triples`)** | `mode` hoặc `run["extraction_mode"] == MODE_FREE_TRIPLES` | Hiện banner info đầu trang; trong Nhật ký hiện thêm 2 khối `st.json` (`Bộ ba thô`, `Chẩn đoán`), expander `Metadata đối chứng baseline`, nút download JSON toàn bộ baseline; cột nút Footer xếp dọc 2 nút (`Bước 5` & `Về Bước 2`). |

---

## 6. Trang 4: Hub Rà soát & Chuẩn hóa Tri thức (`p04_curation_hub.py`)

**Tệp nguồn:** [p04_curation_hub.py](../../frontend/pages/p04_curation_hub.py), [edc_review_table.py](../../frontend/components/edc_review_table.py), [edc_bulk_actions.py](../../frontend/components/edc_bulk_actions.py), [curation_table.py](../../frontend/components/curation_table.py), [evidence_panel.py](../../frontend/components/evidence_panel.py), [entity_merge_panel.py](../../frontend/components/entity_merge_panel.py), [shared_curation_ui.py](../../frontend/components/shared_curation_ui.py), và `frontend/components/merge/*`.

### 6.1. Khung Đầu trang & Điều hướng Phân khu (Persistent Top Chrome của Trang 4)
1. `st.subheader` + **Next Action Banner** (`[3.5, 1.5]`).
2. **Conditional Banners:**
   - `render_sqlite_resync_banner`: chỉ hiện khi `project["sync_pending"] == True`.
   - `_curation_return_context`: chỉ hiện khi vừa nhảy từ Phân khu 2 sang Phân khu 1 xử lý đề xuất chặn; chia `st.columns([3.5, 1.2])` (**74.5% mô tả | 25.5% nút quay lại**).
3. **Dashboard KPI (6 thẻ ngang):** `st.columns(6)` (**16.7% × 6**): `Lược đồ chờ duyệt` | `Quan hệ chờ duyệt` | `Cần kiểm tra` | `Vướng danh mục` | `Cặp nghi trùng` | `Đồ thị (Node / Edge)`.
4. **Thanh Phím tắt Hành động (3 cột):** `st.columns(3)` (**33.3% × 3**) điều hướng nhanh sang Phân khu 1 / 2 / 3 (tự bật `type="primary"` theo mục ưu tiên cần xử lý).
5. **Điều hướng Phân khu Chính:** `st.radio(..., horizontal=True)` chọn giữa **3 Phân khu** (không dùng `st.tabs` để giữ state điều hướng chuyển ngữ cảnh qua `st.session_state["curation_hub_active_tab"]`):
   - `schema`: `📐 1. Chuẩn hóa Lược đồ (Schema EDC)`
   - `edges`: `🔬 2. Duyệt Quan hệ & Bằng chứng`
   - `entities`: `🏛️ 3. Quản lý & Gộp thực thể`

---

### 6.2. Phân khu 1 (`selected_tab == "schema"`): Chuẩn hóa Lược đồ (EDC)
Gồm 2 `st.container(border=True)` xếp dọc nối tiếp nhau qua `st.divider()`: **Khu A (`entity_types`)** và **Khu B (`relations`)**. Mỗi khu có cấu trúc y hệt:

1. **Bảng lọc & chọn ([edc_review_table.py](../../frontend/components/edc_review_table.py)):**
   - Thanh lọc cơ bản: `st.columns([3.5, 1.5])` (**70% Tìm kiếm | 30% Trạng thái**).
   - Expander Bộ lọc nâng cao (`expanded=True` nếu có bộ lọc active, ngược lại `False`): Hàng 1 `st.columns(3)` (Tài liệu | Ứng viên | Định nghĩa), Hàng 2 `st.columns([1.2, 1.5, 1.0, 0.8])` (Nguồn QĐ | Sắp xếp | Tải lại | Reset).
   - `render_selection_action_bar` ([shared_curation_ui.py](../../frontend/components/shared_curation_ui.py#L105)):
     - Chế độ 5 cột `st.columns([1.2, 1.4, 1.0, 1.1, 1.3])` (**20% | 23% | 17% | 18% | 22%**): Chọn trang này | Chọn tất cả lọc | Bỏ chọn | Số dòng/trang (`10, 25, 50, 100`) | Trang.
   - `st.data_editor(width="stretch", hide_index=True)` (chỉ cho phép tick cột `Chọn`).
   - **Ngăn kéo Chi tiết 1 Đề xuất (`render_proposal_detail_drawer`):** Hiện `st.expander(..., expanded=True)` nếu đang chọn/focus 1 đề xuất:
     - 4 cột thông số `st.columns(4)` (**25% × 4**) + Định nghĩa/Mô tả + Bảng Quan sát (`dataframe`) + Expander Đọc Chunk gốc (tối đa 4 quan sát đầu qua `highlight_text_html`) + Bảng Top-K Ứng viên đích + Form `st.radio` Xử lý đơn (`merge` / `approve` / `reject`).
2. **Thanh Thao tác Hàng loạt ([edc_bulk_actions.py](../../frontend/components/edc_bulk_actions.py)):**
   - (Có ĐK) Card báo cáo kết quả lô gần nhất: `st.columns(4)`.
   - Hàng làm mới gợi ý AI (`st.columns(3)`): `🔄 Làm mới mục đã chọn` | `🔄 Làm mới mục đang lọc` | `🤖 Tự điền gợi ý`.
   - (Khi `selected_count > 0`) Card Thao tác Nhanh (`st.columns(3)`): `[✅ Hợp nhất vào Top-1]` | `[🆕 Duyệt tất cả thành mới]` | `[❌ Từ chối tất cả]`.
   - Expander Chuẩn bị Bản nháp (`expanded=selected_count > 0`): Tham số áp dụng `st.columns([2.0, 1.2, 1.8])` + 4 nút chuẩn bị `st.columns(4)`.
   - **Trạng thái Xem trước Lô (Preview Active):** Hiện `st.columns(4)` tóm tắt số lượng + `st.data_editor` danh sách chốt + 3 nút hành động `st.columns([1.6, 2.0, 1.0])` (**35% Hủy / Làm lại | 43% Áp dụng chính thức | 22% Hủy xem trước**).
3. **Khu vực C (Chung cho Phân khu 1):** Expander `🤖 Auto Target Alignment` với `st.columns(2)` (Loại thực thể 50% | Quan hệ 50%) + `render_decision_batch_history` (nếu mở xem batch có thêm bảng kết quả + nút nhảy `[2.0, 1.0]`).

---

### 6.3. Phân khu 2 (`selected_tab == "edges"`): Kiểm duyệt Quan hệ & Bằng chứng
Xếp dọc 2 phần chính ngăn bởi `st.divider()`, tối ưu cho quy trình *"Trên bảng — Dưới đối chiếu"*:

1. **Phần trên — Bảng Quan hệ & Thao tác lô ([curation_table.py](../../frontend/components/curation_table.py#L521-L934)):**
   - Bộ lọc cơ bản: `st.columns([3.5, 1.5])` (**70% Từ khóa | 30% Trạng thái**).
   - Expander Bộ lọc nâng cao: Hàng 1 `st.columns(4)` (Tài liệu | Quan hệ | Thực thể | Loại đầu mút), Hàng 2 `st.columns([2, 2, 1])` (Tình trạng bằng chứng 40% | Tình trạng danh mục 40% | Reset 20%).
   - `render_selection_action_bar` (`[1.2, 1.5, 1.0, 1.2, 2.2]`) -> `st.data_editor(width="stretch")` -> Thanh chọn dòng focus `st.columns([3.0, 1.2])` (**71.4% Selectbox | 28.6% Caption ID**).
   - **Khi `len(sel_ids) > 0`:** Hiện Card Thao tác Nhanh (`st.columns(3)`: Duyệt / Đánh dấu kiểm tra / Từ chối) + Expander Xem trước nâng cao (`[1.3, 1.5, 1.8, 1.2]` chế độ/lý do/nút -> `st.columns(4)` metrics -> `st.dataframe` -> `st.columns(2)` áp dụng/hủy).
2. **Phần dưới — Khung Đối chiếu Hai Cột & Sửa dữ kiện ([evidence_panel.py](../../frontend/components/evidence_panel.py#L55-L350)):**
   - **Tỷ lệ 2 cột đối xứng gần bằng nhau:** `col_left, col_right = st.columns([1.05, 1.15])` (**47.7% Trái | 52.3% Phải**):
     - **Cột trái (`container(border=True)`):** Hiển thị `Source -> Relation -> Target`, trạng thái kiểm duyệt, badge danh mục, tên mở EDC gốc, Model/Run. **Khi bị chặn bởi danh mục (`status_code != "valid"`):** tự sinh cảnh báo + nút `🔗 Mở đề xuất ... ở Trang 4` (nhảy qua Phân khu 1 kèm lưu `_curation_return_context`).
     - **Cột phải (`container(border=True)`):** Metadata tài liệu/đoạn/trang/offset `[start:end]` + Box HTML Highlight (`format_highlighted_evidence_html`). **Khi câu trích dẫn khớp >= 2 vị trí (`len(candidates) > 1`):** hiện `st.info` + thanh khóa vị trí `st.columns([2.5, 1.1])` (**69.4% Selectbox | 30.6% Nút Khóa vị trí**).
   - **Thanh điều hướng trước/sau:** Header đối chiếu có nút `◀️ Mục trước` / `Mục tiếp ▶️` theo `ordered_edge_ids` (ổn định theo `edge_id`).
   - **Khối quyết định trực diện (`container(border=True)`):** Đặt ngay dưới khung 2 cột (Duyệt / Cần kiểm tra / Từ chối + lý do/ngoại lệ + nút Lưu quyết định) trước 2 tab phụ `✏️ Sửa dữ kiện` và `📜 Lịch sử thay đổi của cạnh`.
   - **Trạng thái rỗng:** Nếu chưa có cạnh hoặc ID không khớp, hiển thị duy nhất `st.info("Hãy chọn một dòng quan hệ trong bảng...")`.
3. **Cuối Phân khu 2:** `render_decision_batch_history` (Lịch sử Lô Kiểm duyệt Quan hệ & Khôi phục Snapshot).

---

### 6.4. Phân khu 3 (`selected_tab == "entities"`): Hồ sơ Thực thể & Gộp Trùng lặp
**Hiện trạng mới nhất:** Chỉ còn **2 chế độ** chuyển qua `ent_subnav = st.radio(..., horizontal=True)` (đã **gỡ bỏ hoàn toàn** giao diện Quản lý Từ điển và nút điều hướng sang Bước 2):

1. **Chế độ A: `🏛️ Bảng Hồ sơ Thực thể & Trọng số` ([curation_table.py](../../frontend/components/curation_table.py#L935-L1197) + [evidence_panel.py](../../frontend/components/evidence_panel.py#L352-L490)):**
   - **Bảng danh sách:** Filter `[3.5, 1.5]` -> Expander `[1.5, 1.2, 1.3]` + `[3.5, 1.5]` -> Action Bar -> `st.data_editor` -> (Khi `selected_node_ids` khác rỗng) Thanh thao tác hàng loạt `st.columns([2.0, 1.4, 1.4])` (Đổi loại hàng loạt `[1.5, 1.0]` / Đưa vào bàn gộp / Xóa bỏ) -> Thanh focus 1 thực thể `st.columns([2.4, 1.2, 1.2])` (**50% Selectbox | 25% Xem quan hệ | 25% Đưa vào bàn gộp**).
   - **Inspector 2 cột dưới bảng (`render_entity_profile_inspector`):** `st.columns([1.05, 1.15])` (**47.7% Trái | 52.3% Phải**):
     - Trái (`container(border=True)`): Form sửa tên, loại, bí danh, mô tả (`text_area height=90`).
     - Phải (`container(border=True)`): `st.dataframe` các quan hệ đi ra/vào + `st.columns([2.0, 1.2])` nút mở cạnh tương ứng ở Phân khu 2.
2. **Chế độ B: `🔀 Công cụ Gộp Thực thể Trùng lặp (Entity Merge)` ([entity_merge_panel.py](../../frontend/components/entity_merge_panel.py)):**
   Tổ chức thành **`st.tabs(4)`**:
   - **Tab 1 — Gộp Thực thể ([entity_tab.py](../../frontend/components/merge/entity_tab.py)):**
     - **Banner Phản hồi Từ điển (Conditional Flash Messages):** Nếu `m_state["flash_messages"]` có nội dung (sau `st.rerun()` từ Gộp đơn lẻ hoặc Gộp hàng loạt), render `st.success` ngay đầu tab (ví dụ: `"📚 Đã thêm 1 bí danh vào Từ điển Dự án: 'Chùa Một Cột' → 'Diên Hựu Tự'"`) kèm `st.toast`.
     - **Khu 1 (Bulk Entity Merge):** Filter `[1.6, 2.4]` (40% / 60%) -> 3 nút chọn `[1.3, 1.8, 1.2, 2.0]` -> `st.data_editor` -> (Khi tick chọn cặp) Card Thao tác Nhanh `st.columns([1.5, 1.5])` -> Kiểm tra từng cặp `st.columns([2.4, 1.2, 1.3])` (50% / 25% / 25%).
     - **Khu 2 (Bàn Gộp 2..N thực thể):** Bước 1 (Chọn & bảng thuộc tính + Expander Provenance `[1.2, 1.0]` trong `provenance_view.py`) -> Bước 2 (`st.columns(3)` giữ ID/Tên/Loại + `text_area height=80`) -> Bước 3 (Nút xem trước -> `st.columns(4)` metrics -> Nút xác nhận gộp).
     - Expander Lịch sử Gộp & Bảng chuyển hướng ID.
   - **Tab 2 — Gộp Quan hệ ([relation_tab.py](../../frontend/components/merge/relation_tab.py)):**
     - Khu 1 AI Clustering (`[3, 3]`, `[2.5, 3.5]`, `[2.2, 3.8]`, cụm đề xuất `[3, 3]`) -> Khu 2 Fuzzy Matching (`[1.6, 2.4]`, `[1.5, 1.5, 3.0]`, `[1.5, 1.5]`) -> Khu 3 Bàn gộp thủ công (`[1.5, 1.5]`) -> Khu 4 Tiện ích khử trùng & Lịch sử.
   - **Tab 3 — Chuẩn hóa Loại Thực thể ([entity_type_tab.py](../../frontend/components/merge/entity_type_tab.py)):**
     - AI Clustering (`[3, 3]`, `[2.5, 3.5]`, `[2.2, 3.8]`) -> Bàn gộp thủ công `[1.5, 1.5]` -> Bảng lịch sử.
   - **Tab 4 — Khử trùng Cạnh Lặp ([triple_dedup_tab.py](../../frontend/components/merge/triple_dedup_tab.py)):**
     - Banner hành động `st.columns([2, 1.2])` (62.5% / 37.5%) -> Bảng nhóm trùng -> Expander Lịch sử & `edge_redirects`.

### 6.5. Footer Trang 4
- `st.container(border=True)` + `st.columns([3.5, 1.5])` (**70% | 30%**): nút `➡️ Chuyển sang Bước 5: Khai thác & Xuất đồ thị`.

---

## 7. Trang 5: Khai thác Đồ thị & Xuất Dữ liệu (`p05_graph_export.py`)

**Tệp nguồn:** [p05_graph_export.py](../../frontend/pages/p05_graph_export.py), [graph_source.py](../../frontend/components/graph_source.py), [graph_view.py](../../frontend/components/graph_view.py), và `frontend/components/export_tabs/*`.

### 7.1. Bộ chọn Nguồn & Sức khỏe Đồ thị
1. `select_graph_snapshot` ([graph_source.py](../../frontend/components/graph_source.py)): `st.radio(..., horizontal=True)` với 3 nguồn: `Đồ thị đã duyệt` (`approved`) | `Baseline B — KG thô` (`baseline`) | `Graph từ file` (`external`).
   - **Khi chọn `baseline`:** Hiện `st.columns(2)` (50% Chọn toàn bộ chunks / 50% Xóa chọn) + `st.multiselect` runs. Nếu chưa chọn run nào -> dừng sớm (`return None`) tại `st.info`.
   - **Khi chọn `external`:** Hiện `st.file_uploader` (`.json`, `.zip`). Nếu chưa có file -> dừng sớm (`return None`).
2. **Phân khu 1 — Báo cáo Sức khỏe Đồ thị (`container(border=True)`):** `st.columns(3)` (**33.3% × 3** Metrics: `Nodes` | `Edges / observations` | `Tính toàn vẹn`) + Expander chi tiết cảnh báo nếu `problems` khác rỗng.

### 7.2. Phân khu 2 — `st.tabs(4)` Tách bạch Khám phá & Nghiên cứu

| Tab | Bố cục Cột & Thành phần chính | Biến thể Trạng thái |
| :--- | :--- | :--- |
| **1. Khám phá & Hỏi đáp** ([g_retriever_tab.py](../../frontend/components/export_tabs/g_retriever_tab.py)) | Câu hỏi mẫu `[4, 1]` -> Input câu hỏi -> Expander `🔬 Tham số thuật toán & Chế độ đối sánh` (`method`, `max_edges`, `hub_alpha`, `expand_leaf`) -> 2 nút chạy `st.columns(2)`. | **Mode `compare_all`:** Expander tự mở, 3 cột đối sánh song song.<br>**Mode đơn (`pcst`/`ppr`/`naive_topk`):** KPI 5 cột + Split `[1.25, 1.0]`. |
| **2. Bản đồ, Bảng & Xuất tệp** ([p05_graph_export.py](../../frontend/pages/p05_graph_export.py)) | Slider giới hạn cạnh minh họa `[4, 1]` + `st.graphviz_chart` tương phản nền sáng (`#EFF6FF`/`#1D4ED8`) + Expander Bảng quan hệ & Bằng chứng đầy đủ hỗ trợ bàn phím -> Xuất JSON/CSV/ZIP/Neo4j. | Hiển thị rõ banner trạng thái nguồn (`approved` vs `baseline` vs `external`) và ghi chú giới hạn hiển thị không cắt tệp xuất. Khi `not current_approved`, ẩn ZIP 11 tệp & Neo4j. |
| **3. Nghiên cứu: Đối sánh** ([benchmark_tab.py](../../frontend/components/export_tabs/benchmark_tab.py)) | Cấu hình `[1.2, 1.2, 1.6]` -> Summary `st.dataframe` -> Export JSON/CSV/Markdown. | Phân biệt câu hỏi tự sinh cùng graph vs gold facts JSON độc lập. |
| **4. Nghiên cứu: QA Studio** ([training_dataset_tab.py](../../frontend/components/export_tabs/training_dataset_tab.py)) | Cấu hình `[1.5, 1.2, 1.3]` -> 5 KPI -> Phân bố 6 nhóm & Paraphrase -> Preview -> ZIP 11 tệp. | Khi `not current_approved`, ẩn form sinh dữ liệu huấn luyện. |

### 7.3. Footer Trang 5
- `st.container(border=True)` + `st.columns([2.5, 1.25, 1.25])` (**50% mô tả | 25% Quay lại Bước 4 | 25% Bổ sung tài liệu Bước 1**).

---

## 8. Chi tiết HTML/CSS Inline & Ghi chú Kỹ thuật cho AI Agent

1. **Tô sáng Bằng chứng & Ngữ cảnh Văn bản:**
   - [evidence_panel.py](../../frontend/components/evidence_panel.py#L36-L52) (`format_highlighted_evidence_html`): Box nền `#f8fafc`, viền `1px solid #cbd5e1`, `border-radius:6px`, `padding:12px`, `line-height:1.65`, `font-size:0.95rem`, thẻ `<mark style='background:#fde047;...'>`; khi không tìm thấy dùng nền cảnh báo `#fffbeb` viền trái `#d97706`.
   - [provenance_view.py](../../frontend/components/merge/provenance_view.py#L21-L90) (`highlight_text_html`): Giới hạn khung cuộn dọc `max-height:360px;overflow-y:auto;` (`font-size:0.92rem`), tự động cắt cửa sổ `max_chars=1500` quanh vị trí khớp đầu tiên. Được tái sử dụng trong cả `provenance_view.py` lẫn `edc_review_table.py`.
2. **Căn chỉnh lề cột với Widget có Label:**
   - [gazetteer_panel.py](../../frontend/components/gazetteer_panel.py#L87) dùng `<div style='height: 1.75rem'></div>` để căn nút ở cột phải thẳng hàng ngang với `st.file_uploader` bên trái.
   - Các trang mới hơn (`p05_graph_export.py`, `g_retriever_tab.py`, `benchmark_tab.py`, `training_dataset_tab.py`) ưu tiên dùng tham số chuẩn của Streamlit `st.columns(..., vertical_alignment="bottom")`.
3. **Ràng buộc An toàn khi Chỉnh sửa UI (theo `AGENTS.md`):**
   - Toàn bộ widget/tác vụ ghi dữ liệu từ UI phải đi qua `get_facade()` hoặc `get_ui_composition()` (`ProjectCommitCoordinator`), không ghi trực tiếp JSON/SQLite từ tầng UI.
   - Bảo toàn các `key=` trong `st.session_state` (nhất là bộ key đồng bộ 2 chiều Sidebar ↔ Trang 2 `sb_llm_*` / `p02_llm_*`, bộ lọc phân trang `edc_*` / `cur_*`, và `_curation_return_context`).
   - Toàn bộ bố cục đã thống nhất sử dụng `width="stretch"` (thay thế hoàn toàn `use_container_width=True` trước đây).
