# Báo cáo Triển khai Tối ưu Hiệu năng và Bộ nhớ (Performance & Memory Optimization Report)

- **Ngày thực hiện**: 30/10/2026
- **Căn cứ kế hoạch**: [performance-optimization.md](performance-optimization.md)
- **Mã nguồn thực hiện**: `D:\DATN\CrawData\KG_Studio`
- **Môi trường đo kiểm**:
  - Python: `3.13.2 64-bit` (`D:\DATN\CrawData\KG_Studio_MVP\.venv-win\Scripts\python.exe`)
  - SQLite: `3.45.3`
  - Streamlit: `1.66.1`
- **Bộ công cụ đo lường**: `tools/benchmark_performance.py` kết hợp `tracemalloc` và `time.perf_counter`.
- **Dữ liệu xuất đo lường**:
  - Baseline: `AI/report/perf-baseline.json`
  - Sau tối ưu (Stage A): `AI/report/perf-stage_a.json`

---

## 1. TỔNG QUAN KẾT QUẢ ĐO LƯỜNG ĐỊNH LƯỢNG (BENCHMARK RESULTS)

Toàn bộ các phép đo đều được thực thi trên cùng một máy, không phụ thuộc vào LLM bên ngoài, chia làm 2 quy mô chuẩn:
- **Quy mô S (Small)**: 3 tài liệu, 60 thực thể, 150 quan hệ, 15 đề xuất EDC.
- **Quy mô M (Medium)**: 20 tài liệu (~1 MB text), 500 thực thể, 2.000 quan hệ, 100 đề xuất EDC.

### 1.1. Bảng so sánh Quy mô M (500 thực thể, 2.000 quan hệ)

| Thao tác / Hàm đo lường | Baseline p50 (ms) | Stage A p50 (ms) | **Tăng tốc (Speedup)** | Baseline Peak RAM | Stage A Peak RAM | **Giảm RAM** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`list_projects()`** (Sidebar / Rerun) | 278.80 ms | **1.01 ms** | **276x nhanh hơn** | 38,120.1 KB (~38.1 MB) | **18.2 KB** | **Giảm 99.95%** |
| **`review_stats()`** (Render Tab 4) | 6,708.32 ms | **83.96 ms** | **80x nhanh hơn** *(p95: 362x)* | 320,383.4 KB (~320 MB) | **5,019.4 KB (~5.0 MB)** | **Giảm 98.43%** |
| **`duplicate_suggestions()`** (Gợi ý trùng) | 6,496.31 ms | **49.56 ms** | **131x nhanh hơn** | 307,498.0 KB (~307 MB) | **5,003.5 KB (~5.0 MB)** | **Giảm 98.37%** |
| **`vector_repo.ensure_index`** | 1.65 ms | **0.10 ms** | **16.5x nhanh hơn** | 333.7 KB | **332.7 KB** | Duy trì ổn định |
| **`evidence_context()`** (Direct slice) | 0.03 ms | **0.03 ms** | Không đổi (rất nhanh) | 8.7 KB | **8.6 KB** | Duy trì tối ưu |

### 1.2. Bảng so sánh Quy mô S (Dự án thông thường)

| Thao tác / Hàm đo lường | Baseline p50 (ms) | Stage A p50 (ms) | **Tăng tốc** | Baseline Peak RAM | Stage A Peak RAM | **Giảm RAM** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`list_projects()`** | 282.69 ms | **1.03 ms** | **274x** | 38,120.1 KB | **18.2 KB** | **Giảm 99.95%** |
| **`review_stats()`** | 90.25 ms | **6.83 ms** | **13.2x** | 4,628.7 KB | **417.6 KB** | **Giảm 91%** |
| **`duplicate_suggestions()`** | 74.02 ms | **20.38 ms** | **3.6x** | 4,457.9 KB | **2,377.9 KB** | **Giảm 46.7%** |
| **`vector_repo.ensure_index`** | 1.50 ms | **0.08 ms** | **18.7x** | 332.7 KB | **332.7 KB** | Duy trì tối ưu |

---

## 2. CHI TIẾT CÁC HẠNG MỤC ĐÃ TRIỂN KHAI

