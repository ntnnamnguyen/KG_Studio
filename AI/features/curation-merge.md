# Plan: Kiểm duyệt dữ kiện và gộp thực thể

- **Trạng thái:** Thiết kế để triển khai; chưa thay đổi giao diện hoặc mã nguồn.
- **Phạm vi:** Trang **5. Kiểm duyệt & Gộp thực thể** của `KG_Studio Pro`.
- **Căn cứ:** [Kiến trúc hệ thống](../structure.md) và [plan trang 4 — Duyệt EDC hàng loạt](edc-bulk-review.md).
- **Mục tiêu:** Giao diện gọn, phân vùng rõ, thao tác đơn và nhiều mục nhất quán; mọi quyết định truy ngược được về dữ liệu và bằng chứng.

## 1. Phân định trách nhiệm với trang 4

| Khu vực | Đối tượng xử lý | Quyết định của người dùng |
| --- | --- | --- |
| Trang 4 — Đề xuất loại thực thể | Loại như `Công trình`, `Nhân vật` | Duyệt vào danh mục, hợp nhất loại, từ chối đề xuất |
| Trang 4 — Đề xuất quan hệ | Nhãn như `được_xây_dựng_vào` | Duyệt vào danh mục, hợp nhất nhãn, từ chối đề xuất |
| Trang 5 — Quan hệ & bằng chứng | Dữ kiện cụ thể: A — quan hệ → B, kèm nguồn | Xác nhận dữ kiện, sửa, yêu cầu kiểm tra lại, loại bỏ |
| Trang 5 — Thực thể | Đối tượng cụ thể như `Cột cờ Hà Nội` | Sửa hồ sơ, đối chiếu nguồn, xem quan hệ liên quan |
| Trang 5 — Gộp thực thể | Hai hoặc nhiều node cùng chỉ một đối tượng | Chọn node giữ lại, giải quyết xung đột, hợp nhất có lịch sử |

**Duyệt danh mục không đồng nghĩa duyệt dữ kiện.** Hai tên loại đồng nghĩa cũng không chứng minh hai đối tượng cụ thể là một. Target Alignment của trang 4 không được tự động gộp node tại trang 5.

`NodeDTO` hiện không có trạng thái phê duyệt. Bản này giữ nguyên nguyên tắc đó: duyệt dữ kiện nằm ở cạnh; chỉnh hồ sơ thực thể không tự duyệt các cạnh liên quan. Không thêm nút “Duyệt tất cả thực thể” khi chưa định nghĩa được ý nghĩa nghiệp vụ.

## 2. Hiện trạng cần xử lý

Đối chiếu `frontend/pages/p05_curation_merge.py` và `backend/domain/curation/service.py`:

- Bảng cạnh, selectbox chọn cạnh, vùng bằng chứng và hai selectbox gộp node nằm nối tiếp trong một trang dài; chưa có bộ lọc hoặc checkbox chọn nhiều.
- Nút duyệt nhanh áp dụng trên toàn bộ cạnh được coi là đủ điều kiện, chưa cho xem trước chính xác phạm vi và lý do từng mục bị chặn.
- `set_edges_status()` sửa lần lượt từng cạnh và bỏ qua lỗi; cần bổ sung hợp đồng xem trước và lưu lô, tránh giao diện tự điều phối các lần ghi riêng lẻ.
- `update_edge()` mới hạ trạng thái đã duyệt khi bằng chứng không còn khớp và không có ngoại lệ. Đổi nguồn, đích hoặc nhãn quan hệ vẫn có thể giữ trạng thái cũ; đây là khoảng trống cần xử lý.
- `merge_nodes()` mới hỗ trợ hai node; nối mô tả, hợp bí danh và tài liệu nhưng chưa có màn hình giải quyết xung đột hoặc lịch sử gộp đầy đủ.
- Gộp cạnh trùng hiện lấy bản đầu theo nguồn, đích, quan hệ, bằng chứng và tài liệu; chưa xét vị trí trích dẫn, trạng thái và lịch sử. Có nguy cơ mất một quan sát hoặc quyết định kiểm duyệt.
- `affected_edges` hiện tăng theo số đầu mút được đổi; cần trả riêng số cạnh duy nhất và số đầu mút đổi để báo cáo đúng.
- Tìm bằng chứng hiện lấy lần xuất hiện đầu tiên trong toàn tài liệu; cần ưu tiên vị trí đã lưu, nhất là khi cùng một câu xuất hiện nhiều lần.

Trong mã nguồn đã có một phần nền tảng bulk EDC, như DTO, hàm preview/apply và thông tin đồng bộ SQLite. Khi triển khai phải kiểm tra mức độ nối đầy đủ qua facade/UI và tái sử dụng phần phù hợp; không mặc định mọi bảo đảm trong plan trang 4 đã hoàn tất.

## 3. Bố cục đề xuất

Ba vùng được đặt dưới một thanh chuyển mục, chỉ hiển thị nội dung vùng đang dùng. Dùng cùng phong cách bảng, bộ lọc, checkbox và thanh thao tác của trang 4; không bê toàn bộ hai bảng schema sang đây.

