# Kế hoạch cải tiến UI/UX KG Studio

Ngày lập: 2026-11-13. Trạng thái: **đề xuất triển khai, chưa thực hiện thay đổi UI**.

## 1. Mục tiêu và phạm vi

Người dùng không chuyên về lập trình/AI có thể nhập tư liệu, tạo dữ kiện, kiểm tra bằng chứng và khám phá kết quả mà không cần hiểu prompt, token hoặc thuật toán truy xuất. Người nghiên cứu vẫn truy cập được cấu hình, lịch sử và thí nghiệm đầy đủ.

Đầu vào chính: [đặc tả hiện trạng](current_ui_layout_spec.md), [quy tắc dự án](../../AGENTS.md), [bản đồ kiến trúc](../structure.md). Các đường dẫn implementation dưới đây là điểm bắt đầu kiểm chứng, không phải chỉ thị thay thế nguyên file.

Đánh giá hiện trạng dựa trên đặc tả, chưa quan sát trình duyệt hay thử với người dùng. Đã đọc `pyproject.toml`, `.streamlit/config.toml`, renderer `frontend/components/graph_view.py` và metadata Streamlit trong `.venv-win`. Graphify CLI không có trong PATH; đường dẫn executable đã biết ở lượt trước cũng không khả dụng. Đã dùng graph JSON có phạm vi để định vị app, renderer và manifest package. Không suy luận caller hoặc xóa source từ việc thiếu cạnh graph.

Đợt này chỉ lập tài liệu. Không đổi thuật toán, prompt, schema lưu trữ, engine registrations, API hoặc dữ liệu dự án. Không thêm entity resolution hay phương pháp trích xuất mới trong một đợt chỉnh UI.

## 2. Hướng thiết kế thống nhất

**Giao diện công cụ nghiên cứu gọn, rõ, hướng dẫn theo nhiệm vụ; hiển thị tính năng nâng cao theo nhu cầu.**

- Giữ 5 bước và khả năng quay lại; đây không phải wizard khóa người dùng vào một thứ tự cứng.
- Sidebar là điều hướng chính. Header chỉ tóm tắt dự án, bước hiện tại, trạng thái; bỏ hệ nút điều hướng trùng sau khi kiểm tra callers/state.
- Một hành động chính nổi bật trong vùng công việc đang hoạt động. Điều hướng bước tiếp theo là phụ khi công việc hiện tại chưa hoàn thành.
- Mỗi màn hình trả lời: đang làm gì, trên dữ liệu nào, kết quả ở đâu, việc tiếp theo là gì.
- Nền trung tính, một màu nhấn, ít viền trang trí. Màu trạng thái luôn có chữ/icon giải thích; không dùng màu làm tín hiệu duy nhất.
- Typography khởi điểm: chữ thân khoảng 16 px, line-height 1.5–1.65; khoảng cách theo thang 4/8/12/16/24/32 px. Đây là token thiết kế cần thử, không phải chuẩn khoa học bắt buộc.
- Form chủ yếu 1–2 cột; không chia 4–5 cột input chỉ để tiết kiệm chiều cao. Nội dung đọc có độ rộng vừa phải, bảng có thể rộng toàn vùng.
- Desktop là ưu tiên đầu tiên. Kiểm tra 1280/1440 px và cửa sổ hẹp 768/390 px; vùng đọc/form chuyển một cột. Bảng/đồ thị có thể cần cuộn riêng, không kéo tràn toàn trang.
- Không mở mọi chức năng bằng expander lồng nhau. Dùng khu Nâng cao/Nghiên cứu có mục đích rõ, nhớ lựa chọn hiển thị nhưng không tự thay cấu hình nghiệp vụ.

### Ngôn ngữ và tính trung thực

| Hiện trạng/thuật ngữ | Cách trình bày đề xuất |
| --- | --- |
| Node / Edge | Đối tượng / Quan hệ; giải thích thuật ngữ kỹ thuật khi cần |
| Chunk / Run | Đoạn văn / Lần xử lý; ID nằm ở chi tiết |
| Schema | Danh mục loại đối tượng và quan hệ (schema) |
| Lưu TOML | Lưu cấu hình; hiển thị rõ phạm vi áp dụng thực tế |
| Preview / Apply | Xem trước thay đổi / Áp dụng thay đổi |
| Integrity | Kiểm tra cấu trúc; không diễn giải là chính xác lịch sử |
| Approved | Đã được người dùng duyệt; không gọi là sự thật được xác minh độc lập |
| Baseline | Đồ thị thô từ AI — baseline B, chưa chuẩn hóa ngữ nghĩa |

