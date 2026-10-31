# Báo cáo Triển khai: Sửa Lỗi API Key Khi Chuyển Tab & Cấu Hình Lưu Trữ API Key An Toàn

- **Dự án**: Knowledge Graph Studio Pro (`KG_Studio`)
- **Ngày thực hiện**: 31/10/2026
- **Trạng thái**: ✅ **Hoàn thành 100%**
- **Kết quả Kiểm thử**: **70/70 tests pass (100%)** trong 3.5 giây

---

## 1. Phân Tích Nguyên Nhân Gốc Rễ (Root Cause Analysis)

### 1.1. Lỗi Mất Hiệu Lực API Key Khi Chuyển Tab (Tab-Switching Key Loss)
- **Cơ chế xung đột Widget của Streamlit**:
  - Tại thanh bên (`frontend/app.py`), ô nhập API Key sử dụng widget key `key="sb_llm_key"` và gán:
    `st.session_state["llm_api_key"] = st.text_input(..., key="sb_llm_key")`
  - Tại màn hình Bước 2 (`frontend/pages/p02_catalogs_prompts.py`), ô nhập API Key sử dụng widget key `key="p02_llm_key"` và gán:
    `st.session_state["llm_api_key"] = c_key.text_input(..., key="p02_llm_key")`
- **Diễn biến lỗi khi người dùng thao tác**:
  1. Người dùng vào Tab 2 ("2. Thiết lập"), nhập API key của DeepSeek (`sk-...`) vào ô `p02_llm_key`.
  2. Người dùng bấm chuyển sang Tab 3 ("3. Trích xuất") trên thanh điều hướng.
  3. Streamlit kích hoạt script rerun bắt đầu từ file `app.py`.
  4. Vì `sb_llm_key` ở thanh bên chưa từng được người dùng gõ vào, giá trị trong widget state của Streamlit đối với `sb_llm_key` là chuỗi rỗng `""`.
  5. Khi chạy qua dòng 114 của `app.py`, câu lệnh:
     `st.session_state["llm_api_key"] = st.text_input(..., key="sb_llm_key")`
     lập tức **ghi đè chuỗi rỗng `""`** lên `st.session_state["llm_api_key"]`!
  6. Sau đó Tab 3 (`p03_extraction.py`) được render. Khi đọc `api_key = st.session_state.get("llm_api_key", "")`, nó nhận được `""`. Khi bấm "Trích xuất" hoặc "Dry-run", hệ thống báo lỗi: *"Chưa nhập API key"*.
  7. Lỗi tương tự cũng xảy ra nếu người dùng chỉnh sửa Model ID, Base URL, hoặc Token sliders giữa thanh bên và Tab 2.