```text
5. Kiểm duyệt & Gộp thực thể
Chờ duyệt: N | Cần kiểm tra: N | Vướng danh mục: N | Cặp nghi trùng: N

[Quan hệ & bằng chứng]    [Thực thể]    [Gộp thực thể]

Tìm kiếm… | Trạng thái / Loại | Tài liệu | Bộ lọc khác ▾
Chọn trang này | Chọn tất cả kết quả lọc | Bỏ chọn
Đã chọn X / Y kết quả lọc

BẢNG CỦA VÙNG ĐANG MỞ                         Phân trang

Thanh thao tác theo tập đã chọn
Chi tiết dòng đang xem / Bản nháp / Xem trước kết quả
```

### Nguyên tắc hiển thị

- Mặc định mở **Quan hệ & bằng chứng**, lọc `Chờ duyệt` và `Cần kiểm tra`.
- Bảng chiếm toàn chiều ngang. Nội dung dài, ID kỹ thuật, trace và lịch sử đưa vào chi tiết có thể mở/đóng.
- Chi tiết quan hệ trên màn hình rộng chia hai cột: dữ kiện bên trái, nguồn và bằng chứng bên phải. Màn hình hẹp xếp dọc.
- Dùng nhãn và biểu tượng cùng màu; không dùng màu làm tín hiệu duy nhất. Nút bị khóa phải có lý do rõ.
- Chỉ một hành động chính nổi bật trong mỗi ngữ cảnh. Dùng “Loại bỏ khỏi đồ thị” thay cho từ “Xóa” nếu chỉ đổi trạng thái.
- Phân trang mặc định 50 dòng; cho chọn 25/50/100. Không đưa toàn bộ văn bản bằng chứng vào bảng.
- Các số thống kê không cộng thành một tổng: một cạnh có thể vừa cần kiểm tra vừa vướng danh mục. “Cặp nghi trùng” là số cặp gợi ý, không phải số thực thể chắc chắn trùng.
- Trạng thái rỗng phân biệt “Chưa có dữ liệu” với “Không có kết quả phù hợp”; cung cấp nút bỏ bộ lọc trong trường hợp thứ hai.

### Giữ trạng thái điều hướng

Khóa UI theo `project_id + section + object_id/action`; lưu vùng đang mở, bộ lọc, trang, lựa chọn, dòng chi tiết và bản nháp trong session. Rerun sau thao tác vẫn ở trang 5 và đúng vùng đang dùng, không bật lại trang Tổng quan hoặc reset selectbox.

Đi từ trang 5 sang đề xuất ở trang 4 phải mang theo `proposal_id`, `edge_id`/`node_id` và ngữ cảnh quay lại. Sau xử lý schema, tải trạng thái mới trước khi cho duyệt cạnh. Nếu cơ chế tab hiện tại không hỗ trợ điều hướng ổn định, bổ sung điều hướng có trạng thái tại `frontend/app.py`; không dựa riêng vào thứ tự gọi `st.tabs()`.

## 4. Vùng A — Quan hệ & bằng chứng

### 4.1. Bảng và bộ lọc

| Cột | Nội dung |
| --- | --- |
| Chọn | Checkbox theo `edge_id`; không chọn ngầm khi mở chi tiết |
| Thực thể nguồn | Tên hiển thị, mở hồ sơ node |
| Quan hệ | Nhãn canonical hiện tại; chi tiết cho xem tên gốc và quyết định EDC |
| Thực thể đích | Tên hiển thị, mở hồ sơ node |
| Trạng thái | Chờ duyệt / Cần kiểm tra / Đã duyệt / Loại bỏ |
| Bằng chứng | Khớp nguyên văn / Khớp sau chuẩn hóa / Không tìm thấy / Thiếu nguồn |
| Danh mục | Hợp lệ / Còn đề xuất chờ / Đề xuất bị từ chối / Ngoài danh mục |
| Nguồn | Tài liệu và trang hoặc đoạn khi có dữ liệu vị trí |

Lọc theo trạng thái, tài liệu, nhãn quan hệ, loại nguồn/đích, chất lượng bằng chứng, tình trạng schema; tìm theo tên hai đầu mút hoặc nội dung trích dẫn. Bộ lọc ít dùng nằm trong “Bộ lọc khác”. ID đầy đủ chỉ hiện khi mở chi tiết hoặc sao chép.

### 4.2. Đối chiếu một dữ kiện