Tên phương pháp kỹ thuật được giữ trong khu nghiên cứu và metadata xuất. Câu trả lời AI phải có nguồn/bằng chứng liên quan và thể hiện khi không đủ dữ liệu; không nâng mức tin cậy chỉ bằng màu xanh.

## 3. Quy trình giao việc cho AI Agent

Mỗi đợt phải: đọc AGENTS → query graph hoặc fallback được quy định → kiểm chứng source liên quan → ghi hiện trạng và tiêu chí → triển khai giới hạn → kiểm thử → cập nhật tài liệu và graph sau code changes.

Không đánh dấu một đợt hoàn thành chỉ vì đã dựng component. Báo cáo phải có: file sửa, thay đổi hành vi, bằng chứng nghiệm thu, lệnh/kết quả test, ảnh các trạng thái chính, hạn chế và việc còn lại. Khi chưa có người dùng thử, ghi “chưa xác minh usability”.

### Đợt U0 — Kiểm kê và thiết kế trước triển khai

**Đầu vào:** đặc tả hiện trạng, source và runtime hiện tại, fixtures không chứa dữ liệu thật.

**Công việc:**
1. Chụp hiện trạng 5 bước cho dự án rỗng, đã có tài liệu, đang có kết quả/lỗi; đối chiếu mô tả với app.
2. Lập ma trận chức năng → màn hình hiện tại → màn hình đích; không để tính năng mất nơi truy cập.
3. Kiểm kê session keys, selection IDs, draft, pagination, return context và phạm vi cấu hình global/project/run.
4. Tạo wireframe cho 5 bước, trạng thái rỗng/lỗi/đang xử lý/thành công và bộ nhãn thống nhất.
5. Đo thời gian, lỗi, số lần cần trợ giúp trên các nhiệm vụ ở mục 6 làm mốc trước cải tiến.

**Đầu ra:** `ui-ux-state-inventory.md`, `ui-ux-wireframes.md`, baseline usability có dữ liệu đo hoặc đánh dấu chưa đo, lưu trong `AI/layout/`.

**Gate:** mọi capability hiện tại có nơi truy cập; mọi thao tác ghi có owner application; không có hành vi mới bị ngụy trang thành thay đổi trình bày.

### Đợt U1 — Khung chung, theme và điều hướng

**Đầu vào:** U0; `frontend/app.py`, `pipeline_banner.py`, `frontend/state/session.py`, `.streamlit/config.toml`.

**Công việc:** tạo theme/token thống nhất; sidebar giữ chọn dự án, 5 bước và tóm tắt kết nối. Tách “Mở dự án” và “Tạo dự án” thành hành động rõ. Gom cấu hình kết nối về một nơi chỉnh sửa; các trang khác chỉ tóm tắt và dẫn tới đó. Header không tạo thêm bộ nút 5 bước cạnh tranh. Chuẩn hóa thông báo lỗi có nguyên nhân dễ hiểu và hành động khắc phục.

Tạo helper UI chỉ khi có nhiều consumer cùng semantics. Ưu tiên theme và widget chính thức; CSS chỉ áp dụng có phạm vi, tránh phụ thuộc class DOM sinh tự động. Không đưa secrets vào ảnh/test fixtures.

**Đầu ra:** shell thống nhất, theme, bộ nhãn, bản đồ di chuyển/migrate state.

**Gate:** đổi trang không mất draft/selection hợp lệ; đổi dự án không rò state dự án cũ; nhận biết bước hiện tại không phụ thuộc màu; không có hai nơi chỉnh cấu hình thiếu đồng bộ.

### Đợt U2 — Bước 1: Thêm và kiểm tra tài liệu

**Đầu vào:** U1; `p01_projects_docs.py` và application APIs tương ứng.

