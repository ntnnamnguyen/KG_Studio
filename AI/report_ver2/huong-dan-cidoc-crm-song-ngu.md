# Hướng Dẫn Sử Dụng KG Studio Phiên Bản CIDOC CRM Song Ngữ (Việt – CIDOC)

**Cập nhật:** 2026-11-14 (Áp dụng sau đợt nâng cấp & sửa lỗi P0 + P1)  
**Đối tượng sử dụng:** Người nghiên cứu di sản văn hóa, lịch sử, lưu trữ và người làm đồ thị tri thức (KG) bằng tiếng Việt cần chuẩn hóa dữ liệu theo chuẩn quốc tế **ISO 21127 / CIDOC CRM v7.1.3** mà không làm mất câu trích dẫn nguyên văn tiếng Việt.

---

## 1. Tư Duy Thiết Kế: "CIDOC CRM Song Ngữ" Hoạt Động Như Thế Nào?

Trong KG Studio, cấu hình CIDOC CRM song ngữ kết hợp hai ưu điểm đồng thời:
1. **Tên chuẩn (Schema Canonical Name) theo CIDOC CRM quốc tế:**
   - **Loại thực thể (`entity_types.name`):** dùng mã lớp chuẩn CIDOC CRM nối bằng dấu `_` hoặc `-`, ví dụ `E22_Human-Made_Object`, `E53_Place`, `E52_Time-Span`, `E21_Person`, `E74_Group`, `E5_Event`, `E12_Production`.
   - **Quan hệ (`relations.name`):** dùng mã thuộc tính chuẩn CIDOC CRM, ví dụ `P53_has_former_or_current_location`, `P4_has_time-span`, `P7_took_place_at`, `P14_carried_out_by`, `P45_consists_of`, `P108_has_produced`.
2. **Ngữ nghĩa, từ đồng nghĩa & bằng chứng bằng tiếng Việt:**
   - `description` (mô tả ngắn), `definition` (định nghĩa phạm vi) và `aliases` (từ đồng nghĩa tiếng Việt như `tọa lạc tại; nằm tại; đặt tại; ở địa điểm`) đều viết bằng tiếng Việt.
   - Tên thực thể cụ thể trong văn bản (`Chùa Một Cột`, `Thăng Long`, `năm 1049`) và câu trích dẫn bằng chứng (`trich_dan`) luôn giữ **nguyên văn tiếng Việt**.