1. Mở dòng: hiển thị rõ `Nguồn — quan hệ → Đích`, các loại tương ứng và nguồn trích xuất.
2. Bên bằng chứng hiển thị trích dẫn, ngữ cảnh trước/sau, vị trí và nút mở rộng ngữ cảnh. Tô sáng bằng chứng theo span đã xác minh; không render HTML thô từ tài liệu.
3. Ưu tiên offset và phiên bản văn bản đã lưu, sau đó giới hạn theo đoạn; chỉ tìm toàn tài liệu khi cần. Nếu có nhiều kết quả mà không xác định được vị trí, hiển thị “Nhiều vị trí phù hợp” để người dùng chọn.
4. Không tự bịa số trang cho DOCX hoặc tài liệu không có thông tin phân trang. Hiển thị tên tài liệu + số đoạn/vị trí ký tự phù hợp.
5. Thông báo rõ: **Khớp câu trích dẫn chỉ chứng minh câu có trong tài liệu; người duyệt vẫn cần xác nhận câu hỗ trợ đúng dữ kiện, chiều quan hệ và ngữ cảnh.**
6. Nếu vướng schema, đưa nút “Xử lý đề xuất ở trang 4”, chỉ rõ từng đề xuất liên quan. Cho phép đọc, sửa hoặc loại bỏ dữ kiện nhưng khóa phê duyệt cho đến khi schema hợp lệ.

Các nút chính: **Duyệt**, **Cần kiểm tra**, **Loại bỏ**, **Sửa dữ kiện**. Lưu bản sửa và duyệt là hai quyết định riêng, tránh một nút vô tình thực hiện cả hai.

### 4.3. Quy tắc duyệt

- Dùng chung một validator ở backend cho duyệt đơn, duyệt lô và kiểm tra dữ liệu xuất: đầu mút tồn tại, nhãn và loại hợp lệ, không còn chặn schema, bằng chứng không rỗng, nguồn còn hợp lệ.
- Tính lại kết quả khớp trên văn bản hiện tại; không chỉ tin `evidence_found` đã lưu từ lần trước.
- Không tìm thấy trích dẫn: bản đầu không cho duyệt hàng loạt. Cho xử lý riêng từng cạnh bằng sửa bằng chứng hoặc ngoại lệ có lý do và danh tính người duyệt. Ngoại lệ không vượt qua thiếu đầu mút, thiếu tài liệu hoặc schema chưa hợp lệ.
- Chấp nhận ngoại lệ nghĩa là người duyệt đã kiểm tra nguồn theo cách khác; lưu cách đối chiếu và lý do. Trên UI vẫn gắn nhãn ngoại lệ, không đổi thành “Khớp nguyên văn”.
- Cạnh tự nối cần quyết định riêng; bản đầu loại khỏi tập duyệt lô. Chỉ cho duyệt đơn khi người dùng xác nhận quan hệ có ý nghĩa tự nối và ghi lý do. Không mặc định mọi self-loop đều sai.
- Lý do loại bỏ có mã và ghi chú: sai thực thể, sai quan hệ/chiều, không đủ bằng chứng, dữ kiện trùng, không thuộc phạm vi, khác. “Không thuộc phạm vi” không đồng nghĩa dữ kiện sai.
- `Đã duyệt` và `Loại bỏ` được xem lịch sử và xử lý lại từng cạnh. Bản đầu không cho lô mặc định đảo các quyết định này.

## 5. Chọn nhiều, duyệt toàn bộ và duyệt một phần

Áp dụng quy tắc của trang 4 cho từng bảng độc lập:

1. Chọn một, nhiều, trang hiện tại hoặc toàn bộ kết quả lọc; hiển thị chính xác số lượng, kể cả ngoài trang hiện tại.
2. Giữ lựa chọn theo ID khi đổi trang/sắp xếp. Đổi bộ lọc lấy giao giữa tập đã chọn và tập kết quả mới, báo số mục đã bỏ chọn.
3. Đổi dự án xóa lựa chọn và preview cũ. Chuyển giữa ba vùng giữ lựa chọn riêng, không tự chuyển lựa chọn thành lệnh thao tác.
4. “Duyệt toàn bộ kết quả lọc” chốt danh sách ID và mở preview; không có nghĩa toàn bộ dự án. Chỉ nhận cạnh `Chờ duyệt`/`Cần kiểm tra`; báo riêng số mục đã xử lý bị loại khỏi phạm vi.
5. Dòng đang xem chi tiết độc lập với các dòng đã tick. Mở xem một dòng không thêm dòng đó vào lô.

Thanh thao tác của vùng A: **Duyệt đã chọn**, **Chuyển cần kiểm tra**, **Loại bỏ đã chọn**, **Bỏ chọn**. Lý do chung được áp dụng rõ ràng cho lô chuyển cần kiểm tra/loại bỏ, cho phép sửa riêng từng dòng ở preview.

### Xem trước và áp dụng