**Công việc:** thể hiện chọn tệp → xem tình trạng đọc → thêm vào dự án. Tài liệu lỗi có cảnh báo ngay cạnh tên. Bảng mặc định ưu tiên tên, trạng thái và nguồn; số ký tự/đoạn và metadata khác đưa vào chi tiết. Không dùng trạng thái “đã thêm” cho tệp mới chọn nhưng chưa lưu. Preview dài phải ghi rõ phần đang hiển thị bị giới hạn.

**Đầu ra:** màn hình tài liệu có empty state, kết quả từng tệp, preview và đường đi tiếp rõ ràng.

**Gate:** thử nhiều file gồm thành công/thất bại; không mất file thành công hoặc báo tất cả thành công sai; không tạo bản ghi chỉ vì rerun. Nếu API chưa hỗ trợ xem trước trước khi nhập, dùng kiểm tra sau nhập hoặc tách use case mới thành phạm vi riêng, không tự nhét parsing/ghi vào UI.

### Đợt U3 — Bước 2: Chọn phương pháp và thiết lập

**Đầu vào:** U1; `p02_catalogs_prompts.py`, `prompt_editor.py`, `gazetteer_panel.py`, `ml_lab_panel.py`.

**Công việc:** mô tả mỗi engine bằng mục đích, đầu ra, yêu cầu và giới hạn; giữ đúng 4 registrations hiện tại. Hiện rõ phương pháp đang áp dụng và lựa chọn chưa áp dụng. Prompt/request/hash/version và EDC+R parameters vào Nâng cao. Danh mục/từ điển chỉ được trình bày như có tác dụng khi engine thực sự sử dụng chúng. ML Lab chuyển sang mục Nghiên cứu độc lập với đường cơ bản, giữ đường truy cập và trạng thái.

**Đầu ra:** lựa chọn dễ hiểu; cấu hình đang dùng được tóm tắt; quản lý danh mục/từ điển một nơi duy nhất.

**Gate:** chuyển tab không áp dụng engine/prompt nháp; prepared request vẫn đúng cấu hình đã pin; baseline không bị áp dụng schema/từ điển vì người dùng đã nhập chúng ở UI. Không chọn phương pháp mặc định “tốt nhất” nếu chưa có bằng chứng phù hợp.

### Đợt U4 — Bước 3: Chạy và theo dõi trích xuất

**Đầu vào:** U2–U3; `p03_extraction.py`, `step_traces_viewer.py`.

**Công việc:** luồng chính chọn tài liệu → xem phạm vi → chạy thử hoặc chạy phần đã chọn → xem kết quả. Chunk/overlap/workers/token vào Nâng cao. Tóm tắt số tài liệu/đoạn, phương pháp và cấu hình đang dùng. Ghi rõ chạy thử có gọi LLM, phát sinh chi phí hoặc ghi kết quả hay không dựa trên implementation. Đưa trace/raw JSON vào chi tiết kỹ thuật.

Progress phản ánh dữ liệu thực, không tạo phần trăm giả; chỉ ước tính chi phí khi có đủ giá và token, gắn nhãn ước tính. Không thêm nút dừng/retry nếu backend chưa bảo đảm semantics; tách thành use case riêng nếu cần.

**Đầu ra:** trạng thái chờ/đang chạy/thành công một phần/lỗi rõ; đường tới rà soát hoặc KG baseline phù hợp engine.

**Gate:** rerun/nhấn lặp không vô tình chạy lại; lỗi từng đoạn không bị che; lịch sử và attempt provenance giữ nguyên; baseline được đến bước 5 mà không giả lập phê duyệt bước 4.

### Đợt U5 — Bước 4: Kiểm chứng và chuẩn hóa

**Đầu vào:** U1, U4; `p04` và components curation/evidence/EDC/merge được đặc tả định vị.