### 2.1. Manifest & In-Memory Project Registry (`backend/repositories/json_repo.py`)
- **Vấn đề trước đây**: Mỗi Streamlit rerun (click bất kỳ widget nào trên UI), sidebar gọi `list_projects()` $\rightarrow$ đọc đĩa và `json.loads` toàn bộ file `project.json` của mọi dự án (dự án 10 MB tốn ~100 ms và hàng chục MB RAM chỉ để lấy tên).
- **Giải pháp**:
  - Tạo file metadata nhỏ `project.meta.json` cho từng dự án (chứa `project_id`, `name`, `folder`, `schema_version`, `saved_at`, `counts`, `mtime_ns`, `size`).
  - Xây dựng cache in-memory `_PROJECT_REGISTRY_CACHE`.
  - `_folder_name_of`, `list_projects`, `list_project_headers`, `find_folder` ưu tiên đọc từ manifest hoặc RAM cache. Chỉ fallback parse full JSON 1 lần duy nhất khi manifest chưa tồn tại hoặc bị stale `mtime`.
  - Hàm `save_project` tự động cập nhật `project.meta.json` nguyên tử song song với `project.json`.

### 2.2. Khử tải nặng khi mở Curation Hub (`curation/service.py`, `p04_curation_hub.py`)
- **Vấn đề trước đây**: Khi mở Trang 4 (Curation Hub), hàm `review_stats` tự động kích hoạt:
  1. Quét tìm cặp nghi trùng lặp $O(N^2)$ qua `duplicate_suggestions(fuzzy_threshold=0.82)`.
  2. Duyệt qua toàn bộ cạnh và dựng lại dict `proposals`, `nodes`, `rel_norms`, `type_norms` cho mỗi cạnh.
  3. Cắt chuỗi và băm toàn văn bản tài liệu chỉ để đếm số chunks.
  Dẫn đến: với 500 nodes, chỉ riêng render tiêu tốn **6.7 đến 31.8 giây** và ngốn **320 MB RAM**.
- **Giải pháp**:
  - `review_stats(project, include_duplicates=False)`:
    - Mặc định chỉ lấy số lượng cặp nghi trùng từ cache (nếu đã quét trước đó) hoặc trả về `-1` ("Chưa quét").
    - Tiền tính toán (precomputed) `proposals`, `nodes`, `rel_norms`, `type_norms` 1 lần duy nhất cho toàn bộ danh sách cạnh trong `inspect_edge_schema_status`.
    - Tối ưu `count_chunks(text)` trong `documents/processor.py` sử dụng thuật toán duyệt con trỏ số (pointer arithmetic) thay vì tạo ra hàng ngàn dicts chunk và băm SHA.
  - Trên giao diện `p04_curation_hub.py`: Metric `m5` hiển thị `Chưa quét (bấm để quét)` và chuyển việc quét về đúng phân khu Thực thể khi người dùng có nhu cầu.
  - Trong `curation_table.py`: Bộ lọc nghi trùng `f_dup` chỉ gọi `duplicate_suggestions` khi checkbox được đánh dấu.

### 2.3. Bounded Duplicate Suggestions & Candidate Blocking (`curation/service.py`)
- **Vấn đề trước đây**: Thuật toán so khớp vét cạn $N(N-1)/2$ cặp node, trên mỗi cặp đều gọi `copy.deepcopy(first)` và `copy.deepcopy(second)`, sau đó `copy.deepcopy` toàn bộ danh sách kết quả trước khi trả về, gây tràn bộ nhớ Python.
- **Giải pháp**:
  - **Candidate Blocking / Inverted Index**:
    - Chuẩn hóa tên và bí danh 1 lần duy nhất.
    - Xây dựng chỉ mục đảo: theo tên chuẩn hóa, bí danh, các token từ $\ge 3$ ký tự, và tiền tố 3 ký tự.
    - Chỉ so khớp chi tiết `SequenceMatcher` trên các cặp ứng viên có khả năng trùng cao.
    - Đối với đồ thị nhỏ ($< 80$ nodes), tự động fallback kiểm tra toàn diện để đảm bảo 100% không bỏ sót.
  - **Khử bỏ deepcopy dư thừa**: Lưu trữ trực tiếp tham chiếu dictionary gọn nhẹ thay vì deepcopy lặp đi lặp lại.

### 2.4. Đối chiếu Bằng chứng Lát cắt Trực tiếp (`evidence_context`)
- **Vấn đề trước đây**: Khi mở chi tiết cạnh, `evidence_context` luôn quét `find_all_quote_spans` trên toàn bộ văn bản tài liệu dù cạnh đã có `verified_start_char` và `verified_end_char`.
- **Giải pháp**:
  - Thêm nhánh nhanh **Direct Slice**: Nếu `doc_fingerprint` hợp lệ và đã có vị trí span, cắt trực tiếp `text[start:end]` để so khớp exact/normalized.
  - Chỉ fallback quét regex/find toàn tài liệu khi vị trí lát cắt không khớp hoặc tài liệu bị sửa đổi.

