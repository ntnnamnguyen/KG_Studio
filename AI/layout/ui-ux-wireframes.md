# Wireframes & Bộ Nhãn Thống nhất cho Cải tiến UI/UX (Đợt U0)

> **Ngày lập:** 2026-11-13  
> **Mục tiêu:** Thiết kế wireframe mục tiêu cho 5 bước (bao gồm trạng thái rỗng / lỗi / đang xử lý / thành công) và chuẩn hóa ngôn ngữ hiển thị thân thiện với người dùng không chuyên nhưng giữ chính xác khoa học.

---

## 1. Bộ Từ vựng & Nhãn Giao diện Thống nhất

| Khái niệm nội bộ | Nhãn hiển thị mặc định (người dùng phổ thông) | Hiển thị trong Khu Nghiên cứu / Chi tiết kỹ thuật |
| :--- | :--- | :--- |
| `nodes` / `edges` | **Đối tượng** / **Quan hệ** | Giữ mã ID, `(Node / Edge)` ở phần mô tả chi tiết & xuất |
| `chunks` / `runs` | **Đoạn văn** / **Lần xử lý** | `chunk_number`, `run_id` đặt trong chi tiết kỹ thuật |
| `schema` / `catalog` | **Danh mục loại đối tượng và quan hệ (schema)** | `entity_types`, `relations`, `schema_proposals` |
| `Lưu TOML` | **Lưu làm mặc định toàn hệ thống** | Ghi chú rõ lưu vào `config/default.toml`, áp dụng cho phiên mặc định |
| `Preview` / `Apply` | **Xem trước thay đổi** / **Áp dụng thay đổi** | Giữ chế độ `All-or-Nothing` (toàn bộ) / `Valid-Only` (chỉ mục hợp lệ) kèm giải thích rõ |
| `Integrity` | **Kiểm tra cấu trúc dữ liệu** | Cảnh báo rõ: *"Kiểm tra cấu trúc không xác nhận tính đúng đắn lịch sử"* |
| `Approved` | **Đã được người dùng duyệt** | Không khẳng định là sự thật khách quan tuyệt đối |
| `Baseline` | **Đồ thị thô từ AI — baseline B (chưa chuẩn hóa ngữ nghĩa)** | Hiển thị rõ phạm vi thử nghiệm & manifest các lần xử lý đã chọn |
| `Auto Target Alignment` | **Gợi ý ghép danh mục tự động (AI)** | Nhãn rõ *"Không tính là quyết định xác nhận của người dùng"* |

---

## 2. Wireframe Khung Chung (U1 Shell)

```text
+-----------------------+-------------------------------------------------------------------+
| SIDEBAR (Chính)       | MAIN WORKSPACE (layout="wide")                                    |
| KG Studio Pro         | +---------------------------------------------------------------+ |
|                       | | DỰ ÁN: [Tên dự án] · BƯỚC HIỆN TẠI: [2/5 · 2. Thiết lập]     | |
| 📂 Mở dự án           | | Tiến độ: 1.Tài liệu ✓ | 2.Thiết lập ✓ | 3.Trích xuất ○ | ...  | |
| [Selectbox dự án]     | +---------------------------------------------------------------+ |
| ▸ ➕ Tạo dự án mới    |                                                                   |
| ───────────────────── | +---------------------------------------------------------------+ |
| 🧭 Quy trình 5 Bước   | | THẺ MỤC TIÊU BƯỚC HIỆN TẠI & HÀNH ĐỘNG TIẾP THEO (3.5 : 1.5) | |
| (●) 1. Tài liệu [✓]   | | 🎯 Đang làm gì / Trạng thái hiện tại  | [➡️ Bước tiếp (phụ)]  | |
| ( ) 2. Thiết lập [✓]  | +---------------------------------------------------------------+ |
| ...                   |                                                                   |
| ───────────────────── | [NỘI DUNG MÀN HÌNH ĐANG MỞ]                                       |
| 🤖 Kết nối AI (tóm tắt)|                                                                  |
| DeepSeek / model      |                                                                   |
| Key: Đã lưu | In/Out  |                                                                   |
| [⚙️ Sửa ở Bước 2]     |                                                                   |
+-----------------------+-------------------------------------------------------------------+
```

---

## 3. Wireframe 5 Màn hình & Các Trạng thái Chính (U2–U6)

