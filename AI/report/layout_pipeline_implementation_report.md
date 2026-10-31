# Báo cáo Triển khai Quy chuẩn Bố cục & Luồng Sử dụng 5 Bước (KG Studio)

- **Ngày hoàn thành**: 31/10/2026.
- **Căn cứ đề xuất**: [layout-pipeline-proposal.md](layout-pipeline-proposal.md).
- **Phạm vi triển khai**: Toàn bộ hệ thống frontend (`frontend/app.py`, `frontend/state/session.py`, `frontend/components/pipeline_banner.py`, các màn hình `p01` đến `p06`), tích hợp engine điều hướng, kiểm thử đơn vị (`tests/test_layout_pipeline.py`, `tests/test_curation_hub.py`).
- **Trạng thái**: Hoàn tất 100%, 47/47 unit tests pass.

---

## 1. Tổng quan & Mục tiêu Cải tiến

Trước đây, giao diện KG Studio được tổ chức theo các thẻ chức năng kỹ thuật mang tính độc lập (Dự án, EDC+R & ML Lab, Trích xuất, Hub Kiểm duyệt, Xuất Neo4j). Người dùng mới hoặc nhà nghiên cứu thường gặp khó khăn trong việc nhận diện:
- Dữ liệu đầu vào của bước này đến từ đâu?
- Khi nào một bước đủ điều kiện hoàn thành để chuyển sang bước kế tiếp?
- Cần làm gì tiếp theo sau khi chạy xong một tác vụ trích xuất hoặc kiểm duyệt?

Dựa trên đề xuất chi tiết tại `layout-pipeline-proposal.md`, toàn bộ trải nghiệm người dùng đã được tái cấu trúc xoay quanh **Quy trình 5 bước chuẩn hóa**:

$$\text{1. Tài liệu} \longrightarrow \text{2. Thiết lập} \longrightarrow \text{3. Trích xuất} \longrightarrow \text{4. Rà soát} \longrightarrow \text{5. Khai thác}$$

Mỗi bước đều có:
1. **Mục tiêu rõ ràng** và **điều kiện sẵn sàng (readiness criteria)**.
2. **Dấu chỉ trạng thái trực quan**: Đã hoàn tất (`✓`), Đang có việc cần xử lý (`●`), Thiếu điều kiện cần (`!`), Chưa bắt đầu (`○`).
3. **Thẻ gợi ý hành động tiếp theo (Contextual Next Action Banner)** với nút bấm CTA chuyển bước tức thời (1-click transition).
4. **Cơ chế lặp (Feedback loops)**: Cho phép chạy lại đoạn lỗi, quay lại chỉnh catalog, hoặc bổ sung tài liệu mới mà không mất ngữ cảnh làm việc.

---

## 2. Các Module Cốt lõi & Engine Điều hướng Đã Xây dựng

### 2.1. Pipeline Readiness & Route Normalization (`frontend/state/session.py`)

- **Chuẩn hóa danh mục định danh & nhãn hiển thị**:
  - `PIPELINE_STEPS = ["documents", "setup", "extraction", "review", "explore"]`
  - `PAGE_LABELS = ["1. Tài liệu", "2. Thiết lập", "3. Trích xuất", "4. Rà soát", "5. Khai thác"]`
- **Tương thích ngược 100% (`normalize_page_label`)**:
  - Tự động chuyển đổi các nhãn phiên bản cũ trong `session_state` (ví dụ `"1. Dự án & Tài liệu"` $\rightarrow$ `"1. Tài liệu"`, `"4. Kiểm duyệt & Chuẩn hóa Tri thức"` $\rightarrow$ `"4. Rà soát"`) để không làm gián đoạn các phiên làm việc đang mở.
- **Hàm điều hướng tiện ích (`navigate_to_step`)**:
  - Hỗ trợ điều hướng bằng cả index (`0..4`) hoặc mã định danh step (`"documents"`, `"setup"`, `"extraction"`, `"review"`, `"explore"`).
  - Tự động đồng bộ đồng thời `active_page` và `active_step`.