**Công việc:**
1. Mặc định hàng đợi cần kiểm tra, giải thích bộ lọc đang active; giữ hai bảng EDC.
2. Phân biệt chọn một mục để xem với checkbox chọn nhiều mục để áp dụng lô. Chọn dòng phải ánh xạ sang ID, không dùng số thứ tự làm định danh sau sort/filter.
3. Bằng chứng và dữ kiện ở cạnh nhau trên màn hình rộng, xếp dọc trên màn hình hẹp. Có Mục trước/Mục tiếp theo; vị trí bằng chứng mơ hồ phải được thể hiện.
4. Quyết định Duyệt/Cần kiểm tra/Từ chối nằm gần bằng chứng; chỉnh sửa và lịch sử là chức năng phụ.
5. Gộp theo chọn mục → xem tác động → áp dụng. Hiện rõ đối tượng giữ lại, dữ liệu bị ảnh hưởng và tác động từ điển. AI gợi ý không tự trở thành quyết định người dùng.
6. Thao tác lô hiển thị số đã chọn và phạm vi “trang này/toàn bộ bộ lọc”; preview và thông báo kết quả giữ đúng all_or_nothing/valid_only.

**Đầu ra:** bàn rà soát dùng chung mẫu tương tác; luồng gộp minh bạch; không mất công cụ chuyên sâu.

**Gate:** filter/pagination không đổi sai đối tượng; trở về từ đề xuất schema giữ return context; stale preview bị chặn; giữ provenance/history/aliases/redirects; không có mutation khi chỉ xem trước. Hành động phá hủy phải có xác nhận tác động cụ thể, không thêm confirm cho mọi click vô hại.

### Đợt U6 — Bước 5: Khám phá, hỏi đáp và nghiên cứu

**Đầu vào:** U4–U5; `p05_graph_export.py`, `graph_source.py`, `graph_view.py`, `export_tabs/*`.

**Công việc:**
1. Luôn hiện nguồn graph, trạng thái kiểm duyệt và phạm vi dữ liệu. Dùng chung GraphSnapshotDTO và giao diện cho approved/baseline/external.
2. Baseline chọn theo tài liệu → đoạn → lần xử lý có metadata dễ đọc. Có nhiều attempts thì yêu cầu chọn rõ; không tự chọn “tốt nhất”, không trộn nhiều attempt cùng đoạn trái policy.
3. Khám phá bắt đầu từ tìm đối tượng/câu hỏi, mở quan hệ liên quan và bằng chứng. Có bảng tương đương để sử dụng bằng bàn phím; không ép người mới đọc toàn bộ graph dày đặc.
4. Thuật toán/KPI chi tiết/so sánh/benchmark/training chuyển vào Nghiên cứu. Cấu hình ẩn vẫn được tóm tắt, không âm thầm đổi thuật toán.
5. Giữ phân biệt benchmark với gold độc lập và demo câu hỏi tự sinh; giữ metadata/fingerprint/dataset/budget khi xuất kết quả.
6. Nêu rõ giới hạn hiển thị không cắt dữ liệu export. External graph tự khai báo approved không được phép thao tác training/export project hiện tại.

**Đầu ra:** cùng một luồng khám phá cho mọi nguồn; nghiên cứu có thể truy cập đầy đủ; xuất dữ liệu đúng phạm vi.

**Gate:** đổi nguồn làm vô hiệu kết quả cũ phù hợp fingerprint; không fallback sang graph khác khi nguồn rỗng/lỗi; baseline vẫn là dữ liệu thô, không biến thành nhãn huấn luyện đã duyệt.

**Hai mức đồ thị:** mức bắt buộc dùng Graphviz hiện có + tìm kiếm/bảng/chọn đối tượng bên ngoài graph. Mức tùy chọn mới là click node mở hồ sơ, kéo thả, mở rộng lân cận trực tiếp. Mức tùy chọn cần spike riêng; không hứa có sẵn chỉ bằng đổi CSS.

### Đợt U7 — Kiểm thử và nghiệm thu toàn bộ

**Đầu vào:** U1–U6, fixtures, baseline U0.

**Đầu ra:** `ui-ux-acceptance-report.md`, ảnh trước/sau, kết quả test, dữ liệu usability đã ẩn danh, danh sách hạn chế. Cập nhật đặc tả hiện trạng sau implementation, không sửa thành hiện trạng ngay khi mới có kế hoạch.

**Gate:** đạt mục 6; chạy suite offline và architecture checks bằng interpreter dự án; graphify update sau source changes theo AGENTS. Lỗi tool/runtime phải được ghi, không báo PASS thay cho phần chưa chạy.

## 4. Thư viện hiện tại và quyết định công nghệ

Kiểm chứng ngày lập kế hoạch:

- `pyproject.toml`: `streamlit>=1.38.0,<2.0.0`, `graphviz>=0.20.3,<1.0.0`.
- Metadata `.venv-win/Lib/site-packages/streamlit-1.66.1.dist-info/METADATA`: 1.66.1. Đây là package trong venv, chưa chứng minh tiến trình server đang mở dùng interpreter đó.
- `.streamlit/config.toml` chỉ có cấu hình ẩn navigation mặc định, chưa có theme riêng.
- Renderer hiện tại sinh DOT dùng node IDs; màu node hiện hardcode, cần kiểm tra cả light/dark khi chỉnh theme.

| Nhu cầu | Khả năng và quyết định |
| --- | --- |
| Màu/font/viền, bố cục, bảng, form, trạng thái, ẩn cấu hình nâng cao | Streamlit hiện có đủ nền tảng; không cần thêm UI framework để bắt đầu |
| Chọn mục mở chi tiết | Dùng selection/table/widget hiện có; kiểm tra API của bản cài, giữ ID semantics |
| Đồ thị minh họa, sơ đồ con theo bộ lọc | Graphviz hiện có đủ; vẫn cần tối ưu số phần tử và bảng thay thế |
| Click node trả sự kiện về Python, kéo thả và khám phá graph chuyên sâu | Renderer hiện có chưa cung cấp luồng này; cần component có event contract hoặc custom component được đánh giá riêng |
| Responsive tùy biến hoàn toàn, animation phức tạp, trải nghiệm như canvas editor | Không phải thế mạnh mặc định của Streamlit; chỉ cân nhắc frontend riêng nếu là yêu cầu bắt buộc đã đo và chứng minh |

**Quyết định:** giữ Streamlit, chưa nâng framework/chưa thêm dependency trong các đợt cơ bản. Tài liệu web có thể mới hơn 1.66.1; Agent phải kiểm tra API thực tế trước dùng. Dải version khai báo khá rộng, không được giả định mọi API hiện có hoạt động trên bản tối thiểu 1.38; xử lý tương thích hoặc đề xuất chỉnh minimum version trong thay đổi dependency riêng.

Nếu cần component graph mới: chứng minh event node/edge ID → inspector, Unicode và cạnh trùng, hiệu năng theo quy mô thật, keyboard fallback, theme, giấy phép, bảo trì, hoạt động offline và không tải dữ liệu sang dịch vụ ngoài ngoài ý muốn. Giữ cùng snapshot/application APIs; thay renderer không viết lại pipeline KG. Không cài nhiều thư viện trang trí để giải quyết lỗi tổ chức thông tin.

## 5. Bảo toàn kiến trúc và dữ liệu

- UI gọi public application APIs qua composition/client; không thêm nghiệp vụ vào facade hoặc tự tạo repositories.
- Không thay commit coordinator, khóa/revision/idempotency, snapshot và policy lưu trong đợt giao diện.
- Preview chỉ đọc; apply kiểm tra lại trạng thái. Không dùng thao tác đổi trang để tự lưu bản nháp.
- Giữ API/registrations/export, prompt pinning, token accounting và provenance. Không dùng mẫu dữ liệu thật chứa key để test.
- Trước xóa UI/helper cũ phải audit callers/imports/dynamic registrations/test seams; ghi deletion ledger: symbol, consumers, thay thế, điều kiện tương thích và kết quả tests. Không xóa test chỉ để xanh suite.
- Nếu thay session keys phải có mapping/migration rõ; thay layout không là lý do đổi toàn bộ keys.
- Không cam kết undo nếu backend chỉ có khôi phục snapshot với phạm vi khác; mô tả đúng tác động của khôi phục.

## 6. Đo chất lượng và tiêu chí kết quả

### Nhiệm vụ thử nghiệm

1. Tạo/mở dự án, thêm hai tài liệu và nhận diện một tệp đọc lỗi.
2. Chọn phương pháp, chạy thử, chỉ ra cấu hình thực sự được áp dụng.
3. Tìm một dữ kiện, mở bằng chứng, duyệt hoặc từ chối có lý do.
4. Xem trước gộp, giải thích tác động, hủy mà dữ liệu không đổi.
5. Tìm thông tin trong graph và chỉ ra nguồn hỗ trợ.
6. Chọn KG baseline, nhận biết khác với KG đã duyệt, xuất đúng nguồn.