- Preview hiển thị tổng số yêu cầu, số hợp lệ, số bị chặn; mỗi dòng có quyết định, trạng thái trước/sau và lý do.
- Mặc định `all_or_nothing`: có mục không hợp lệ thì chưa ghi gì.
- Người dùng có thể chọn rõ **“Chỉ áp dụng N mục hợp lệ”** (`valid_only`). Ví dụ chọn 10 cạnh, 7 hợp lệ, 3 vướng schema: áp dụng 7, giữ nguyên 3 và liệt kê cách xử lý.
- “Duyệt một phần” cũng có thể là bỏ tick những mục chưa muốn duyệt, không bắt buộc dùng chế độ bỏ qua lỗi.
- Toàn bộ tập hợp lệ được ghi bằng một giao dịch logic. Lỗi ghi tệp không được báo thành “duyệt một phần thành công”.
- Thay lựa chọn, nội dung, quyết định hoặc phiên bản dữ liệu làm preview cũ mất hiệu lực. Cạnh mới xuất hiện sau preview không tự gia nhập lô.
- Sau lưu: báo số thành công, số còn chờ và lý do; bỏ chọn mục thành công. Giữ bản nháp của mục chưa xử lý nếu còn khớp bộ lọc.
- Không cần hộp xác nhận thứ hai sau preview đối với lô thông thường. Quyết định đơn từ bảng chi tiết đã đủ thông tin có thể lưu trực tiếp qua cùng validator và cơ chế giao dịch.

## 6. Vùng B — Thực thể

### 6.1. Bảng và hồ sơ

Các cột: checkbox, tên, loại thực thể, bí danh rút gọn, số tài liệu, số cạnh liên quan, vấn đề dữ liệu. Lọc theo tên/bí danh, loại, tài liệu và dấu hiệu trùng. Hai node cùng tên vẫn là hai dòng riêng; phần chi tiết hiển thị ID ngắn và nguồn để phân biệt.

Hồ sơ gồm:

- Tên chính, loại hiện tại, mô tả, danh sách bí danh dạng từng mục.
- Danh sách tài liệu và những lần xuất hiện có vị trí nếu dữ liệu đã lưu; không suy diễn vị trí từ tên.
- Quan hệ đi vào/đi ra cùng trạng thái, mở được vùng A với bộ lọc theo `node_id`.
- Đề xuất schema liên quan, lịch sử sửa/gộp và dấu hiệu cần xử lý.

### 6.2. Thao tác

- **Sửa hồ sơ:** một node/lần, form có Lưu/Hủy; bản nháp không ghi xuống dự án theo mỗi ký tự.
- **Xem quan hệ:** một node/lần; nếu chọn nhiều, hiển thị hợp các cạnh liên quan, đếm mỗi cạnh một lần.
- **Đưa vào gộp:** ít nhất hai node được chọn; chuyển danh sách ID sang vùng C dưới dạng bản nháp, chưa thay đổi dữ liệu.
- Không đổi hàng loạt tên hoặc loại trong bản đầu. Không có nút xóa cứng node đang được tham chiếu.
- Loại phải chọn từ catalog đã duyệt. Nếu cần loại mới, dùng luồng đề xuất trang 4; trang 5 không âm thầm ghi thêm vào `entity_types.json`.

Chuẩn hóa NFC và khoảng trắng cho tên/bí danh; loại bí danh trùng theo hàm `normal()` dùng chung, loại bí danh trùng tên chính. Giữ dấu tiếng Việt và cách viết để hiển thị. Không dùng tên làm định danh và không gộp hai node chỉ vì tên sau chuẩn hóa giống nhau.

## 7. Vùng C — Gộp thực thể

### 7.1. Danh sách nghi trùng

Hiển thị các cặp gợi ý với tên, loại, tài liệu, lý do và điểm giống tên. Điểm hiện có từ `SequenceMatcher` được ghi là **độ giống tên**, không gọi là xác suất cùng thực thể hoặc điểm embedding.

Hai lối vào: mở một cặp gợi ý hoặc nhận các node đã chọn ở vùng B. Cho đánh dấu “Khác đối tượng” kèm ghi chú để giảm gợi ý lặp; quyết định này gắn với cặp ID và phiên bản thông tin liên quan, cho phép xem lại khi dữ liệu thay đổi.

Không coi chuỗi A giống B, B giống C là bằng chứng A/B/C đều cùng một đối tượng. Bản đầu xử lý một nhóm gộp mỗi lần, có thể chứa nhiều node; chưa có “gộp tất cả gợi ý”.

### 7.2. Luồng ba bước

**Bước 1 — Đối chiếu:** bảng so sánh các node theo tên, loại, mô tả, bí danh, nguồn, quan hệ nổi bật. Người dùng chọn rõ một node giữ lại; không tự chọn node đầu tiên làm đích đã được xác nhận.

**Bước 2 — Chọn dữ liệu sau gộp:**

- Giữ nguyên ID của node đích; chọn tên chính, thêm các tên còn lại vào bí danh sau chuẩn hóa.
- Các loại khác nhau phải được giải quyết: chọn loại canonical phù hợp và ghi lý do; còn đề xuất schema chưa giải quyết thì chặn commit, cho liên kết sang trang 4.
- Mô tả khác nhau hiển thị song song để chọn hoặc biên tập; không nối máy móc thành một mô tả có thể mâu thuẫn. Lưu bản gốc trong lịch sử.
- Hợp tài liệu và nguồn tham chiếu theo ID, bảo toàn quan sát gốc, đề xuất schema và dữ liệu trích xuất ban đầu.

**Bước 3 — Xem trước ảnh hưởng và áp dụng:**