### Bước 1 — Thêm & Kiểm tra Tài liệu (U2)
```text
[1. Tài liệu — Thêm và kiểm tra tư liệu nguồn]
[Banner: Mục tiêu bước | Trạng thái (N tài liệu) | Hành động gợi ý]
[Cảnh báo nếu có chunk lỗi (nhảy Bước 3) hoặc mục chờ duyệt (nhảy Bước 4)]

+-----------------------------------------------------------------------+
| 1. Chọn tệp từ máy (.txt, .docx, .pdf)                                |
| [File Uploader]                                                       |
| ▸ Nguồn & phạm vi tư liệu (tùy chọn, 2 cột 50%/50%)                  |
| [📥 Thêm N tệp đã chọn vào dự án (Primary)]                           |
| -> Kết quả từng tệp sau khi thêm (Thành công / Cảnh báo hoặc Lỗi)    |
+-----------------------------------------------------------------------+

[Trạng thái RỖNG]: Info hướng dẫn tải ít nhất 1 tệp để bắt đầu.
[Trạng thái CÓ TÀI LIỆU]:
  Bảng tóm tắt gọn (100% rộng): Tên tệp | Trạng thái | Nguồn | Phạm vi | Cảnh báo
  ▸ Chi tiết kỹ thuật & Xem trước văn bản đã đọc (số ký tự, ước tính đoạn, text_area 3.000 ký tự đầu)
  [Footer: Chuyển sang Bước 2 (phụ khi chưa sẵn sàng, chính khi đã có tài liệu)]
```

### Bước 2 — Chọn Phương pháp & Thiết lập (U3)
```text
[2. Thiết lập — Kết nối AI, Phương pháp & Danh mục]
1. [Khu Kết nối AI (DUY NHẤT để chỉnh sửa)]
   Form gọn tối đa 2 cột/hàng: Provider + Model | Base URL + API Key | Token sliders
   [Kiểm tra kết nối] [Đặt lại theo model] [Lưu mặc định hệ thống] [Lưu/Xóa API Key]

2. [Phương pháp Trích xuất — Dễ hiểu cho người không chuyên]
   Thẻ trạng thái: "Đang áp dụng: [Tên phương pháp]" (và nút Áp dụng nếu đang xem phương pháp khác)
   4 lựa chọn có bảng/tóm tắt rõ: Mục đích · Đầu ra · Yêu cầu · Giới hạn
   [Lưu ý ngữ cảnh]: Nếu chọn Baseline B -> Thông báo rõ Danh mục & Từ điển bên dưới KHÔNG dùng trong lần chạy Baseline B.
   ▸ Cài đặt Nâng cao & Nghiên cứu (Prompt, Phiên bản, Xem trước Request, Tham số EDC+R)

3. [Danh mục & Từ điển của Dự án] (3 Tabs: Loại đối tượng | Loại quan hệ | Từ điển Bí danh)
   [Thông báo ngữ cảnh nếu Baseline B đang áp dụng]

4. ▸ [Phòng thí nghiệm Nghiên cứu (ML Lab & Active Learning)] (1 cấp expander, không lồng)
```

### Bước 3 — Chạy & Theo dõi Trích xuất (U4)
```text
[3. Trích xuất — Chạy phân tích tài liệu]
[Tóm tắt cấu hình thực tế đang áp dụng (1 dòng thẻ): Phương pháp | AI Model | Nguồn API key | Bước dẫn tới Bước 2 nếu cần đổi]

1. [Chọn tài liệu cần xử lý] (Tìm kiếm + Chọn tất cả / Bỏ chọn / Chưa xử lý + Bảng có trạng thái chữ+icon)
2. [Phạm vi & Chạy trích xuất]
   Tóm tắt: Đã chọn X/Y tài liệu (~Z đoạn văn bản) theo cấu hình [mode].
   Ghi chú minh bạch: "Chạy thử 1 đoạn VẪN gọi AI, có phát sinh chi phí token và lưu vào nhật ký dự án."
   ▸ Tùy chỉnh kỹ thuật (Nâng cao): Kích thước đoạn, chồng lấp, giới hạn đoạn, số luồng đồng thời
   [🧪 Chạy thử 1 đoạn đầu]  [▶️ Bắt đầu trích xuất phần đã chọn (Primary)]
   [Đang chạy]: Progress thực tế (done/total) + trạng thái từng đoạn
   [Lỗi từng đoạn]: Cảnh báo danh sách đoạn lỗi + nút [🔄 Chạy lại đoạn gặp lỗi]
3. [Kết quả & Nhật ký Lần xử lý]
   Tóm tắt dễ đọc lần xử lý gần nhất -> ▸ Chi tiết kỹ thuật (Step Traces, Request Hash, Phản hồi JSON gốc)
```