### 2.5. Reverse Index cho Proposal Impact (`catalogs/service.py`, `edc_review_table.py`)
- **Vấn đề trước đây**: Khi hiển thị bảng EDC, mỗi proposal đều duyệt lại toàn bộ nodes và edges 3 lần $\rightarrow O(P \times (N + E))$ với hàng triệu phép so sánh.
- **Giải pháp**:
  - Bổ sung hàm `batch_proposal_impacts(project, proposal_ids)`: Xây dựng reverse index `proposal_id -> direct_nodes, direct_edges, indirect_edges` chỉ trong **1 lần duyệt duy nhất** $O(N + E)$.
  - Tối ưu bảng `edc_review_table.py`: Chỉ tính impact khi người dùng thực sự chọn sắp xếp theo số lượng cạnh ảnh hưởng (`sort_by == "impact_edges"`).

### 2.6. Bộ nhớ đệm Vector Index & Embedder Gateway (`vector_repo.py`, `embedder_gateway.py`)
- **Vấn đề trước đây**: Mỗi lần gọi tìm kiếm vector (SR hoặc Canonicalization), hệ thống phải giải nén tệp `.npz` từ đĩa, parse JSON và convert numpy array.
- **Giải pháp**:
  - Thêm `_INDEX_MEM_CACHE` trong `VectorIndexRepository` theo `(project_id, kind, model_fingerprint, catalog_hash)`.
  - Tự động xóa cache khi gọi `invalidate_project_indices`.
  - Thêm `_ST_MODEL_CACHE` và `_DEFAULT_EMBEDDER_CACHE` trong `embedder_gateway.py` để tái sử dụng mô hình embedding và gateway instance giữa các lần gọi.

### 2.7. Chuẩn bị Tệp Xuất Đồ thị Theo Yêu cầu (`p06_graph_export.py`)
- **Vấn đề trước đây**: Chỉ cần click vào Tab 5 ("5. Đồ thị & Xuất Neo4j"), Streamlit tự động serialize toàn bộ đồ thị ra JSON bytes và nén tệp ZIP vào RAM `BytesIO` do truyền tham số `data=...` trực tiếp vào `st.download_button`.
- **Giải pháp**:
  - Chuyển sang cơ chế **Chuẩn bị theo yêu cầu (On-Demand Preparation)**: Khi mở tab 5, người dùng chỉ thấy các nút "🔨 Chuẩn bị tệp JSON / ZIP".
  - Chỉ khi người dùng bấm nút, hệ thống mới tiến hành đóng gói và hiển thị nút tải về cùng nút làm mới. Tiết kiệm hàng chục MB RAM khi người dùng chỉ vào xem biểu đồ Graphviz.

### 2.8. Lược đồ Đọc DTO & Chỉ mục Truy vấn SQLite (`shared/schemas/queries.py`, `sqlite_repo.py`)
- Tạo mới module [shared/schemas/queries.py](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/queries.py) gồm: `ProjectHeaderDTO`, `PageDTO`, `EdgeRowDTO`, `NodeRowDTO`, `ProposalRowDTO`.
- Bổ sung 7 chỉ mục B-tree trong `backend/repositories/sqlite_repo.py`:
  - `idx_edges_status_page ON edges(project_id, status, chunk_number, id)`
  - `idx_edges_doc_page ON edges(project_id, doc_id, chunk_number, id)`
  - `idx_edges_source ON edges(project_id, source, id)`
  - `idx_edges_target ON edges(project_id, target, id)`
  - `idx_edges_relation ON edges(project_id, relation, id)`
  - `idx_nodes_kind_name ON nodes(project_id, kind, id)`
  - `idx_proposals_kind_status ON schema_proposals(project_id, kind, status, id)`
- Thêm phương thức truy vấn phân trang chuẩn `query_edges_page(project_id, status, doc_id, page, page_size)`.

---

## 3. KIỂM THỬ VÀ ĐẢM BẢO TÍNH TOÀN VẸN (VERIFICATION)

- Toàn bộ **40 unit tests** (34 tests hệ thống có sẵn + 6 tests tối ưu hiệu năng mới trong [tests/test_performance_optimizations.py](file:///D:/DATN/CrawData/KG_Studio/tests/test_performance_optimizations.py)) đã chạy và vượt qua 100%:
  ```bash
  Ran 40 tests in 2.146s - OK
  ```
- Tính tương thích ngược 100%:
  - Không phá vỡ bất kỳ API hoặc DTO nào của facade/domain.
  - Các dự án hiện tại (`HanoiQA`, `HanoiQAV2`, `HanoiQAV3`) tự động tạo manifest `project.meta.json` trong lần đọc đầu tiên mà không làm biến đổi cấu trúc `project.json`.