- **Engine tính toán độ sẵn sàng (`compute_pipeline_readiness`)**:
  - Phân tích realtime dữ liệu của `project`:
    - `documents`: Số lượng tài liệu, tổng ký tự, trạng thái sẵn sàng.
    - `setup`: Kiểm tra sự tồn tại của danh mục thực thể & quan hệ, chế độ trích xuất đang chọn.
    - `extraction`: Số lượt chạy, số đoạn thành công vs lỗi (cảnh báo nếu có lỗi cục bộ).
    - `review`: Đếm số quan hệ chờ duyệt, cạnh nghi vấn (`check`), đề xuất EDC đang chặn (`schema_blocked`), và số dữ kiện đã duyệt.
    - `explore`: Xác định đồ thị đã sẵn sàng xuất bản khi có ít nhất một dữ kiện được duyệt.
  - Tự động sinh đối tượng `overall_next` chỉ định bước ưu tiên số 1 mà người dùng cần thực hiện tiếp.

### 2.2. Dải Tiến trình Ngang & Banner Hành động (`frontend/components/pipeline_banner.py`)

- **`render_pipeline_header(project)`**:
  - Thanh breadcrumbs 5 cột nằm ngang ngay dưới tiêu đề ứng dụng.
  - Mỗi bước hiển thị số thứ tự, tên ngắn gọn và huy hiệu trạng thái (badge) cập nhật tự động.
  - Bước hiện tại được làm nổi bật với nút màu Primary; người dùng có thể nhấp vào bất kỳ bước nào để chuyển trang nhanh.
- **`render_step_next_action(current_step_id, project)`**:
  - Hộp thông báo ngữ cảnh thông minh đặt tại đầu mỗi màn hình làm việc:
    - Nếu đã thỏa điều kiện: Hiển thị mục tiêu hoàn thành, tóm tắt dữ liệu hiện có và nút CTA màu Primary (ví dụ: `[➡️ Chuyển sang Bước 3: Trích xuất tri thức]`).
    - Nếu chưa thỏa điều kiện: Hiển thị cảnh báo hướng dẫn cụ thể cần làm gì (ví dụ: *"Chưa có tài liệu nào trong dự án. Hãy tải lên ít nhất một tệp để tiếp tục"*).

### 2.3. Tinh gọn Sidebar & Khung Khởi chạy (`frontend/app.py`)

- **Sidebar tập trung vào không gian dự án**:
  - Bộ chọn dự án đang mở và ô tạo dự án mới theo tên.
  - Radio điều hướng 5 bước dọc kèm huy hiệu sống (`[✓]`, `[●]`, `[!]`, `[○]`).
  - Toàn bộ các cấu hình LLM nâng cao (Base URL, API Key, Token Sliders, Auto, Lưu TOML, Test LLM) được thu gọn trong Expander `⚙️ Cài đặt LLM & Token` để giải phóng không gian màn hình chính.
- **Thanh Header ngang cố định**: Giữ vị trí nhận diện quy trình trên mọi màn hình làm việc.

---

## 3. Chi tiết Nâng cấp Trên 5 Bước Nghiệp vụ

### Bước 1: Tài liệu (`frontend/pages/p01_projects_docs.py`)
- **Tích hợp Next Action Banner**: Hướng dẫn chuyển tiếp sang Bước 2 khi đã có tài liệu.
- **Thẻ "Tiếp tục công việc" (Continue Work Card)**:
  - Nếu dự án đã có tài liệu: Tự động phát hiện các tài liệu chưa trích xuất hoặc các dữ kiện đang chờ duyệt ở Bước 4, cung cấp nút tắt nhảy thẳng đến tác vụ dở dang.
- **Khu vực Tải tệp & Quản lý Tài liệu**:
  - Vùng kéo thả tệp văn bản trực quan.
  - Metadata bổ sung (Phạm vi địa lý / Nguồn tài liệu) đặt trong expander tùy chọn.
  - Bảng danh sách tài liệu sử dụng hàm `count_chunks` gọn nhẹ (tránh gọi toàn bộ bộ chia đoạn nặng).
  - Trình đọc xem trước nội dung tài liệu với thanh cuộn tự động.
