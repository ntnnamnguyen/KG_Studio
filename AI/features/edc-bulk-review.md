# Plan: Tách bảng và duyệt EDC hàng loạt

- **Trạng thái:** Đã triển khai và kiểm thử hoàn tất (`13/13` tests PASS).
- **Phạm vi:** Trang **4. Duyệt EDC & Target Alignment** của `KG_Studio Pro`.
- **Căn cứ kiến trúc:** [structure.md](../structure.md), mục 2.3–2.5 và luồng 3.3–3.4.
- **Mục tiêu:** Tách đề xuất loại thực thể và quan hệ thành hai bảng độc lập; hỗ trợ chọn một, chọn nhiều, chọn tất cả, duyệt toàn bộ phạm vi hoặc một phần, hợp nhất và từ chối theo lô.

## 1. Hiện trạng và giới hạn phạm vi

Đối chiếu với mã nguồn hiện tại:

- `frontend/pages/p04_edc_alignment.py` gọi `render_edc_alignment_curation()`.
- `frontend/components/edc_alignment_panel.py` hiển thị một bảng trộn cả hai `kind`, sau đó dùng selectbox để xử lý từng đề xuất.
- Có ba quyết định đơn: `approve`, `merge`, `reject`; chưa có chọn nhiều hoặc hợp đồng xử lý theo lô.
- Nút Target Alignment đang chạy trên toàn bộ đề xuất `pending` của dự án, chưa nhận tập ID được chọn.
- `backend/domain/catalogs/service.py::decide_proposal()` đã xử lý cập nhật catalog, node/cạnh liên quan, lịch sử và đưa cạnh về trạng thái cần kiểm tra.
- `KGStudioFacade.save_project()` ghi JSON rồi đồng bộ SQLite; lỗi đồng bộ SQLite hiện bị bỏ qua. Không được mặc định rằng đây là một giao dịch atomic giữa mọi nơi lưu trữ.

**Phân biệt bắt buộc:** “Thực thể” trong trang 4 là **đề xuất loại thực thể** (`kind="entity_types"`), ví dụ `tháp`, `nhân vật`. Các đối tượng cụ thể như một công trình hoặc một người, cùng thao tác gộp node trùng lặp, tiếp tục thuộc trang 5. Bảng thứ hai là **đề xuất quan hệ** (`kind="relations"`).

Không mở rộng đợt này sang trích xuất mới, đổi thuật toán embedding, tự duyệt cạnh, đồng bộ Neo4j tự động hoặc gộp thực thể cụ thể.

## 2. Bố cục trang mới

Hiển thị hai khu vực theo chiều dọc, mỗi bảng dùng toàn bộ chiều ngang để đọc định nghĩa:

```text
4. Duyệt EDC & Target Alignment
Tổng quan: Chờ duyệt | Đã duyệt mới | Đã hợp nhất | Đã từ chối

A. Đề xuất loại thực thể
   Bộ lọc + Tìm kiếm
   Chọn trang này | Chọn tất cả kết quả lọc | Bỏ chọn
   Đã chọn X / Y kết quả lọc / Z tổng số
   [ ] Tên | Định nghĩa | Ứng viên đích | Điểm | Trạng thái | Ảnh hưởng
   Thao tác trên mục đã chọn | Duyệt toàn bộ kết quả lọc

B. Đề xuất quan hệ
   Bộ lọc + Tìm kiếm
   Chọn trang này | Chọn tất cả kết quả lọc | Bỏ chọn
   Đã chọn X / Y kết quả lọc / Z tổng số
   [ ] Tên | Định nghĩa | Ứng viên đích | Điểm | Trạng thái | Ảnh hưởng
   Thao tác trên mục đã chọn | Duyệt toàn bộ kết quả lọc

Chi tiết mục đang xem: định nghĩa, nguồn, bằng chứng, Top-K ứng viên
Xem trước lô quyết định → Kiểm tra → Áp dụng → Báo cáo kết quả
```