- Tên và ID node giữ lại; các node sẽ ngừng xuất hiện trong danh sách node hoạt động.
- Số cạnh duy nhất đổi đầu mút, số đầu mút đổi, số cạnh đang duyệt phải kiểm tra lại.
- Các self-loop mới, nhóm cạnh có vẻ trùng, xung đột còn lại; xem được từng dòng trước/sau.
- Nút cuối ghi rõ **“Gộp N thực thể thành 1”**; chỉ bật khi đã giải quyết xung đột bắt buộc.

### 7.3. Bảo toàn dữ liệu khi gộp

1. Cập nhật mọi tham chiếu node theo quy tắc miền dữ liệu; không sửa chuỗi tên bên trong trích dẫn nguyên văn. Giữ dữ liệu trích xuất gốc để đối chiếu.
2. Mỗi cạnh có đầu mút đổi chuyển về `Cần kiểm tra`, trừ cạnh đang `Loại bỏ` vẫn giữ nguyên. Xóa hiệu lực phê duyệt/ngoại lệ cũ nhưng bảo toàn quyết định cũ trong audit.
3. Giữ **mọi edge ID và mọi bằng chứng** trong bản đầu. Cạnh trông trùng được nhóm để hiển thị, không tự xóa theo khóa bộ ba hoặc bằng chứng. Có thể loại bỏ một cạnh trùng qua luồng kiểm duyệt có lý do.
4. Cạnh tự nối mới được giữ lại, gắn lý do cần kiểm tra; không tự xóa hay duyệt. Xử lý theo quy tắc duyệt đơn ở mục 4.3.
5. Lưu ánh xạ `old_node_id → canonical_node_id` để tra lịch sử và xử lý liên kết cũ; không tạo vòng ánh xạ. Lần gộp tiếp theo phải phân giải đến node đang hoạt động.
6. Lưu snapshot trước lô và bản trước/sau trong lịch sử. Khôi phục bản đầu là khôi phục snapshot dự án, có xem trước ảnh hưởng đến các thay đổi về sau; chưa hứa hỗ trợ tách lại từng node độc lập.
7. Nếu một node bị sửa/gộp ở phiên khác sau preview, chặn áp dụng và yêu cầu tải lại. Không tự đoán một đích thay thế.

## 8. Chuẩn dữ liệu và quy tắc sửa

### 8.1. Hợp đồng dữ liệu

Không thay định dạng catalog tại trang 5. Catalog v2 tiếp tục dùng `name`, `description`, `definition`; dữ liệu node/cạnh là mô hình khác.

| Đối tượng | Trường và quy tắc |
| --- | --- |
| Node đang hoạt động | Giữ `id`, `name`, `kind`, `description`, `aliases[]`, `documents[]`; bảo toàn trường mở rộng đang có |
| Cạnh | Giữ `id`, `source`, `target`, `relation`, `evidence`, `doc_id`, `doc_name`, `chunk_number`, `status`; tham chiếu bằng ID |
| Vị trí bằng chứng | Chuẩn hóa trường hiện có `page`, `start_char`, `end_char`; offset 0-based, đầu gồm/cuối không gồm trên đúng văn bản chuẩn dùng để trích xuất; bổ sung fingerprint văn bản và phương thức khớp |
| Kiểm duyệt | `reviewed_at`, `override`, `review_note` hiện có được giữ tương thích; thêm mã lý do và tham chiếu sự kiện quyết định |
| Lịch sử | Sự kiện có ID, `request_id`, `batch_id`, thời gian, người thao tác/nguồn thao tác, hành động, ID tác động, dữ liệu trước/sau, lý do, revision và snapshot |
| Gộp node | Bản ghi các ID nguồn/đích, bản hồ sơ gốc, quyết định giải quyết xung đột, các cạnh bị đổi và ánh xạ ID cũ |

Giữ các hằng trạng thái hiện có trong `shared/constants.py`, không thêm một bộ enum tiếng Anh song song chỉ cho UI. Dữ liệu cũ thiếu vị trí hoặc audit được hiển thị “Chưa có”, không bịa thời gian/người duyệt. DTO phải đọc/ghi được trường mở rộng, không làm mất `schema_proposal_ids`, `edc_original` hoặc metadata nguồn khi chuyển qua API.

Việc lưu vị trí theo fingerprint cần thống nhất với bước trích xuất. Tài liệu thay nội dung thì vị trí cũ mất hiệu lực, phải đối chiếu lại; không tô sáng bằng offset cũ trên văn bản mới.

### 8.2. Ma trận ảnh hưởng của chỉnh sửa

| Thay đổi | Ảnh hưởng tới kiểm duyệt |
| --- | --- |
| Sửa tên hiển thị, bí danh hoặc mô tả hồ sơ, không đổi danh tính/loại | Giữ ID, lưu audit; không tự thay trạng thái cạnh |
| Đổi loại node | Các cạnh nối node chuyển cần kiểm tra, trừ cạnh đã loại bỏ; kiểm tra lại schema |
| Đổi nguồn, đích, quan hệ, bằng chứng hoặc nguồn/vị trí dẫn chứng của cạnh | Cạnh chuyển cần kiểm tra, trừ cạnh đã loại bỏ; đối chiếu bằng chứng lại |
| Gộp node | Áp dụng mục 7.3 cho mọi cạnh thực sự đổi đầu mút |
| Thêm ghi chú hoặc thay bộ lọc UI | Không thay dữ kiện hoặc trạng thái phê duyệt |