- **Nút CTA chân trang**: `[➡️ Chuyển sang Bước 2: Thiết lập trích xuất]`.

### Bước 2: Thiết lập (`frontend/pages/p02_catalogs_prompts.py`)
- **Tích hợp Next Action Banner**: Kiểm tra trạng thái danh mục và mô hình trước khi cho phép trích xuất.
- **Centralized LLM Connection Card**:
  - Hộp cấu hình kết nối mô hình tập trung: Nhà cung cấp, Tên mô hình, Base URL, API Key.
  - Thanh trượt cấu hình Input/Output Tokens trực quan kèm nút `⚡ Auto theo mô hình` và `🔌 Kiểm tra kết nối LLM`.
- **Danh mục Toàn màn hình (Full-width Catalog Tabs)**:
  - Tách thành 2 thẻ tab rộng rãi: `[🏷️ Loại thực thể / Đối tượng]` và `[🔗 Loại quan hệ]`.
  - Khắc phục triệt để tình trạng hiển thị 2 bảng hẹp cạnh nhau gây khó đọc định nghĩa dài.
  - Đầy đủ chức năng Chỉnh sửa trực tiếp (Data Editor), Tải JSON mẫu, Nhập JSON (hỗ trợ ghi đè hoặc hợp nhất).
- **Công cụ Chuyên sâu (Advanced Expander)**:
  - Thu gọn System Prompt và ML Lab vào Expander `🛠️ Công cụ Chuyên sâu: System Prompt & Tối ưu ML Lab` để giao diện chính gọn gàng cho người dùng thông thường.
- **Nút CTA chân trang**: `[➡️ Chuyển sang Bước 3: Trích xuất tri thức]`.

### Bước 3: Trích xuất (`frontend/pages/p03_extraction.py`)
- **Tích hợp Next Action Banner**: Đánh giá số lượt trích xuất và số đoạn lỗi.
- **Tóm tắt cấu hình & Expander Token**:
  - Tóm tắt gọn mô hình đang dùng trên thanh tiêu đề.
  - Expander cho phép tinh chỉnh nhanh ngân sách token khi cần thiết mà không phải quay lại Bước 2.
- **Bộ chọn tài liệu trực quan**:
  - Hỗ trợ bộ lọc tìm kiếm theo tên file.
  - Phím chọn nhanh: `☑️ Chọn tất cả`, `⬜ Bỏ chọn hết`, `⚪ Chọn file chưa trích xuất`.
  - Khung bảng có thanh cuộn mượt mà kèm ước tính số đoạn và dung lượng ký tự.
- **Tách bạch 2 chế độ kích hoạt**:
  - `🧪 Chạy thử 1 đoạn mẫu (Dry-run)`: Trích xuất ngay chunk đầu tiên để kiểm tra prompt và phản hồi LLM an toàn, nhanh chóng.
  - `▶️ Bắt đầu trích xuất phần đã chọn`: Xử lý toàn bộ các đoạn của các file được đánh dấu.
- **Báo cáo tiến trình & Xử lý lỗi cục bộ**:
  - Thanh tiến trình hiển thị rõ file và đoạn đang xử lý.
  - Phân định rõ ràng số đoạn trích xuất thành công vs số đoạn gặp lỗi.
  - Khi có lỗi, hiển thị nút `🔄 Chạy lại các đoạn gặp lỗi` để người dùng khắc phục ngay mà không phải chạy lại từ đầu.
- **Step Traces & Raw JSON**: Lưu trữ và kiểm tra chi tiết các bước suy luận của mô hình.
- **Nút CTA chân trang**: `[➡️ Chuyển sang Bước 4: Rà soát & Chuẩn hóa Tri thức]`.