Hai bảng có bộ lọc, tập lựa chọn và bản nháp riêng. Thao tác tại bảng A không làm thay đổi bảng B. Bản đầu không có nút ngầm áp dụng cho cả hai bảng; người dùng xử lý lần lượt để phạm vi rõ ràng.

### 2.1. Cột của mỗi bảng

| Cột | Hành vi |
| --- | --- |
| Chọn | Checkbox; mặc định chưa chọn dòng nào. |
| Tên đề xuất | Tên gốc; có thể mở chi tiết bằng ID ổn định. |
| Mô tả / Định nghĩa | Bảng hiển thị bản rút gọn; phần chi tiết cho xem đầy đủ. |
| Ứng viên đích | Tên ứng viên đầu tiên hoặc “Chưa có”; chưa đồng nghĩa đã chọn đích. |
| Điểm tương đồng | Số thực, ví dụ `0.86`; không trình bày thành xác suất đúng 86%. |
| Xác thực | Phân biệt gợi ý vector, đã được LLM kiểm tra, tự động hợp nhất, con người quyết định. |
| Trạng thái | `pending`, `approved`, `merged`, `rejected`, với nhãn tiếng Việt. |
| Tên chuẩn | Giá trị đã duyệt hoặc hợp nhất, nếu có. |
| Ảnh hưởng | Số node và số cạnh liên quan; đếm cạnh bị ảnh hưởng gián tiếp qua đổi loại node. |
| Nguồn | Số tài liệu/quan sát; mở chi tiết để đối chiếu từng nguồn. |

ID được giữ làm khóa kỹ thuật, không dùng vị trí dòng hoặc tên làm khóa lựa chọn. Không cho sửa trực tiếp trạng thái đã lưu trong bảng.

### 2.2. Bộ lọc

- Trạng thái: mặc định `pending`; có thể xem mục đã xử lý.
- Tìm theo tên đề xuất, tên chuẩn hoặc nội dung định nghĩa.
- Tài liệu nguồn: dựa trên `observations`.
- Có/không có ứng viên; thiếu định nghĩa; tự động hợp nhất/chưa có quyết định của người dùng.
- Sắp xếp theo tên, số cạnh ảnh hưởng hoặc điểm tương đồng.
- Phân trang với kích thước cấu hình được, mặc định 50 dòng.

Nếu không có đề xuất hoặc bộ lọc không trả kết quả, hiển thị trạng thái rỗng và vô hiệu hóa các nút áp dụng.

## 3. Quy tắc chọn một, chọn nhiều và chọn tất cả

1. **Chọn một/nhiều:** tick checkbox theo `proposal_id`.
2. **Chọn trang này:** chọn các dòng đủ điều kiện trên trang hiện tại.
3. **Chọn tất cả kết quả lọc:** chọn toàn bộ các dòng đủ điều kiện khớp bộ lọc, kể cả ngoài trang đang xem. Hiển thị rõ số lượng.
4. **Bỏ chọn:** xóa lựa chọn của riêng bảng hiện tại.
5. Đổi trang hoặc thứ tự sắp xếp giữ nguyên lựa chọn theo ID.
6. Đổi bộ lọc loại khỏi tập chọn những ID không còn hiển thị trong kết quả mới; thông báo số mục đã bỏ chọn. Không tác động âm thầm tới mục bị ẩn.
7. Đổi dự án xóa lựa chọn, bản nháp và kết quả xem trước của dự án trước. Rerun thông thường giữ lựa chọn của dự án hiện tại.
8. Sau khi áp dụng, bỏ chọn mục thành công; giữ lựa chọn và bản nháp của mục lỗi/chưa xử lý nếu còn thuộc bộ lọc.
9. Tập ID của “tất cả” được chốt khi xem trước. Đề xuất mới xuất hiện sau đó không tự được đưa vào lô.
10. Bản đầu chỉ cho áp dụng lô quyết định trên `pending`. Mục đã xử lý được xem lịch sử và xử lý lại riêng qua luồng đơn hiện có; không để thao tác hàng loạt vô tình đảo quyết định cũ.