Form sửa hồ sơ nhắc rõ đổi tên chỉ là sửa cách biểu diễn cùng một đối tượng; nếu xác định cạnh đang trỏ nhầm đối tượng, phải sửa đầu mút cạnh. Mọi thao tác vô hiệu hóa quyết định cũ phải xóa hiệu lực `reviewed_at`/ngoại lệ tương ứng và lưu lý do, không xóa lịch sử.

## 9. Hợp đồng backend và lưu dữ liệu

### 9.1. DTO/use case đề xuất

Đặt DTO riêng tại `shared/schemas/curation.py`; dùng lại quy ước revision, request và kết quả của trang 4, không dùng `ProposalDecisionDTO` cho dữ kiện.

- `CurationQueryDTO`: dự án, bộ lọc, sắp xếp, phân trang; trả tổng số, ID và các lý do chặn đã tính ở backend.
- `EdgeReviewDecisionDTO`: `edge_id`, hành động, mã lý do, ghi chú; ngoại lệ bằng chứng chỉ trong luồng đơn có trường riêng.
- `CurationReviewRequestDTO`: dự án, `expected_revision`, `request_id`, các quyết định, `apply_mode`.
- `CurationPreviewDTO`: `preview_id`, revision dự án, hash catalog và nội dung yêu cầu, ID đã chốt, kết quả hợp lệ/lỗi từng mục, các ảnh hưởng.
- `EntityEditRequestDTO` / `EdgeEditRequestDTO`: ID, trường thay đổi cho phép, revision, request và lý do nếu cần. Backend không nhận một dict bất kỳ để ghi đè mọi thuộc tính.
- `EntityMergeRequestDTO`: các ID thành viên, `keep_id`, lựa chọn trường sau gộp, lý do, revision và request. Mọi thành viên phải còn tồn tại, duy nhất và thuộc cùng dự án.
- `CurationResultDTO`: batch/request, revision trước/sau, ID thành công/chưa xử lý, lỗi, snapshot, trạng thái commit và đồng bộ.

Các phương thức facade tương ứng: truy vấn, preview review, apply review, sửa node/cạnh, preview merge, apply merge. UI gọi qua `FrontendClient`; khi mở REST phải dùng cùng use case, không dựng một luồng lưu khác.

### 9.2. Giao dịch và đồng bộ

Kế thừa cơ chế chung trong plan trang 4, với những điều kiện bắt buộc cho trang 5:

1. Backend đọc phiên bản hiện tại, khóa ghi theo dự án, kiểm tra revision và catalog, tái xác thực yêu cầu, tạo bản thay đổi trên bản sao.
2. Preview không thay đổi dữ liệu. Apply chỉ dùng nội dung đã chốt; cùng `request_id` và cùng nội dung trả lại kết quả trước, cùng ID nhưng khác nội dung bị từ chối.
3. Một lô hợp lệ tạo một snapshot và một commit logic gồm dữ liệu, audit, ánh xạ gộp và biên nhận request. Không gọi `save_project()` theo từng dòng từ giao diện.
4. JSON là nguồn dữ liệu chính; SQLite là chỉ mục tái tạo được. JSON đã commit nhưng SQL lỗi thì trả `committed + sync_pending`, cảnh báo và cho thử đồng bộ lại; không chạy lại quyết định duyệt/gộp.
5. Lỗi trước commit không được để một phần node/cạnh đổi trên session hoặc ổ đĩa. Dùng cơ chế ghi an toàn và phục hồi journal phù hợp repo; kiểm tra cả phục hồi sau ngắt tiến trình.
6. Sau commit tải trạng thái dự án mới, cập nhật bảng, thống kê và trang 6. Không ghi ngược bản session cũ đè lên kết quả từ trang 4/phiên khác.
7. Mọi đường ghi dự án có liên quan phải tham gia cùng quy tắc phiên bản/khóa, nếu không kiểm tra stale ở riêng trang 5 chưa đủ bảo vệ khỏi ghi đè.

Luồng này không yêu cầu gọi LLM hoặc embedding khi duyệt/sửa/gộp thủ công. Không bổ sung vector database mới cho phạm vi hiện tại.

## 10. Liên kết với xuất đồ thị và dữ liệu huấn luyện