### Bước 4: Rà soát & Chuẩn hóa (`frontend/pages/p04_curation_hub.py`)
- **Tích hợp Next Action Banner**: Đếm số dữ kiện cần xử lý và thông báo khi đồ thị đã sạch 100%.
- **Action Cards điều hướng tức thời từ số liệu**:
  - Bấm `[⛔ Xử lý X Lược đồ & Y cạnh vướng]` $\rightarrow$ Chuyển ngay sang tab **Schema EDC** để giải quyết các đề xuất danh mục đang chặn cạnh.
  - Bấm `[🔬 Rà soát Z Quan hệ chờ duyệt]` $\rightarrow$ Chuyển sang tab **Duyệt Quan hệ & Bằng chứng**.
  - Bấm `[🔀 Khử trùng lặp W Cặp thực thể]` $\rightarrow$ Chuyển sang tab **Quản lý & Gộp thực thể** ở chế độ Entity Merge.
- **Giữ vững tính năng ngữ cảnh quay lại (Return Context Banner)**:
  - Khi người dùng bấm xử lý đề xuất chặn từ một cạnh, hệ thống ghi nhớ và cung cấp nút `↩️ Quay lại mục đang kiểm duyệt ở Phân khu Quan hệ`.
- **Nút CTA chân trang**: `[➡️ Chuyển sang Bước 5: Khai thác & Xuất đồ thị]`.

### Bước 5: Khai thác & Xuất đồ thị (`frontend/pages/p06_graph_export.py`)
- **Tích hợp Next Action Banner**: Tóm tắt quy mô đồ thị đã duyệt.
- **Phân khu 1: Khai thác đồ thị đã duyệt**:
  - Trực quan hóa đồ thị tri thức với Graphviz được định dạng màu sắc trang nhã, phân biệt rõ nút và liên kết.
  - Bảng chỉ số sức khỏe: Số Nodes, Edges, và Báo cáo toàn vẹn cấu trúc (Integrity Check).
  - Thông báo chính xác phạm vi kiểm tra: *"Không phát hiện lỗi cấu trúc trong các kiểm tra hiện có"*.
- **Phân khu 2: Xuất dữ liệu On-demand**:
  - Cơ chế tạo tệp xuất theo yêu cầu (`approved_json_bytes` và `export_zip`) giúp giải phóng bộ nhớ RAM.
  - Thông tin xuất bản minh bạch: Tên dự án, Mã Revision (`project_revision`), Thời điểm xuất.
- **Phân khu 3: Tích hợp CSDL Neo4j (Expander)**:
  - Đặt cấu hình đồng bộ Neo4j vào Expander nâng cao, tránh làm rối mắt người dùng chỉ có nhu cầu tải file JSON/ZIP.
- **Nút điều hướng lặp**:
  - `[🔍 Quay lại Bước 4: Rà soát]` để duyệt thêm dữ kiện.
  - `[➕ Bổ sung tài liệu ở Bước 1]` để nạp tài liệu mới vào đồ thị.

---

## 4. Bảng So sánh Trước và Sau Khi Tái cấu trúc