Phân biệt **dòng đang mở chi tiết** với **các dòng đã chọn để thao tác**. Mở xem một dòng không tự đánh dấu duyệt dòng đó.

## 4. Thao tác mới

| Thao tác | Phạm vi và điều kiện | Kết quả |
| --- | --- | --- |
| Duyệt các mục đã chọn thành mục mới | Các ID đã tick; tên chuẩn và định nghĩa hợp lệ | Mỗi đề xuất trở thành một mục catalog riêng, trạng thái `approved`. |
| Duyệt toàn bộ kết quả lọc thành mục mới | Mọi đề xuất `pending` khớp bộ lọc trong bảng hiện tại | Mở xem trước toàn bộ phạm vi; không bỏ qua validation. |
| Hợp nhất các mục đã chọn | Người dùng chỉ định đích riêng cho từng dòng | Trạng thái `merged`, cập nhật tham chiếu qua logic nghiệp vụ hiện có. |
| Chọn cùng một đích cho nhiều mục | Cùng `kind`; người dùng chọn đích có sẵn | Điền đích vào bản nháp của những dòng được chọn; chưa lưu ngay. |
| Điền ứng viên đầu tiên vào bản nháp | Chỉ những dòng có ứng viên còn hợp lệ | Hỗ trợ thao tác nhanh; người dùng vẫn xem lại ánh xạ trước khi áp dụng. |
| Từ chối các mục đã chọn | Có lý do chung hoặc lý do riêng từng dòng | Trạng thái `rejected`; giữ đề xuất và nguồn, không xóa node/cạnh. |
| Làm mới gợi ý cho mục đã chọn | Nhận đúng tập ID và `kind` | Cập nhật ứng viên, không tự đổi trạng thái kiểm duyệt trong chế độ này. |
| Sửa tên chuẩn, mô tả, định nghĩa | Bản nháp duyệt mới theo từng dòng | Chưa thay dữ liệu dự án cho tới khi áp dụng. |

“Duyệt toàn bộ” luôn hiển thị nhãn đầy đủ kèm phạm vi và số mục. Không tạo nút “Duyệt” có hành vi lúc thêm mới, lúc tự chọn Top-1 tùy điểm số.

### 4.1. Duyệt một phần

Hỗ trợ hai trường hợp:

- Người dùng tự chọn một tập con rồi áp dụng.
- Lô có cả mục hợp lệ và không hợp lệ: sau xem trước, người dùng chọn **Áp dụng N mục hợp lệ; giữ M mục cần sửa**.

Mặc định, nếu có lỗi validation, nút **Áp dụng toàn bộ lô** bị khóa. Không tự bỏ qua lỗi. Chỉ thực hiện một phần sau khi người dùng chọn rõ phạm vi hợp lệ.

Ví dụ: chọn 12 loại thực thể, 9 đủ điều kiện và 3 thiếu định nghĩa. Có thể duyệt 9 mục; 3 mục còn lại giữ `pending` cùng bản nháp để tiếp tục sửa. Không tự sinh định nghĩa cho 3 mục đó bằng LLM trong thao tác duyệt.

### 4.2. Xem trước quyết định

Bảng xem trước có: ID, tên gốc, thao tác, tên chuẩn/đích, mô tả, định nghĩa, ghi chú, kết quả validation và số node/cạnh ảnh hưởng.

Cho phép chỉnh quyết định theo dòng, bao gồm lô hỗn hợp `approve`/`merge`/`reject` trong cùng một bảng. Mọi chỉnh sửa làm mất hiệu lực kết quả kiểm tra cũ và cần kiểm tra lại.