### 1.2. Vấn Đề Lưu Trữ API Key Thiếu An Toàn & Thiếu Bền Vững
- `config/default.toml` là file cấu hình công khai được quản lý bởi Git, tuyệt đối **không được** lưu plaintext API key của người dùng để tránh rò rỉ mã bí mật lên kho lưu trữ.
- Thư mục gốc `KG_Studio` chưa có file `.gitignore`, dẫn đến rủi ro lộ file secret nếu người dùng tự tạo file cấu hình cá nhân.
- Không có cơ chế nạp key phân cấp (Hierarchical Secret Resolution) để nhận diện tự động từ biến môi trường (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`,...) hoặc file bí mật nội bộ cục bộ.

---

## 2. Kiến Trúc & Giải Pháp Triển Khai

### 2.1. Module Quản Lý Khóa Bí Mật Chuyên Biệt (`shared/secrets_manager.py`)
Tuân thủ nguyên tắc **Clean Architecture** (Tầng `shared` độc lập 100%, không phụ thuộc ngược vào `backend` hay `frontend`):

```
       ┌────────────────────────────────────────────────────────┐
       │   Thứ tự Ưu Tiên Nạp API Key (Hierarchical Loading)     │
       └────────────────────────────────────────────────────────┘
                                   │
      1. Biến Môi Trường Hệ Thống (System Environment Variables)
         ├── DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY / DASHSCOPE_API_KEY
         └── Fallback chung: KG_STUDIO_API_KEY / LLM_API_KEY
                                   │ (nếu rỗng)
                                   ▼
      2. File Bí Mật Cục Bộ (.secrets.toml trong config/.secrets.toml)
         └── Khối [llm_api_keys] (được bảo vệ bởi .gitignore, chmod 0o600)
                                   │ (nếu rỗng)
                                   ▼
      3. File .env Cục Bộ (ở thư mục gốc KG_Studio)
                                   │ (nếu rỗng)
                                   ▼
      4. Streamlit Secrets (st.secrets["llm_api_keys"]) nếu có
```

- **Các hàm cốt lõi**:
  - `get_api_key(provider)`: Tra cứu key theo phân cấp trên cho nhà cung cấp tương ứng.
  - `save_api_key(provider, api_key)`: Ghi nguyên tử (`atomic_write`) vào `config/.secrets.toml`, đặt quyền `0o600` và cập nhật `os.environ` cho tiến trình.
  - `delete_api_key(provider)`: Xóa khóa khỏi `.secrets.toml` và xóa khỏi `os.environ`.
  - `mask_api_key(api_key)`: Che bảo mật hiển thị trên UI (vd: `sk-...1234`).
  - `has_persisted_key(provider)`: Kiểm tra xem đã có key lưu trữ an toàn hay chưa.

### 2.2. Bảo Vệ Tuyệt Đối Bằng `.gitignore`
Tạo file `.gitignore` ở thư mục gốc `D:\DATN\CrawData\KG_Studio`:
- Chặn toàn bộ: `config/.secrets.toml`, `.secrets.*`, `*.secrets.toml`, `.env`, `.env.*`, `.streamlit/secrets.toml`.
- Kết hợp với cơ chế `scrubbed()` đã có trong `shared/text_utils.py` (loại bỏ `SECRET_KEYS = {"api_key", ...}`), đảm bảo API key không bao giờ bị ghi vào `project.json`, graph export hay snapshots.

### 2.3. Giải Quyết Xung Đột Widget Streamlit (State Parity & Sync Callbacks)
Để 2 vị trí nhập dữ liệu (Thanh bên Sidebar và Màn hình Tab 2) không bao giờ ghi đè làm mất dữ liệu của nhau:
1. **Canonical State**: `st.session_state["llm_api_key"]` là nguồn chân lý duy nhất (Single Source of Truth).
2. **Callbacks Đồng Bộ Hai Chiều**:
   - Khi sửa ở thanh bên: `on_sb_llm_key_change()` cập nhật ngay lập tức `llm_api_key` và `p02_llm_key`.
   - Khi sửa ở Tab 2: `on_p02_llm_key_change()` cập nhật ngay lập tức `llm_api_key` và `sb_llm_key`.
3. **Đồng Bộ Trước Khi Render**:
   - Ngay trước khi gọi `st.text_input(..., key="sb_llm_key")` hoặc `p02_llm_key`, gán giá trị widget từ `st.session_state["llm_api_key"]`.
   - Loại bỏ hoàn toàn các lệnh gán đè trực tiếp `st.session_state["llm_api_key"] = st.text_input(...)`.
4. **Tự Động Nạp Key Khi Đổi Nhà Cung Cấp**:
   - Hàm `switch_llm_provider(new_provider)` tự động nạp key tương ứng của nhà cung cấp mới từ `secrets_manager`, thiết lập Model ID, Base URL và khuyến nghị ngân sách Token tương ứng.

### 2.4. Trải Nghiệm Người Dùng (UI/UX)
- **Tại Tab 2 (Thiết lập)**:
  - Hiển thị badge trạng thái khóa:
    - *Đã lưu an toàn*: `🔒 Khóa đã lưu an toàn: sk-...1234 (trong config/.secrets.toml hoặc biến môi trường)`.
    - *Khóa phiên*: `ℹ️ Khóa chỉ tạm thời trong phiên. Bấm 'Lưu API Key an toàn' bên dưới để lưu bền vững.`
    - *Chưa có*: `⚠️ Chưa có API Key. Bắt buộc đối với DeepSeek, OpenAI, Claude, Qwen.`
  - Thêm nút **🔑 Lưu API Key an toàn** (lưu vào `.secrets.toml`).
  - Thêm nút **🗑️ Xóa API Key đã lưu** (xóa khỏi `.secrets.toml` và phiên).
- **Tại Tab 3 (Trích xuất)**:
  - Tự động fallback: nếu trong session chưa có, tự động nạp từ `get_api_key(provider)`.
  - Kiểm tra trước khi trích xuất (cả nút *Chạy thử Dry-run* lẫn *Bắt đầu trích xuất*): nếu thiếu API key thì hiển thị thông báo lỗi thân thiện bằng tiếng Việt kèm hướng dẫn nhập, không làm crash ứng dụng.

---

## 3. Danh Sách Tệp Thay Đổi

| Tệp | Hành động | Mục đích |
|---|---|---|
| `shared/secrets_manager.py` | Tạo mới | Quản lý nạp/lưu/xóa/che API key an toàn theo phân cấp ưu tiên |
| `.gitignore` | Tạo mới | Bảo vệ `config/.secrets.toml`, `.env`, Streamlit secrets không bị lọt vào Git |
| `shared/__init__.py` | Cập nhật | Xuất khẩu các hàm secrets manager |
| `backend/integrations/llm/providers.py` | Cập nhật | Hỗ trợ tìm kiếm provider linh hoạt cả theo display name lẫn short key |
| `frontend/state/session.py` | Cập nhật | Nạp API key mặc định từ secrets, các hàm callback đồng bộ 2 chiều và `switch_llm_provider` |
| `frontend/app.py` | Cập nhật | Áp dụng callbacks cho sidebar widgets, thêm nút Lưu/Xóa key, hiển thị badge |
| `frontend/pages/p02_catalogs_prompts.py` | Cập nhật | Áp dụng callbacks cho Tab 2, nút Lưu/Xóa key an toàn và badge bảo mật |
| `frontend/pages/p03_extraction.py` | Cập nhật | Fallback tự động nạp API key an toàn và kiểm tra bảo vệ trước khi chạy trích xuất |
| `backend/facade.py` | Cập nhật | `test_llm` tự động fallback sang `get_api_key` nếu tham số đầu vào rỗng |
| `tests/test_secrets_manager.py` | Tạo mới | 8 bài unit test chuyên sâu kiểm tra an toàn, phân cấp env và Streamlit AppTest chuyển tab |

---

## 4. Kết Quả Kiểm Thử (Verification)

Toàn bộ test suite gồm **70 bài kiểm tra** đều vượt qua thành công 100%:

```text
Ran 70 tests in 3.579s
OK
```

Các ca kiểm thử tiêu biểu cho tính năng mới:
1. `test_save_and_read_api_key_atomic`: Lưu nguyên tử vào `.secrets.toml` và đọc lại chính xác.
2. `test_env_var_priority_over_file`: Biến môi trường hệ thống (`DEEPSEEK_API_KEY`) được ưu tiên cao hơn file bí mật; khi xóa biến môi trường hệ thống tự động fallback về file.
3. `test_delete_api_key`: Xóa key khỏi `.secrets.toml` và dọn dẹp biến môi trường.
4. `test_mask_api_key`: Che giấu key bảo mật đúng chuẩn hiển thị.
5. `test_gitignore_protects_secrets`: Xác minh `.gitignore` bảo vệ `config/.secrets.toml`, `.env`, `.streamlit/secrets.toml`.
6. `test_tab_switching_state_persistence_unit`: Mô phỏng vòng đời unmount/remount giữa các tab đảm bảo key không bị reset.
7. `test_apptest_tab_switching_key_retention`: Sử dụng `streamlit.testing.v1.AppTest` mô phỏng chuyển Tab 1 -> Tab 2 (nhập key) -> Tab 3 (trích xuất) -> Tab 2 -> Tab 1, chứng minh API key được bảo toàn 100% không bị mất.