3. **Các cải tiến nền tảng đã tích hợp (P0 + P1):**
   - **Thông tin `[Domain -> Range]` và `Aliases` chạy xuyên suốt từ CSV/JSON tới Prompt & Vector (`CR-01`, `HI-05`):** [shared/catalog_utils.py](file:///d:/DATN/CrawData/KG_Studio/shared/catalog_utils.py) giữ đầy đủ `domain`, `range`, `aliases`; [shared/prompt_templates/__init__.py](file:///d:/DATN/CrawData/KG_Studio/shared/prompt_templates/__init__.py) gắn `Scope: {domain} -> {range}` vào từng passage (`PASSAGE_TEMPLATE_VERSION = "v2-domain-range"`).
   - **Không ép sai template E5 lên BGE-M3 (`HI-05`):** `should_use_e5_instruct("ollama:bge-m3")` tự động tắt tiền tố `"Instruct: ... Query: ..."` kiểu E5, trong khi vẫn giữ cho model họ E5 và `hybrid_vn:default`.
   - **Target Alignment kiểm tra chiều `[Domain -> Range]` & an toàn khi Verifier lỗi (`CR-08`):** [TargetAligner](file:///d:/DATN/CrawData/KG_Studio/backend/domain/schema_intelligence/aligner.py) căn chỉnh `entity_types` trước rồi suy ngược bối cảnh `[Domain -> Range]` sang `relations`; LLM Verifier lỗi/trả lời mơ hồ sẽ **fail-closed** (giữ `pending`, không tự gộp sai).
   - **GraphRAG đọc mượt nhãn CIDOC có dấu `_` (`HI-08`):** [g_retriever.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/graph/g_retriever.py) tách từ khóa qua dấu gạch dưới/gạch nối (`_`, `-`) và nhận diện thuộc tính CIDOC (`P4_has_time-span`, `P53_has_former_or_current_location`, `P45_consists_of`, v.v.).

---

## 2. Bộ Tệp Danh Mục Mẫu & Định Dạng Chuẩn CSV / JSON

### 2.1. Dùng ngay bộ mẫu song ngữ đi kèm
Hệ thống đã tạo sẵn bộ danh mục CIDOC CRM song ngữ mẫu (đã kiểm chứng round-trip CSV/JSON và retrieval `ollama:bge-m3`) trong thư mục [cidoc_starter](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/cidoc_starter):
- **Loại thực thể (30 lớp CIDOC CRM):**
  - [cidoc_entity_types.csv](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/cidoc_starter/cidoc_entity_types.csv)
  - [cidoc_entity_types.json](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/cidoc_starter/cidoc_entity_types.json)
- **Quan hệ (55 thuộc tính CIDOC CRM kèm `domain`, `range`, `aliases`):**
  - [cidoc_relations.csv](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/cidoc_starter/cidoc_relations.csv)
  - [cidoc_relations.json](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/cidoc_starter/cidoc_relations.json)

### 2.2. Quy cách khi tự soạn file danh mục mới
- **Định dạng CSV (UTF-8 / mở được trực tiếp trong Excel với UTF-8 BOM):**
  - File `entity_types.csv`: bắt buộc có cột `name`, khuyến nghị đầy đủ 3 cột `name,description,definition`.
  - File `relations.csv`: bắt buộc có `name`, khuyến nghị đầy đủ 6 cột:
    ```text
    name,description,definition,domain,range,aliases
    ```
  - Trong cột `aliases` của CSV, ngăn cách nhiều cụm từ đồng nghĩa tiếng Việt bằng **dấu chấm phẩy `;`** hoặc **`|`** (ví dụ: `tọa lạc tại; nằm tại; đặt tại; ở địa điểm`). Tránh dùng dấu `,` làm dấu tách chính trong `aliases` nếu cụm mô tả có dấu phẩy.
- **Định dạng JSON:**
  - `entity_types`: `{"schema_version": 2, "entity_types": [{"name": "E22_Human-Made_Object", "description": "...", "definition": "..."}]}`
  - `relations`: `{"schema_version": 2, "relations": [{"name": "P53_has_former_or_current_location", "description": "...", "definition": "...", "domain": "E18_Physical_Thing", "range": "E53_Place", "aliases": ["tọa lạc tại", "nằm tại"]}]}`

---

## 3. Chuẩn Bị Mô Hình & Khởi Động Ứng Dụng

### 3.1. Cài mô hình đa ngôn ngữ trên Ollama (khuyến nghị mạnh cho song ngữ)
Vì nhãn CIDOC (`P53_has_former_or_current_location`) là tiếng Anh còn văn bản/định nghĩa là tiếng Việt, mô hình nhúng mặc định `hybrid_vn:default` phụ thuộc nhiều vào từ khóa tiếng Việt trong `definition`/`aliases`, còn **BAAI BGE-M3** hỗ trợ ngữ nghĩa chéo ngôn ngữ Anh–Việt tốt hơn. Hãy cài qua terminal:

```powershell
ollama pull bge-m3
ollama pull qwen3.5:4b   # Nếu muốn chạy LLM Verifier / Hỏi đáp cục bộ không tốn chi phí API
```

### 3.2. Khởi động KG Studio
Từ thư mục gốc dự án `d:\DATN\CrawData\KG_Studio`:

```powershell
& .\.venv-win\Scripts\python.exe -m streamlit run app.py
```

Trình duyệt sẽ mở ứng dụng tại địa chỉ mặc định `http://localhost:8502` (theo [config/default.toml](file:///d:/DATN/CrawData/KG_Studio/config/default.toml#L22-L25)).

---

## 4. Quy Trình Thực Hành 5 Bước Trên Giao Diện

### Bước 1 (`1. Tài liệu`): Tạo dự án & Nạp tư liệu nguồn
1. Ở thanh bên trái (Sidebar), tạo dự án mới (ví dụ `DiSan_CIDOC_v1`) hoặc chọn dự án hiện có.
2. Tại màn hình `📄 1. Tư liệu Nguồn`, mở `📥 Bước A — Chọn tệp văn bản từ máy tính` và chọn các tệp `.txt`, `.docx` hoặc `.pdf` chứa lớp văn bản sạch.
   - **Lưu ý encoding `.txt`:** Nên lưu tệp `.txt` ở chuẩn **UTF-8** trước khi tải lên (hệ thống hiện vẫn còn nợ kỹ thuật `MD-06` với tệp `.txt` mã hóa Windows CP1258 cũ).
3. (Tùy chọn) Mở `🏷️ Nhãn nguồn & phạm vi tư liệu (tùy chọn)` để điền `Phạm vi địa lý / tên di tích` và `Nhãn nguồn tư liệu`.
4. Bấm nút **`📥 Bước B — Đọc & thêm các tệp đã chọn vào dự án`** để lưu tư liệu xuống dự án.

---

### Bước 2 (`2. Thiết lập`): Kết nối AI, Phương pháp `EDC + R`, Prompt & Danh mục CIDOC

Mở mục `⚙️ 2. Thiết lập Kết nối, Phương pháp & Danh mục`. Đây là **điểm cấu hình duy nhất** (SSOT):

#### 4.1. Cấu hình Kết nối LLM (`🤖 1. Kết nối Mô hình AI`)
- **Nhà cung cấp LLM:** chọn `DeepSeek` (khuyến nghị khi trích xuất hàng loạt) hoặc `Ollama (Local)` (chạy cục bộ miễn phí với `qwen3.5:4b` / `qwen3.5:latest`).
- **API Base URL:**
  - Nếu chọn `Ollama (Local)`, giữ nguyên `http://localhost:11434/v1` và để trống ô **API Key (để trống nếu dùng Ollama cục bộ)**.
- **Thanh trượt Token (rất quan trọng cho Ollama):**
  - Mặc định trong `config/default.toml`, Ollama đặt `max_input_tokens = 4096`. Khi dùng CIDOC song ngữ kèm Top-K quan hệ `20–30` kèm `definition` + `[Domain -> Range]`, nên kéo **`📥 Token đầu vào tối đa (Input Tokens)`** lên **`8,192 – 16,384`** và **`📤 Token đầu ra tối đa (Output Tokens / max_tokens)`** từ **`4,096`** trở lên.
- Bấm **`🔌 Kiểm tra kết nối`** để xác nhận xanh, sau đó bấm **`💾 Lưu cấu hình mặc định`** nếu muốn giữ cho các lần mở sau.

#### 4.2. Kích hoạt phương pháp `EDC + R` và Nạp Prompt Song Ngữ (`📐 2. Chọn Phương pháp Trích xuất`)
1. Ở hàng radio chọn phương pháp, bấm chọn:  
   **`3. EDC + R — Truy xuất quan hệ & Chuẩn hóa tự động`**
2. **Quan trọng:** Nhìn sang cột bên phải, bấm nút **`🎯 Áp dụng phương pháp này cho Dự án`** cho đến khi thấy thẻ xanh `✅ Đang áp dụng: edc_plus_r`. (Nếu chỉ bấm radio mà không bấm nút Áp dụng, hệ thống vẫn chạy chế độ cũ).
3. Trong khung **`✍️ Hướng dẫn Trích xuất (Prompt cho edc_plus_r)`**:
   - **Cảnh báo:** Tránh câu lệnh *"Tất cả tên loại thực thể, tên quan hệ đều bằng tiếng Việt"* của bộ prompt `closed` cũ vì sẽ khiến LLM bỏ qua các mã chuẩn tiếng Anh `E22_Human-Made_Object` hay `P53_has_former_or_current_location`.
   - Khuyến nghị dán đoạn **Hướng dẫn Trích xuất CIDOC Song ngữ chuẩn** sau vào ô `Nội dung Hướng dẫn Trích xuất (Base Instructions)`:

```text
Trích xuất tri thức từ đoạn tài liệu tiếng Việt theo chuẩn CIDOC CRM song ngữ.
1. Giữ nguyên văn tiếng Việt cho tên thực thể cụ thể (ten), mô tả ngữ cảnh (mo_ta) và câu trích dẫn bằng chứng (trich_dan). Trích dẫn phải là đoạn liên tục nguyên văn, không dùng "..." để lược bớt.
2. Về Loại thực thể (loai) và Tên quan hệ (quan_he): ƯU TIÊN DÙNG NGUYÊN VĂN MÃ CHUẨN CIDOC CRM (dạng E*_... hoặc P*_...) được cung cấp trong khối "GỢI Ý QUAN HỆ CHUẨN" và "GỢI Ý LOẠI THỰC THỂ CHUẨN".
3. Tuân thủ nghiêm ngặt chiều [Domain -> Range] ghi kèm theo từng quan hệ CIDOC. Ví dụ: dùng P53_has_former_or_current_location cho công trình/vật thể [E18_Physical_Thing -> E53_Place], dùng P7_took_place_at cho sự kiện [E4_Period / E5_Event -> E53_Place], dùng P4_has_time-span cho mốc thời gian [E2_Temporal_Entity -> E52_Time-Span].
4. Chỉ tự đề xuất tên loại thực thể hoặc quan hệ tiếng Việt mới (kèm định nghĩa rõ chiều nguồn -> đích) khi hoàn toàn không có mã CIDOC nào phù hợp trong danh sách gợi ý.
5. Mọi thực thể nguồn (nguon) và đích (dich) trong quan_he phải có mặt trong danh sách thuc_the, bao gồm cả mốc thời gian và số đo. Không suy đoán thông tin ngoài văn bản.
```

4. Điền ghi chú (ví dụ `Prompt chuan CIDOC song ngu v1`) và bấm **`💾 Lưu phiên bản mới`**. Bảo đảm thấy trạng thái **`🔒 Đang pin: v...`**.

#### 4.3. Tinh chỉnh tham số `⚙️ Cấu hình Schema Retriever (+R) & Target Alignment`
Mở khối cấu hình EDC+R trong Bước 2 và thiết lập các thông số khuyến nghị cho CIDOC song ngữ:

| Thông số trên giao diện | Phạm vi UI | Giá trị khuyến nghị cho CIDOC song ngữ | Lý do thực nghiệm |
| --- | --- | --- | --- |
| **Mô hình Embedding (Model Registry)** | Dropdown | `ollama:bge-m3` | Hiểu đồng thời định nghĩa tiếng Việt & mã/tên tiếng Anh `E*/P*` (`Recall@5 = 0.95`, `Recall@15 = 1.00`, `MRR = 0.7625` với 20 truy vấn mẫu trong thực nghiệm). |
| **Số vòng lặp Tinh chỉnh** | `1`, `2`, `3` | `1` (mặc định) hoặc `2` | `1` chạy nhanh ổn định; đặt `2` khi văn bản dài nhiều quan hệ phức tạp, chấp nhận tốn gấp đôi lượt gọi LLM mỗi đoạn. |
| **Top-K Quan hệ (+R)** | `3 .. 80` | **`20 – 30`** | Danh mục CIDOC thường có 50–80 thuộc tính; để `10` dễ rớt quan hệ phụ như `P43_has_dimension`, `P72_has_language`. Ở `K=15..30`, thực nghiệm đạt `Recall = 1.00`. |
| **Top-K Loại thực thể (+R)** | `3 .. 50` | **`12 – 15`** | Bao phủ tốt phần lớn trong 30 lớp CIDOC hay gặp. |
| **Ngưỡng Tự động Chuẩn hóa** (`auto_align_threshold`) | `0.50 .. 0.99` | **`0.86` (Thận trọng)** hoặc **`0.72 – 0.75` (Bán tự động)** | Xem lưu ý quan trọng ở Hộp bên dưới! |
| **Ngưỡng Gợi ý Ứng viên** (`candidate_threshold`) | `0.20 .. 0.90` | **`0.40 – 0.45`** | Điểm cosine chéo ngôn ngữ của `bge-m3` cho cặp đúng tiếng Việt ↔ tiếng Anh CIDOC thường nằm khoảng `0.55 – 0.78`, nên ngưỡng gợi ý không nên đặt cao hơn `0.45`. |
| **Bật LLM xác thực lại ứng viên Target Alignment** | Checkbox | **Bật (Tick chọn)** | Cho phép LLM Verifier (`qwen3.5:4b` hoặc DeepSeek) phân biệt cặp gần nghĩa như `P53` (vị trí công trình) vs `P7` (nơi diễn ra sự kiện) dựa theo `[Domain -> Range]`. |

> **⚠️ LƯU Ý QUAN TRỌNG VỀ NGƯỠNG `auto_align_threshold` KHI DÙNG SONG NGỮ:**  
> Thực nghiệm đo với `ollama:bge-m3` cho thấy ngay cả các cặp đồng nghĩa chính xác giữa tiếng Việt và mã tiếng Anh CIDOC (`"Vật liệu xây dựng"` → `E57_Material`: `0.7756`; `"tổ chức ở nơi"` → `P7_took_place_at`: `0.7445`; `"đóng tại địa bàn"` → `P53_has_former_or_current_location`: `0.7238`) đều có điểm cosine **dưới mức mặc định `0.86`**.  
> - Nếu giữ **`0.86` (khuyến nghị khi làm dữ liệu chuẩn nghiên cứu):** `TargetAligner` vẫn chạy Verifier để xếp hạng ứng viên chuẩn (`llm_verified_candidates`), nhưng **giữ an toàn ở trạng thái `pending`** (`suggested_for_review`) để bạn duyệt một lượt trước khi gộp.  
> - Nếu muốn tự động gộp ngay các cặp vượt kiểm tra Verifier: chỉnh thanh trượt về **`0.72 – 0.75`** kết hợp **bật LLM Verifier**, sau đó kiểm tra lại trong Phân khu 1 của Bước 4.

Bấm **`💾 Lưu Cấu hình Tham số EDC+R`** ngay sau khi điều chỉnh.

#### 4.4. Nạp 3 Tab Danh Mục & Lưu Giao Dịch (`💾 Lưu Toàn bộ Thay đổi Danh mục`)
1. Chuyển sang tab **`🏷️ Loại thực thể / Đối tượng`**:
   - Tải lên `cidoc_entity_types.csv` (hoặc `.json`), bấm **`⚡ Nạp đè toàn bộ`** (hoặc **`➕ Gộp thêm vào mục cũ`** nếu muốn giữ loại thực thể sẵn có).
2. Chuyển sang tab **`🔗 Loại quan hệ`**:
   - Tải lên `cidoc_relations.csv` (hoặc `.json`), bấm **`⚡ Nạp đè toàn bộ`**.
   - Kiểm tra bảng hiển thị bên dưới có đủ 5 cột: `name`, `description`, `definition`, `domain`, `range` (cùng `aliases` bảo toàn ở backend/JSON).
3. Chuyển sang tab **`📚 Từ điển Bí danh & Địa danh`**:
   - Khai báo các cặp tên biến thể địa danh/di tích đồng nhất trong bộ tài liệu của bạn (ví dụ `Thăng Long` → `Hà Nội`, `Văn Miếu` → `Văn Miếu Quốc Tử Giám`).
4. Cuối cùng, bấm **`💾 Lưu Toàn bộ Thay đổi Danh mục`**. Sau đợt vá `CR-06`, thao tác lưu danh mục + từ điển đi qua một vòng đồng bộ revision an toàn, không còn lỗi `"revision mismatch"` giả.

---

### Bước 3 (`3. Trích xuất`): Chạy Thử 1 Đoạn Mẫu & Trích Xuất Song Song

1. Kiểm tra thẻ **`🤖 Kết nối AI & Phương pháp đang áp dụng`** ở đầu trang phải ghi **`edc_plus_r`** và đúng model bạn vừa cấu hình.
2. Mở **`⚙️ Tùy chỉnh kỹ thuật (Phân đoạn & Đa luồng)`**:
   - **Kích thước đoạn (ký tự):** `2,200 – 3,200` (để chừa ngân sách input token cho khối gợi ý Top-K CIDOC vốn dài hơn danh mục thường).
   - **Độ chồng lấp (ký tự):** `50 – 150`.
   - **Số luồng gọi API đồng thời (Concurrent Threads):**
     - Dùng **Ollama local** (`qwen3.5:4b`, `bge-m3`): chỉ nên đặt **`1 – 2` luồng** để tránh nghẽn VRAM GPU hoặc swap model liên tục giữa LLM và Embedder.
     - Dùng **DeepSeek / OpenAI API**: đặt **`3 – 5` luồng**.
3. **Bắt buộc kiểm tra thử bằng nút `🧪 Chạy thử 1 đoạn mẫu (Dry-run)`** trước khi chạy hàng loạt:
   - Sau khi chạy xong 1 đoạn, cuộn xuống **`📜 Nhật ký Trích xuất`** -> mở mục **`👁️ Nội dung Request Thực tế đã Gửi tới LLM trong Lượt này`** -> tab **`User Message Đã gửi`**.
   - Xác nhận bạn nhìn thấy dòng dạng:
     ```text
     - P53_has_former_or_current_location [E18_Physical_Thing -> E53_Place] (từ đồng nghĩa/biến thể: tọa lạc tại, nằm tại, đặt tại, ở địa điểm): ...
     ```
     Nếu thấy đúng dòng này kèm định nghĩa tiếng Việt, hệ thống `v2-domain-range` + `SchemaRetriever` đang hoạt động chuẩn xác!
4. Bấm **`▶️ Bắt đầu trích xuất phần đã chọn (... luồng)`** để chạy toàn bộ tài liệu đã chọn. Nếu có đoạn lỗi, hệ thống vẫn giữ nguyên metadata lượt lỗi (`status="error"`, token lỗi, đã che khóa API bí mật) và không đánh dấu hoàn tất để bạn chạy lại riêng đoạn lỗi sau.

---

### Bước 4 (`4. Rà soát`): Chuẩn Hóa Đề Xuất Mở & Kiểm Duyệt Tri Thức

Mở **`🎯 4. Rà soát & Chuẩn hóa Tri thức (Knowledge Curation Hub)`** gồm 3 phân khu:

#### 4.5. Phân khu 1: `📐 1. Chuẩn hóa Lược đồ (Schema EDC)`
Nếu LLM có sinh thêm đề xuất mở ngoài bộ CIDOC (ví dụ đề xuất `"nằm trên đảo"` hay `"Công trình tôn giáo"`):
1. Mở **`🤖 Công cụ Chuẩn hóa Tự động (Auto Target Alignment — Không tính là nhãn con người)`**.
2. **Luôn chạy theo đúng thứ tự 2 bước** (hoặc chọn cả loại + quan hệ):
   - Đầu tiên: chọn các đề xuất loại thực thể -> bấm **`🤖 Chạy chuẩn hóa tự động cho ... Loại thực thể đã chọn`** (hoặc xem và ghép thủ công về `E22_Human-Made_Object`, `E53_Place`, v.v.).
   - Thứ hai: chọn các đề xuất quan hệ -> bấm **`🤖 Chạy chuẩn hóa tự động cho ... Quan hệ đã chọn`**. Khi các loại thực thể ở thực thể nguồn/đích đã rõ, Verifier sẽ tận dụng được ngữ cảnh `[E* -> E*]` để phân biệt chính xác hơn `P53` vs `P7`.
3. Ở bảng duyệt hai miền (Loại thực thể & Quan hệ), sử dụng các nút hỗ trợ:
   - `🎯 Làm mới gợi ý cho mục đã chọn (...)`
   - `⚡ Điền ứng viên đầu tiên vào bản nháp (...)`
   - `⚡ Hợp nhất ngay theo Top-1 (... mục)` (hoặc chỉnh từng mục trong ngăn chi tiết để tránh ghép nhầm).
   - **Lưu ý quy trình khoa học:** Các mục có `decision_origin = auto_align` không được coi là nhãn vàng của con người nếu bạn chưa rà soát xác nhận lại.

#### 4.6. Phân khu 2 (`🔬 2. Duyệt Quan hệ & Bằng chứng`) & Phân khu 3 (`🏛️ 3. Quản lý & Gộp thực thể`)
1. Xử lý các cạnh đang báo `⛔ Vướng danh mục` bằng cách bấm chuyển sang Phân khu 1 và dùng nút `↩️ Quay lại mục đang kiểm duyệt ở Phân khu Quan hệ` sau khi xử lý xong đề xuất chặn.
2. Đối chiếu hai cột văn bản gốc – câu trích dẫn để phê duyệt (`Đã duyệt`) hoặc loại bỏ (`Loại bỏ`) các cạnh sai bằng chứng.
3. Trong Phân khu 3, khi quét cặp nghi trùng lặp và thực hiện **Gộp thực thể** (hoặc **Gộp loại thực thể**):
   - Bí danh của thực thể bị gộp sẽ tự động được làm giàu vào `Từ điển Bí danh`.
   - Mọi cạnh `Đã duyệt` gắn với thực thể bị thay đổi loại (`kind`) hay bị biến thành self-loop sẽ **tự động hạ về trạng thái `Cần kiểm tra`** (`CR-04`/`HI-06`), bảo đảm đồ thị không bao giờ giữ cạnh đã duyệt trái ràng buộc sau khi sửa node.
   - Các cặp bạn đã bấm *"Không trùng lặp"* sẽ được loại ngay khỏi bộ đếm chỉ số dù đang bật cache.

---

### Bước 5 (`5. Khai thác`): G-Retriever GraphRAG, Xuất Tập Huấn Luyện & Neo4j

Mở **`🕸️ 5. Khai thác Đồ thị Tri thức (G-Retriever & GraphRAG) & Xuất Dữ liệu`**:
1. **Chọn nguồn đồ thị rõ ràng ở đầu trang:**
   - Mặc định nên chọn **`🟢 ĐỒ THỊ ĐÃ ĐƯỢC NGƯỜI DÙNG KIỂM DUYỆT (Approved KG)`**. Hệ thống tuân thủ nguyên tắc fail-closed (`CR-07`): nếu chưa có cạnh nào ở trạng thái `Đã duyệt`, đồ thị trả về **0 cạnh** (không âm thầm rơi xuống cạnh chưa duyệt).
   - Khi làm thí nghiệm đối chứng khoa học với Baseline B, chọn **`🟡 ĐỒ THỊ THÔ TỪ AI — CHƯA QUA KIỂM DUYỆT (Baseline B)`**.
2. **Tab `🔍 1. Khám phá & Hỏi đáp (G-Retriever)`:**
   - Bạn có thể hỏi trực tiếp bằng tiếng Việt tự nhiên (ví dụ: *"82 bia Tiến sĩ tại Văn Miếu làm từ chất liệu gì và do triều đại nào dựng?"*). Engine tự tách token qua dấu `_` của `P45_consists_of`, `P4_has_time-span`, `P53_has_former_or_current_location` và dùng PCST/PPR truy xuất đồ thị con liên thông gửi LLM trả lời kèm trích dẫn cạnh.
3. **Tab `🧪 3. Nghiên cứu: Đối sánh Thuật toán (Benchmark)` & `🧬 4. Nghiên cứu: Sinh Dữ liệu Huấn luyện (QA Studio)`:**
   - Khi sinh bộ `train / val / test` cho thí nghiệm G-Retriever (`QA Studio`), mặc định `disjoint_split=True` phân cụm các bộ ba liên thông trước khi chia tập để bảo đảm **0 cạnh rò rỉ chéo giữa Train, Val và Test** (`HI-08`).
   - Lưu ý nhỏ UI (nợ `MD` từ bảng audit): tab `QA Studio` hiện có thể tự kích hoạt sinh mẫu mặc định ngay lần đầu mở tab trên project mới nếu chưa sửa tách nút ở đợt P2.
4. **Tab `📦 2. Bản đồ, Bảng Quan hệ & Xuất tệp` & Neo4j:**
   - Bấm **`🔨 Chuẩn bị Gói Sao lưu ZIP Đầy đủ (JSON + CSV + QA)`** để xuất trọn bộ 11 tệp (gồm PyG CSV và `train/val/test.jsonl`).
   - Mở **`🗄️ Tích hợp Cơ sở dữ liệu Đồ thị Neo4j (Tùy chọn nâng cao)`**, kiểm tra kết nối và bấm **`🚀 Đồng bộ Đồ thị Đã duyệt lên Neo4j`**. Bản sửa `HI-07` chỉ ghi các cạnh đã duyệt đạt chuẩn `is_edge_exportable` (chứng từ & schema hợp lệ), lưu đúng thuộc tính `trang_thai` và dùng khóa duy nhất `n.uid = f"{project_id}::{id}"` nên đồng bộ nhiều dự án CIDOC khác nhau trên cùng 1 instance Neo4j không còn ghi đè nhau.

---

## 5. Xử Lý Sự Cố Thường Gặp Khi Vận Hành Song Ngữ

| Triệu chứng gặp phải | Nguyên nhân & Cách xử lý nhanh |
| --- | --- |
| Tải JSON/CSV quan hệ có cột `domain`/`range` báo lỗi | Kiểm tra file xem có thừa khoảng trắng ở tên cột header hay thiếu cột bắt buộc `name` không. Từ bản P0 `CR-01`, `domain`, `range` (`OPTIONAL_CATALOG_FIELDS`) và `aliases` đã được `validate_catalog()` hỗ trợ đầy đủ cả CSV và JSON. |
| Auto Target Alignment gộp nhầm hoặc giữ `pending` hàng loạt dù đã bật LLM Verifier | Kiểm tra 3 điểm ở Bước 2: (1) Đã chọn `ollama:bge-m3` chưa; (2) `Ngưỡng Gợi ý Ứng viên` có bị đặt quá cao (`> 0.50`) làm rớt ứng viên trước khi tới Verifier không; (3) Nếu dùng ngưỡng mặc định `0.86`, hệ thống cố ý giữ ở hàng `pending` (`suggested_for_review`) kèm `llm_verified_candidates` để bạn duyệt an toàn. Hạ về `0.72–0.75` nếu muốn gộp bán tự động. |
| LLM tự đề xuất quan hệ tiếng Việt thay vì chọn mã `P*_...` CIDOC | Kiểm tra **Prompt** ở Bước 2 xem còn câu ép *"tên quan hệ đều bằng tiếng Việt"* không; nâng **`Top-K Quan hệ (+R)`** từ `10` lên `20–30`; tăng `Input Tokens` của Ollama lên `8192+` để prompt không cắt cụt danh sách quan hệ. |
| Bước 5 báo đồ thị 0 cạnh dù đã trích xuất xong nhiều lượt | Vì đồ thị `Approved KG` chỉ hiển thị cạnh đã được duyệt ở Bước 4 (`CR-07`: không còn fallback sang cạnh `Chờ duyệt`). Hãy sang Bước 4 rà soát/duyệt cạnh (hoặc chuyển sang nguồn `Baseline B` nếu muốn đánh giá đồ thị thô chưa duyệt). |
| Báo `Ollama timeout` hoặc trích xuất đa luồng chậm trên máy GPU cá nhân | Khi chạy đồng thời cả `qwen3.5:4b` và `bge-m3` trên GPU VRAM nhỏ (6–8 GB), Ollama có thể phải nạp đi nạp lại giữa hai model nếu chạy nhiều luồng. Giảm **`Số luồng gọi API đồng thời`** ở Bước 3 về `1` hoặc `2`, hoặc dùng LLM trích xuất qua API (`DeepSeek`) và giữ `bge-m3` ở Ollama local. |