Tổng ảnh hưởng phải đếm ID duy nhất. Một cạnh phụ thuộc nhiều đề xuất không được cộng nhiều lần. Phần xem trước hiển thị cả cạnh bị ảnh hưởng trực tiếp lẫn qua node được đổi loại.

## 5. Validation và quy tắc nghiệp vụ

- Kiểm tra ID tồn tại, thuộc dự án, đúng `kind`, chưa bị xử lý kể từ lúc xem trước.
- Loại ID trùng lặp trong request; từ chối nếu cùng ID có nhiều quyết định mâu thuẫn.
- `approve`: tên chuẩn và định nghĩa không rỗng; catalog vẫn đúng ba trường `name`, `description`, `definition`. Mô tả trống dùng chính sách tương thích hiện có và được hiển thị rõ ở preview.
- Tên chuẩn mới không trùng catalog hoặc một mục mới khác trong lô sau chuẩn hóa Unicode/khoảng trắng/chữ hoa thường. Đánh dấu toàn bộ nhóm xung đột, không mặc định dòng trước thắng.
- `merge`: đích tồn tại trong catalog của **cùng nhóm** tại phiên bản đã xem trước. Bản đầu không cho hợp nhất vào một mục vừa tạo trong chính lô đó để tránh phụ thuộc thứ tự.
- Khi nhiều quyết định tác động cùng node/cạnh theo cách không tương thích, chặn nhóm xung đột để người dùng tách lô hoặc sửa đích. Không lấy quyết định cuối cùng để ghi đè.
- Không tự đảo chiều nguồn–đích khi hợp nhất quan hệ gần nghĩa. Trường hợp cần đảo chiều phải xử lý bằng nghiệp vụ riêng, ngoài phạm vi lô này.
- Điểm tương đồng cao không thay thế quyết định của con người. Nhãn điểm thấp cũng không khẳng định chắc chắn đây là khái niệm mới.
- Duyệt loại thực thể chỉ đổi loại theo phạm vi tham chiếu đề xuất; không gộp node cụ thể.
- Duyệt danh mục **không duyệt bằng chứng**. Cạnh bị ảnh hưởng tiếp tục theo quy tắc hiện có: chuyển về `Cần kiểm tra`, xóa dấu duyệt/ngoại lệ cũ; giữ nguyên cạnh đã `Loại bỏ`.
- Nếu cạnh còn phụ thuộc một đề xuất khác `pending`/`rejected`, tiếp tục chặn duyệt/xuất dù các đề xuất còn lại đã được chấp nhận.
- Từ chối là quyết định kiểm duyệt có thể truy vết, không phải xóa cứng dữ liệu.

## 6. Target Alignment theo phạm vi

Tách rõ hai lệnh:

1. **Làm mới gợi ý:** nhận danh sách ID, chỉ tìm ứng viên. Dùng cho hai bảng mới, không chạy ngầm trên cả dự án.
2. **Chạy chuẩn hóa tự động:** giữ như khả năng riêng nếu cần tương thích, nhưng phải nêu rõ phạm vi ID, số mục và chính sách áp dụng; không dùng chung nhãn với làm mới gợi ý hoặc duyệt của người dùng.

Ứng viên gắn với `catalog_hash` và `model_fingerprint`; khi định nghĩa, danh mục hoặc model thay đổi, đánh dấu gợi ý cũ và yêu cầu kiểm tra lại trước khi dùng nó để áp dụng hàng loạt.

Xử lý từng mục khi không có ứng viên, thiếu model hoặc lỗi gọi dịch vụ: giữ quyết định cũ, báo lỗi tại dòng; không chuyển lỗi thành `reject` hoặc khẳng định “khái niệm mới”. Ghi số mục đã làm mới và số lỗi.

Giữ `auto_aligned`/nguồn quyết định để phân biệt tự động với người duyệt. Các quyết định tự động đã có không được coi là con người đã xác nhận chỉ vì trạng thái đang là `merged`.