- Trang 6 và các dạng xuất chỉ nhận cạnh được duyệt còn hợp lệ theo validator dùng chung; không chỉ kiểm tra chuỗi trạng thái từ SQLite.
- Các cạnh vừa đổi loại/đầu mút sau EDC hoặc gộp phải rời tập xuất cho đến khi được duyệt lại. Node được xuất theo các cạnh đủ điều kiện, giữ ID canonical.
- Bảo toàn cạnh nhiều nguồn ở dữ liệu gốc và bản xuất; nếu giao diện đồ thị nhóm cạnh để dễ nhìn, vẫn phải mở được từng bằng chứng.
- Chỉ quyết định con người đã commit mới tạo nhãn kiểm duyệt. `evidence_found=True` không tự là nhãn đúng; loại bỏ vì ngoài phạm vi hoặc trùng dữ liệu không tự là nhãn sai về ngữ nghĩa.
- Sửa hồ sơ/gộp danh tính không tự trở thành quyết định Target Alignment của loại hoặc quan hệ. Lịch sử phải phân biệt các loại thao tác để ML Lab sử dụng đúng.

## 11. Phân công theo file/module khi triển khai

| File/module | Công việc |
| --- | --- |
| `frontend/pages/p05_curation_merge.py` | Điều phối ba vùng; bỏ giao diện dồn và ghi trực tiếp theo từng thao tác |
| `frontend/components/curation_table.py` — mới | Bảng, bộ lọc, selection và thanh thao tác cạnh/thực thể |
| `frontend/components/evidence_panel.py` — mới | Chi tiết dữ kiện, đối chiếu nguồn, bản nháp sửa và quyết định đơn |
| `frontend/components/entity_merge_panel.py` — mới | So sánh hồ sơ, giải quyết xung đột, preview gộp |
| `frontend/state/session.py`, `frontend/app.py` | Lưu điều hướng và trạng thái theo dự án; nối trang 4–5, bảo vệ bản nháp |
| `frontend/client.py` | Phương thức đọc/preview/apply chung cho chế độ in-process và API |
| `shared/schemas/graph.py`, `shared/schemas/curation.py` — mới | Chuẩn DTO, vị trí bằng chứng, yêu cầu/preview/kết quả và bảo toàn metadata |
| `backend/domain/curation/service.py` | Validator, ảnh hưởng chỉnh sửa, duyệt lô, preview/apply gộp, không tự xóa cạnh trùng |
| `backend/facade.py`, `backend/api/v1.py` | Điều phối giao dịch, revision, idempotency và hợp đồng lỗi |
| `backend/repositories/json_repo.py`, `sqlite_repo.py` | Lưu an toàn, snapshot/audit/ánh xạ, đồng bộ và khôi phục |
| `backend/domain/graph/service.py` | Dùng cùng điều kiện đủ để xuất dữ kiện; không lọt cạnh hết hiệu lực |
| `backend/domain/dataset_exporter/exporter.py` | Tách nhãn con người khỏi khớp bằng chứng và lý do loại bỏ không phải sai dữ kiện |
| `tests/` | Kiểm thử domain, giao dịch, migration, facade và hành vi UI cốt lõi |
| `AI/structure.md`, tài liệu sử dụng | Cập nhật sau triển khai, không mô tả tính năng dự kiến như đã có |

Nếu component lựa chọn/preview đã được tạo cho trang 4, ưu tiên trích phần chung hợp lý; giữ riêng logic schema, duyệt dữ kiện và gộp danh tính. Không tạo một component lớn chứa cả ba nghiệp vụ.

## 12. Lộ trình triển khai

### Đợt 1 — Chuẩn dữ liệu và bố cục

- Chốt validator và ma trận sửa; thống nhất ID, vị trí bằng chứng, audit và kết quả lỗi.
- Tách ba vùng, thêm bảng/bộ lọc, hồ sơ và chi tiết bằng chứng; giữ trạng thái trang/subsection.
- Hoàn thiện sửa và duyệt đơn qua facade; không mất metadata khi lưu dự án cũ.

**Điều kiện hoàn tất:** dữ kiện luôn truy được nguồn; sửa trường ngữ nghĩa làm mất hiệu lực duyệt đúng phạm vi; rerun không đổi trang.

### Đợt 2 — Duyệt hàng loạt

- Chọn trang/chọn tất cả kết quả lọc, preview, all-or-nothing và valid-only.
- Nối giao dịch chung với trang 4, kiểm tra revision, idempotency, snapshot và SQL sync pending.
- Hoàn thiện chuyển sang xử lý schema và quay lại đúng dữ kiện.

**Điều kiện hoàn tất:** không tác động mục bị ẩn ngoài phạm vi; kết quả từng mục rõ ràng; thử lại không duyệt hai lần.

### Đợt 3 — Gộp an toàn

- Danh sách nghi trùng, chọn nhiều từ vùng B, so sánh và chọn node giữ lại.
- Preview xung đột, giữ cạnh/bằng chứng, ánh xạ ID, audit, vô hiệu hóa phê duyệt bị ảnh hưởng.
- Khôi phục snapshot có báo phạm vi thay đổi; chưa làm gộp tự động hàng loạt hoặc tách node tùy ý.

**Điều kiện hoàn tất:** gộp không mất quan sát; tất cả cạnh đổi đầu mút được kiểm tra lại; lịch sử giải thích được mọi thay đổi.

### Đợt 4 — Nghiệm thu và tài liệu