### Bước 4 — Kiểm chứng & Chuẩn hóa (U5)
```text
[4. Rà soát & Chuẩn hóa]
[Banner Đồng bộ SQLite nếu sync_pending] + [Banner Quay lại Phân khu Quan hệ nếu có _curation_return_context]
[6 Thẻ KPI + 3 Phím tắt hành động]
[Radio 3 Phân khu: 1. Chuẩn hóa Danh mục (EDC) | 2. Duyệt Quan hệ & Bằng chứng | 3. Đối tượng & Gộp]

Phân khu 1 (EDC):
  Giữ đủ 2 bảng độc lập (Loại đối tượng + Loại quan hệ). Thanh lọc + Phạm vi chọn ("X đã chọn · trang này / toàn bộ lọc").
  Mở chi tiết 1 đề xuất + Preview/Apply (all_or_nothing / valid_only) + Auto Alignment (gắn nhãn gợi ý AI).

Phân khu 2 (Quan hệ & Bằng chứng):
  Mặc định lọc hàng đợi cần kiểm tra (Chờ duyệt + Cần kiểm tra) kèm badge bộ lọc đang active.
  Bảng danh sách (checkbox lô theo ID) -> Thanh chọn mục xem + [◀️ Mục trước] [Mục tiếp theo ▶️]
  Khung đối chiếu responsive: [Dữ kiện 48%] | [Bằng chứng văn bản gốc highlight 52%] (tự xếp dọc trên màn hình hẹp)
  Thông báo rõ nếu trích dẫn xuất hiện nhiều vị trí (mơ hồ) để người dùng khóa span.
  Ngay dưới bằng chứng: [Ra quyết định Duyệt / Cần kiểm tra / Từ chối (Primary)] -> Tabs phụ: [Sửa dữ kiện] [Lịch sử].

Phân khu 3 (Đối tượng & Gộp):
  2 chế độ (Bảng Hồ sơ | Công cụ Gộp) + Notice học từ điển sau khi gộp.
  Bàn gộp thể hiện rõ: Giữ lại (Target) · Bị gộp (Absorbed) · Số quan hệ chuyển hướng · Bí danh sẽ thêm vào Từ điển.
  Nút xóa nhiều đối tượng yêu cầu xác nhận tác động cụ thể.
```

### Bước 5 — Khám phá, Hỏi đáp & Nghiên cứu (U6)
```text
[5. Khai thác & Xuất dữ liệu]
1. [Nguồn Đồ thị Tường minh]:
   Radio: (Đã được người dùng duyệt) | (Đồ thị thô từ AI — baseline B) | (Nạp Graph từ file)
   Khi chọn Baseline B: Chọn theo Tài liệu -> Đoạn -> Lần xử lý (yêu cầu chọn 1 attempt/đoạn, không tự chọn ngầm).
   Thẻ Trạng thái Nguồn: Tên nguồn · Số đối tượng / quan hệ · Kiểm tra cấu trúc (kèm cảnh báo không đồng nghĩa đúng lịch sử).

2. [Luồng Chức năng Chia Tách Người dùng Phổ thông vs Nghiên cứu]:
   - Tab 1: 🔍 Khám phá & Hỏi đáp (Chế độ Khám phá đơn giản mặc định: Tìm đối tượng/câu hỏi -> Đồ thị con + Bảng quan hệ tương đương hỗ trợ bàn phím + Bằng chứng nguồn; phần tham số PCST/PPR/Alpha & So sánh 3 thuật toán gói gọn trong tùy chọn Nghiên cứu / So sánh)
   - Tab 2: 🔬 Phòng thí nghiệm Nghiên cứu (So sánh 3 thuật toán Side-by-Side, Benchmark Thesis vs Gold độc lập, Sinh Dữ liệu Huấn luyện [khóa khi không phải Approved])
   - Tab 3: 📦 Xuất Dữ liệu & Tích hợp (Ghi rõ giới hạn slider hiển thị KHÔNG cắt dữ liệu xuất; khóa Gói Huấn luyện ZIP 11 tệp & Neo4j khi nguồn là baseline/external)
```