## 7. Thiết kế backend và hợp đồng dữ liệu

Các tên sau là API/DTO **đề xuất bổ sung**, không phải chức năng đã tồn tại.

### 7.1. DTO tại `shared/schemas/edc.py`

- `ProposalDecisionDTO`: `proposal_id`, `kind`, `action`, `canonical_name`, `definition`, `description`, `note`.
- `BulkReviewRequestDTO`: `project_id`, `kind`, `expected_revision`, `request_id`, `decisions`, `apply_mode` (`all_or_nothing` hoặc `valid_only`).
- `BulkReviewPreviewDTO`: `preview_id`, `revision`, `catalog_hash`, `request_hash`, tập ID đã chốt, số hợp lệ/lỗi, lỗi từng dòng và tập node/cạnh bị ảnh hưởng.
- `BulkReviewResultDTO`: `batch_id`, `request_id`, `revision_before/after`, số đã áp dụng/không áp dụng, kết quả từng ID, tham chiếu snapshot và trạng thái đồng bộ chỉ mục.

`expected_revision` phải phản ánh trạng thái dự án và catalog đang dùng. Không chỉ dựa vào thời gian trong UI. Preview lưu phía backend hoặc được kiểm tra lại hoàn toàn từ nội dung request; không tin kết quả validation do client gửi.

### 7.2. Domain và Facade

- Thêm `preview_proposal_decisions()` và `apply_proposal_decisions()` tại domain catalog, tái sử dụng quy tắc quyết định đơn.
- Domain làm việc trên bản sao dự án, kiểm tra cả lô trước khi sửa trạng thái chính; không đưa vòng lặp nghiệp vụ và logic xung đột vào frontend.
- Facade cung cấp preview/commit, quản lý snapshot, revision, lưu và đồng bộ repository.
- `FrontendClient` bọc các use-case mới để giao diện không tự ghi JSON/SQLite hoặc sửa trực tiếp `project` rồi lưu từng dòng.
- API REST bổ sung preview, apply và refresh-candidates theo cùng hợp đồng. Local client và REST phải cho kết quả nghiệp vụ tương đương.
- Đề xuất đường dẫn: `POST /api/v1/projects/{name}/edc-review/preview`, `/apply`, `/refresh-candidates`; kiểm tra tên dự án trên URL khớp `project_id` trong request.

### 7.3. Lưu và xử lý lỗi

1. Preview không ghi dự án, không tạo snapshot, không đổi trạng thái đề xuất.
2. Commit nạp phiên bản hiện tại dưới khóa dự án; đối chiếu revision và request hash. Có thay đổi thì yêu cầu xem trước lại.
3. Xác thực lại lô trên backend, tạo một snapshot trước commit, tính trạng thái mới trên bản sao.
4. Lưu `project.json` và hai catalog như một bộ có nhật ký phục hồi/rollback. Không gọi lưu cho từng đề xuất.
5. Với `valid_only`, toàn bộ tập hợp lệ được chốt và lưu trong một commit. Lỗi I/O phải rollback cả tập đó; không được coi là thành công một phần do ghi dở.
6. Xác định JSON là nguồn phục hồi chính, SQLite là bản đồng bộ có thể dựng lại. SQLite dùng transaction; nếu JSON đã commit nhưng SQLite lỗi, trả rõ `committed` kèm `sync_pending`, ghi yêu cầu đồng bộ lại và không báo lỗi khiến client áp dụng lặp quyết định.
7. Catalog thay đổi làm chỉ mục vector cũ hết hiệu lực theo hash. Có thể dựng lại khi cần; không dùng chỉ mục cũ cho catalog mới, không đảo quyết định đã lưu vì embedding tạm lỗi.
8. Lưu `request_id` và kết quả theo lô để nhấn đúp, timeout hoặc retry không tạo quyết định/snapshot lặp. Cùng ID nhưng khác nội dung request phải bị từ chối.
9. Chỉ cập nhật trạng thái phiên giao diện từ kết quả đã commit. Khi lỗi lưu, giữ bản nháp để sửa/thử lại.