Vòng tìm vấn đề: 5–8 người không chuyên lập trình/AI, có thể hiểu nội dung tư liệu. Ghi background, nhiệm vụ, thành công/không, thời gian, số lần trợ giúp, lỗi và mức dễ dùng tự đánh giá. Không khái quát tỷ lệ của mẫu nhỏ thành kết luận thống kê cho mọi người dùng.

So trước/sau bằng nhiệm vụ tương đương và cùng dữ liệu/độ khó; đổi thứ tự hoặc dùng nhóm tương đương để giảm hiệu ứng học. Thời gian thao tác người dùng phải tách khỏi thời gian chờ LLM. Nếu cần khẳng định thống kê, thiết kế mẫu và phân tích riêng.

### Mục tiêu nghiệm thu đề xuất, chưa phải kết quả đạt được

| Nhóm | Tiêu chí |
| --- | --- |
| Dễ học | Ít nhất 80% lượt thực hiện từng nhiệm vụ cốt lõi thành công không cần người hướng dẫn; báo cả số tuyệt đối và tỷ lệ |
| Dễ hiểu | Ít nhất 80% người thử phân biệt được AI đề xuất, đã duyệt và đúng cấu trúc qua câu hỏi kiểm tra; mọi hiểu nhầm gây quyết định nguy hiểm phải sửa |
| Hiệu quả | So baseline U0 về thời gian trung vị, lỗi và trợ giúp; không đặt phần trăm cải thiện giả khi chưa có baseline |
| Toàn vẹn | Không có lỗi ghi sai dự án/đối tượng/nguồn graph, mất draft ngoài ý muốn hoặc mutation khi preview trong các ca kiểm thử |
| Accessibility | Kiểm tra bàn phím/focus/label và trạng thái không chỉ bằng màu; chữ thường tương phản tối thiểu 4.5:1, chữ lớn 3:1 theo WCAG; kiểm tra reflow/zoom và ngoại lệ hợp lý cho bảng/graph |
| Tương tác | Mục tiêu nút thuận tiện khoảng 40–44 px khi phù hợp; tối thiểu/ngoại lệ target size đánh giá theo WCAG 2.2, không gọi 44 px là yêu cầu AA chung |
| Hồi quy | Test UI state và application contracts phù hợp; full offline suite + architecture checks trước chốt đợt refactor; không lấy báo cáo PASS cũ làm bằng chứng |
| Hiệu năng | Cùng fixture/environment, đo rerun/render/graph với cỡ dữ liệu đại diện; hồi quy p95 hoặc peak memory >10% điều tra và ghi tradeoff |

AppTest kiểm chứng hành vi/state nhưng không thay kiểm tra trình duyệt về bố cục, focus, tương phản và responsive. Test live provider/Neo4j chỉ opt-in; không chạy live để chứng minh giao diện đẹp.

## 7. Nguồn tham chiếu và giới hạn kết luận

- [NN/g — Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/): cơ sở cho việc chỉ hiện cấu hình cần thiết theo ngữ cảnh.
- [NN/g — 10 Usability Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/): trạng thái hệ thống, nhất quán, ngôn ngữ người dùng, phòng lỗi và quyền kiểm soát.
- [W3C — WCAG 2.2](https://www.w3.org/TR/WCAG22/): căn cứ accessibility; không tuyên bố đạt toàn bộ WCAG chỉ từ vài phép kiểm tra.
- [Streamlit — Theming](https://docs.streamlit.io/develop/concepts/configuration/theming): khả năng tùy chỉnh theme chính thức.
- [Streamlit — Dataframe](https://docs.streamlit.io/develop/api-reference/data/st.dataframe): bảng và selection, phải đối chiếu version cài.
- [Streamlit — Graphviz chart](https://docs.streamlit.io/develop/api-reference/charts/st.graphviz_chart): renderer DOT; không coi là graph editor có application callbacks.

Các nguyên tắc trên tạo cơ sở đề xuất. Tính phù hợp với KG Studio phải được chứng minh bằng kiểm thử nhiệm vụ và đo thực tế. Chưa thực hiện usability study, kiểm thử trực quan hay đo hiệu năng trong đợt chỉ viết kế hoạch này.