- Kiểm tra liên thông trang 4–5–6 và ML exporter, dữ liệu tiếng Việt, dự án cũ và lỗi lưu.
- Đo thời gian tải/phân trang/gợi ý trên dữ liệu đại diện. Không chạy so sánh mọi cặp node theo O(n²) trong mỗi rerun; cache theo revision, tải gợi ý theo yêu cầu và phân trang. Tối ưu tìm ứng viên trước khi đưa dữ liệu lớn vào dùng thực tế.
- Cập nhật hướng dẫn sử dụng với ba ví dụ: duyệt một dữ kiện, duyệt một phần lô, gộp hai tên cùng một đối tượng.

## 13. Kịch bản nghiệm thu bắt buộc

| Tình huống | Kết quả cần đạt |
| --- | --- |
| Mở cạnh chỉ để đọc | Không tự tick hoặc duyệt |
| Chọn 3 cạnh rồi đổi thứ tự/phân trang | Vẫn đúng 3 ID; đổi lọc bỏ mục bị ẩn và báo số lượng |
| Chọn toàn bộ 120 kết quả với trang 50 dòng | Preview đúng 120 ID, cạnh mới đến sau không tự vào lô |
| Chọn 10 cạnh, 3 vướng schema | Mặc định không ghi; chọn áp dụng 7 hợp lệ thì chỉ 7 thay đổi |
| Câu trích dẫn có thật nhưng không hỗ trợ quan hệ | UI cho loại bỏ có lý do; không tự duyệt nhờ khớp văn bản |
| Hai vị trí có cùng câu dẫn chứng | Hiển thị vị trí đã xác minh hoặc yêu cầu chọn, không luôn lấy lần đầu |
| Sửa đích/quan hệ của cạnh đã duyệt | Về cần kiểm tra dù câu bằng chứng vẫn khớp |
| Sửa bí danh mà không đổi danh tính | Giữ ID và trạng thái cạnh; có lịch sử sửa |
| Hai người cùng tên nhưng khác nguồn/ngữ cảnh | Chỉ là ứng viên; cho đánh dấu khác đối tượng, không tự gộp |
| Gộp 3 node có xung đột loại | Phải giải quyết xung đột và schema trước commit |
| Gộp tạo hai cạnh cùng bộ ba nhưng khác nguồn/vị trí | Giữ cả hai ID và bằng chứng; chỉ nhóm hiển thị |
| Gộp tạo self-loop hoặc chạm cạnh đã loại bỏ | Self-loop cần kiểm tra; cạnh đã loại bỏ giữ trạng thái |
| Một cạnh đổi cả hai đầu mút | Báo một cạnh ảnh hưởng, hai đầu mút thay đổi |
| Preview cũ sau khi trang 4 đổi catalog hoặc phiên khác gộp node | Chặn commit, tải lại và xem trước mới |
| Bấm áp dụng hai lần / thử lại sau timeout | Một quyết định đã commit, một bộ audit và kết quả có thể lấy lại |
| Lỗi ghi JSON / JSON xong nhưng SQLite lỗi | Trường hợp đầu không commit một phần; trường hợp sau báo sync pending và đồng bộ lại được |
| Mở dự án cũ, sửa rồi lưu | Không mất metadata; trường chưa có hiển thị trung thực |
| Duyệt/sửa/chuyển trang 4 rồi quay lại | Vẫn ở đúng vùng, filter và đối tượng; dữ liệu đã được làm mới |
| Xuất sau khi gộp | Cạnh hết hiệu lực duyệt không vào đồ thị đã duyệt; dữ liệu gốc và audit vẫn đủ |

Kiểm thử domain và giao dịch dùng fixture tạm, có mô phỏng lỗi ghi và đồng bộ. Kiểm thử UI tập trung vào chọn theo ID, điều hướng, bản nháp và phạm vi áp dụng; không cần LLM thật để nghiệm thu chức năng này.

## 14. Kết quả mong đợi

Người dùng đọc một bảng gọn, mở đúng chi tiết, đối chiếu nguồn rồi quyết định. Khi cần xử lý nhiều mục, họ biết chính xác số lượng và lý do mục nào chưa được áp dụng. Khi gộp thực thể, họ nhìn được hồ sơ sau gộp và các dữ kiện bị ảnh hưởng trước khi lưu; hệ thống vẫn giữ đủ nguồn và lịch sử để kiểm tra lại.

---

## 15. Trạng thái triển khai & Báo cáo nghiệm thu

- **Trạng thái:** ✅ Đã triển khai đầy đủ toàn bộ 4 đợt và vượt qua 100% kịch bản nghiệm thu bắt buộc (`20/20` bài kiểm thử tự động PASS).
- **Báo cáo chi tiết:** Xem tại [curation-merge-report.md](file:///D:/DATN/CrawData/KG_Studio/AI/features/curation-merge-report.md).
- **Bộ kiểm thử tự động:** [tests/test_curation_merge.py](file:///D:/DATN/CrawData/KG_Studio/tests/test_curation_merge.py).