## 8. Lịch sử, khôi phục và dữ liệu huấn luyện

- Mỗi quyết định vẫn có `before`, `after`, `impact`, thời điểm; bổ sung `batch_id`, `request_id`, `decision_origin`, người/phiên thao tác nếu hệ thống có định danh tương ứng.
- Lô có bản tóm tắt: phạm vi lọc, tập ID, số duyệt mới/hợp nhất/từ chối và số chưa xử lý.
- “Xem lịch sử lô” cho phép đi tới từng đề xuất và snapshot liên quan.
- Khôi phục snapshot là khôi phục toàn dự án tại thời điểm đó. UI phải hiển thị phạm vi ảnh hưởng; bản đầu không hứa hỗ trợ hoàn tác chọn lọc một lô sau khi có các thay đổi mới.
- Khôi phục phải đồng bộ lại SQLite và vô hiệu hóa chỉ mục vector nếu catalog đổi.
- Active Learning chỉ nhận nhãn con người từ quyết định đã commit; không lấy bản nháp, preview, request lỗi hoặc bản đã bị thay thế làm nhãn mới.
- Từ chối một đề xuất không mặc định là một cặp chuẩn hóa âm cụ thể; chỉ xuất negative pair khi có đích so sánh và lý do tương ứng.
- Rà soát exporter hiện có: việc bằng chứng xuất hiện trong nguồn không thay thế trạng thái con người đã duyệt. Không dùng tính năng duyệt hàng loạt để biến tự động hợp nhất thành nhãn người dùng.

## 9. File dự kiến thay đổi

| File | Thay đổi dự kiến |
| --- | --- |
| `frontend/pages/p04_edc_alignment.py` | Bố trí hai bảng, tổng quan và kết quả lô. |
| `frontend/components/edc_alignment_panel.py` | Giữ cấu hình EDC+R; tách phần duyệt sang component mới, bảo toàn chức năng đang dùng ở trang 2. |
| `frontend/components/edc_review_table.py` — mới | Component dùng chung cho từng `kind`: lọc, chọn, phân trang, mở chi tiết. |
| `frontend/components/edc_bulk_actions.py` — mới | Bản nháp quyết định, xem trước, áp dụng toàn bộ/phần hợp lệ và báo cáo lỗi. |
| `frontend/state/session.py` | State theo `project_id` + `kind`; lưu ID lựa chọn và bản nháp qua rerun. |
| `frontend/client.py` | Wrapper preview/apply/refresh theo phạm vi. |
| `shared/schemas/edc.py` | DTO lô và metadata tương thích dữ liệu cũ. |
| `backend/domain/catalogs/service.py` | Validation lô, tác động trực tiếp/gián tiếp và quyết định nhất quán. |
| `backend/domain/schema_intelligence/aligner.py` | Nhận tập ID; tách gợi ý khỏi tự động áp dụng. |
| `backend/facade.py`, `backend/api/v1.py` | Điều phối use-case, revision, idempotency và REST. |
| `backend/repositories/json_repo.py`, `sqlite_repo.py`, `vector_repo.py` | Commit bộ file, phục hồi, báo lỗi đồng bộ và invalidation theo catalog. |
| `backend/domain/dataset_exporter/exporter.py` | Nhận diện nguồn quyết định, chỉ dùng nhãn hợp lệ đã commit. |
| `tests/` | Kiểm thử domain, API, UI và lỗi lưu/khôi phục. |
| `AI/structure.md`, `README.md` | Cập nhật sau khi triển khai và kiểm thử hoàn tất. |

Không import hoặc sao chép phụ thuộc runtime từ `KG_Studio_MVP`; giữ kiến trúc độc lập của `KG_Studio`.