| Khía cạnh | Trước khi Tối ưu | Sau khi Chuẩn hóa Quy trình 5 Bước |
| :--- | :--- | :--- |
| **Cấu trúc Menu** | 5 tab kỹ thuật dài: *"Danh mục, EDC+R & ML Lab"*, *"Kiểm duyệt & Chuẩn hóa Tri thức"* | 5 bước quy chuẩn ngắn gọn: `1. Tài liệu` $\rightarrow$ `2. Thiết lập` $\rightarrow$ `3. Trích xuất` $\rightarrow$ `4. Rà soát` $\rightarrow$ `5. Khai thác` |
| **Chỉ dẫn Quy trình** | Người dùng tự suy luận bước tiếp theo; không có liên kết giữa các màn hình | Dải Breadcrumbs kèm Huy hiệu tiến độ (`✓`, `●`, `!`, `○`) và Banner gợi ý hành động CTA |
| **Cấu hình LLM & Token** | Phân tán ở cả Sidebar, Trang 2 và Trang 3; dễ lệch giá trị | Tập trung tại Bước 2 (Centralized Connection Card), có Expander tinh chỉnh nhanh tại Sidebar và Bước 3 |
| **Bảng Danh mục (Catalogs)** | Hai bảng hẹp đặt cạnh nhau, chữ bị ép dòng khó đọc | Hai Tab toàn màn hình (`Loại thực thể` và `Loại quan hệ`) rộng rãi, dễ thao tác |
| **Thao tác Trích xuất** | Chỉ có nút chạy toàn bộ; nếu lỗi chunk vẫn báo thành công chung | Hỗ trợ nút `🧪 Chạy thử 1 đoạn mẫu` và nút `🔄 Chạy lại các đoạn gặp lỗi` chuyên biệt |
| **Chuyển đổi Kiểm duyệt** | Số liệu tĩnh; phải tự tìm đến tab cần xử lý | Thẻ Action Cards nhấp 1 phát chuyển thẳng đến vấn đề (Schema blocked $\rightarrow$ Schema tab, Cặp trùng $\rightarrow$ Merge tool) |
| **Khai thác & Xuất** | Trộn lẫn đồ thị trực quan, tải file và form cấu hình Neo4j | Tách 3 phân khu rõ: Bản đồ đồ thị $\rightarrow$ Xuất JSON/ZIP On-demand $\rightarrow$ Expander Neo4j |
| **Bộ nhớ & Hiệu năng** | Xuất file nén giữ cache nặng, tính số chunk tốn thời gian | Kế thừa tối ưu On-demand generator, `count_chunks` siêu tốc |

---

## 5. Kết quả Kiểm thử Đơn vị & Xác minh Toàn vẹn

Hệ thống kiểm thử đã được bổ sung và cập nhật toàn diện:
1. **`tests/test_layout_pipeline.py` (Mới tạo)**:
   - Kiểm tra tính nhất quán của `PIPELINE_STEPS` và `PAGE_LABELS`.
   - Kiểm tra khả năng chuẩn hóa nhãn tương thích ngược (`normalize_page_label`).
   - Kiểm tra chuyển bước điều hướng (`navigate_to_step`, `get_active_step`).
   - Kiểm tra logic tính toán độ sẵn sàng (`compute_pipeline_readiness`) trên cả dự án rỗng và dự án đã có dữ liệu.
   - Kiểm tra khả năng render không lỗi của component banner và cả 5 màn hình nghiệp vụ.
2. **`tests/test_curation_hub.py` (Cập nhật)**:
   - Cập nhật assertion kiểm tra nhãn trang mới và tính tương thích ngược.

### Kết quả chạy kiểm thử tự động:
```text
Ran 47 tests in 2.009s
OK
```
- **Tổng số tests**: 47 (tăng từ 40 tests ban đầu).
- **Tỷ lệ Pass**: **100% (47/47)**.
- **Biên dịch cú pháp Python**: Đạt 100% không cảnh báo trên toàn bộ các file `frontend/`.

---

## 6. Kết luận & Hướng phát triển

Việc hiện thực hóa đề xuất tại `layout-pipeline-proposal.md` đã hoàn thiện chuyển đổi KG Studio thành một công cụ làm giàu và chuẩn hóa tri thức có cấu trúc trực quan, chuyên nghiệp, hỗ trợ tối đa cho cả người dùng phổ thông, nhà nghiên cứu học thuật lẫn chuyên gia kỹ thuật AI.
Các bước tiếp theo có thể mở rộng:
- Bổ sung phím tắt bàn phím (Keyboard Shortcuts: `Alt+1` đến `Alt+5`) để chuyển nhanh giữa các bước.
- Lưu lại nhật ký các quyết định duyệt vào file báo cáo tiến độ tải về được.
- Tích hợp thêm các tùy chọn thuật toán trực quan hóa đồ thị động (Interactive Cytoscape / Pyvis) trong Bước 5 khi kích thước đồ thị lớn hơn 500 nodes.