## 10. Thứ tự triển khai

1. **Chốt DTO và validation:** phạm vi ID, trạng thái, đích, xung đột trong lô, chính sách toàn bộ/phần hợp lệ.
2. **Hoàn thiện commit:** revision, khóa, idempotency, snapshot, rollback nhóm JSON và trạng thái đồng bộ SQLite. Đây là điều kiện trước khi bật nút áp dụng hàng loạt.
3. **Tách hai bảng:** bộ lọc, ID lựa chọn, phân trang và state độc lập; giữ xem chi tiết/duyệt đơn.
4. **Thêm bản nháp và preview:** duyệt mới, hợp nhất theo đích riêng/chung, từ chối, áp dụng phần hợp lệ.
5. **Giới hạn Target Alignment theo lựa chọn:** refresh-only, nhận diện gợi ý cũ và lỗi từng dòng.
6. **Lịch sử và exporter:** ghi nhận lô, khôi phục, phân biệt nhãn con người/tự động.
7. **Kiểm thử, nghiệm thu và tài liệu:** chạy offline với mock LLM/embedder; không gọi dịch vụ thật để kiểm thử thao tác chọn/duyệt.

## 11. Tiêu chí nghiệm thu

- [x] Trang 4 có hai bảng độc lập, phân loại đúng `entity_types` và `relations`.
- [x] Chọn một/nhiều/tất cả kết quả lọc hoạt động theo ID, kể cả sau sắp xếp và đổi trang.
- [x] Đổi bộ lọc không tác động mục bị ẩn; đổi dự án không mang theo lựa chọn cũ.
- [x] Rerun sau thao tác giữ trang 4 và trạng thái bộ lọc; thông báo kết quả không biến mất ngay.
- [x] Duyệt toàn bộ dùng tên/định nghĩa riêng của từng mục, không gộp tất cả vào một mục mới.
- [x] Với 12 mục có 3 lỗi, `all_or_nothing` không lưu; `valid_only` chỉ lưu đúng 9 mục sau khi người dùng chọn rõ.
- [x] Hợp nhất nhiều mục vào cùng đích hoặc các đích khác nhau đúng nhóm; không tự chọn Top-1 để commit.
- [x] Chặn thiếu định nghĩa, đích đã bị xóa, ID sai dự án, ID trùng có quyết định khác nhau và nhóm tên mới trùng nhau.
- [x] Chặn quyết định xung đột trên cùng node/cạnh; đếm ảnh hưởng gián tiếp và khử trùng ID.
- [x] Duyệt đề xuất không tự duyệt/xuất cạnh; cạnh còn phụ thuộc đề xuất chưa xử lý vẫn bị chặn.
- [x] Từ chối giữ được đối tượng, bằng chứng và lịch sử; không xóa cứng dữ liệu.
- [x] Làm mới gợi ý chỉ chạy trên ID đã chọn và không đổi trạng thái quyết định.
- [x] Hai phiên cùng sửa, thay catalog/model sau preview và nhấn đúp đều có hành vi xác định, không ghi đè hoặc áp dụng hai lần.
- [x] Giả lập lỗi giữa các lần ghi JSON khôi phục bộ file cũ; lỗi SQLite sau commit được báo là chờ đồng bộ, có thể chạy lại đồng bộ.
- [x] Một lô commit thành công có snapshot và audit đầy đủ; khôi phục đồng bộ được JSON, SQLite và trạng thái chỉ mục.
- [x] Exporter không nhầm quyết định tự động, preview hoặc trích dẫn khớp với nhãn con người đã duyệt.
- [x] Luồng duyệt đơn, cấu hình trang 2 và các dự án cũ vẫn hoạt động; dữ liệu không bị di chuyển ngoài chủ đích.

**Lệnh kiểm thử sau triển khai:** `python -m unittest discover -s tests -t . -v` từ thư mục `KG_Studio`.
