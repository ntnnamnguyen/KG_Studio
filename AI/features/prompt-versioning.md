# Plan: Prompt theo cấu hình và lịch sử phiên bản

- **Ngày:** 31/10/2026.
- **Trạng thái:** Hướng dẫn triển khai; tài liệu này chưa thay đổi mã nguồn ứng dụng.
- **Phạm vi:** `KG_Studio`, bước Thiết lập và Trích xuất; lưu prompt theo dự án, cấu hình, phiên bản; xem trước request và truy vết lượt gửi.
- **Căn cứ:** [structure.md](../structure.md), [đề xuất pipeline](../report/layout-pipeline-proposal.md), [báo cáo hiệu năng](../report/performance-optimization.md), mã nguồn hiện tại.
- **Nguyên tắc:** Dùng lại lưu trữ, facade, engine và LLM gateway hiện có; không xây thêm một hệ thống prompt song song.

## 1. Kết quả người dùng cần nhận được

1. Mỗi dự án sở hữu prompt riêng, không bị sửa theo dự án khác hoặc cấu hình mặc định toàn ứng dụng.
2. Chọn cấu hình nào thì chỉ hiện editor và lịch sử của prompt thuộc cấu hình đó.
3. Sửa rồi lưu tạo một phiên bản mới; giữ phiên bản cũ để xem, so sánh và sử dụng lại.
4. Xem trước được prompt đã ghép hoàn chỉnh cho đoạn tài liệu được chọn, kể cả catalog/schema retrieval, user message và giới hạn đầu ra đang áp dụng.
5. Nội dung thực tế gửi LLM có dấu vết phiên bản/request; không hiển thị một bản xem trước rồi âm thầm gửi một bản khác.
6. Chạy lại hoặc xem lịch sử biết được prompt nào từng dùng. Khôi phục prompt không khôi phục nhầm catalog hoặc toàn bộ dự án.

### Hiểu “mỗi cấu hình một prompt” trong đợt đầu

Mã hiện tại chưa có hệ cấu hình có tên/ID độc lập. Đợt đầu dùng ba ID cấu hình sẵn có từ `shared/constants.py`: **`closed`, `edc`, `edc_plus_r`**. Đây là khóa ổn định; nhãn giao diện có thể đổi.

- `closed`: prompt hướng dẫn cho chế độ danh mục cố định.
- `edc`: prompt hướng dẫn cho chế độ trích xuất mở.
- `edc_plus_r`: prompt hướng dẫn cho trích xuất mở có gợi ý catalog; lưu riêng dù ban đầu nội dung có thể giống EDC.

Đổi model/provider/Top-K không tự tạo một cấu hình hoặc phiên bản prompt mới. Những tham số đó đi vào snapshot cấu hình và request hash của lượt chạy. Nếu lúc triển khai đã có named configuration/profile thì dùng ID profile thật và ràng buộc với mode; không tạo thêm bảng profile thứ hai. Việc cho người dùng tự tạo nhiều cấu hình có tên là mở rộng riêng, không bắt buộc để hoàn thành yêu cầu này.

## 2. Hiện trạng và khoảng trống đã xác minh

| Vị trí | Hiện trạng | Hệ quả cần xử lý |
| --- | --- | --- |
| `json_repo.py::empty_project` | Có `prompt`, `edc_prompt`, `prompt_versions`; dữ liệu thuộc project JSON | Có nền tảng lưu theo dự án, chưa có binding prompt riêng cho ba cấu hình |
| `catalogs/service.py::save_prompt_settings` | Lưu trạng thái cũ của prompt/catalog vào `prompt_versions`, rồi cập nhật prompt cố định và hai catalog | Lịch sử prompt và lịch sử catalog đang gộp; chưa có vòng đời version độc lập |
| `edc_alignment_panel.py::render_edc_mode_settings` | Ghi trực tiếp `project['edc_prompt']` và dùng chung cho EDC/EDC+R | Đổi một prompt có thể tác động hai chế độ; chưa version đầy đủ |
| `p02_catalogs_prompts.py` | Có editor/chức năng lưu cho cấu hình EDC và một vùng prompt cố định riêng | Người dùng có thể thấy prompt không thuộc cấu hình đang chọn; nhiều đường ghi phải được thống nhất |
| `shared/catalog_utils.py::edc_prompt`, `EDC_SCHEMA` | Ghép hướng dẫn với hợp đồng JSON bắt buộc | Phải giữ cùng hợp đồng cho preview và execution, tránh người dùng vô tình sửa hỏng schema |
| `fixed_catalog.py`, `edc_one_pass.py` | Gọi `extraction_prompt()` và gateway | Có thể tái sử dụng resolver prompt chung |
| `edc_plus_r.py` | Tự đọc `edc_prompt`, ghép schema retrieval và hints theo từng vòng | Prompt cuối thay đổi theo chunk/vòng, không thể preview chính xác chỉ bằng base prompt |
| `llm/gateway.py::extract` | Fit chunk theo input budget, clamp output, dựng user message và chọn response format trước gọi adapter | Preview ở UI nếu tự ghép sẽ lệch request thực tế |
| `llm/clients.py` | Chuyển system/user sang định dạng provider, thêm tùy chọn và có fallback response_format | Phải hiển thị đúng loại request và ghi fallback, không sao chép client transport vào UI |
| `facade.py::extract_chunk` | Tính lại `prompt_id` sau engine; run record và engine có cách tính signature khác nhau | Một ID hiện tại chưa đủ chứng minh đúng prompt động đã gửi |
| `dataset_exporter/exporter.py` | SFT record lấy `project.get('prompt')` hiện hành | Có thể gán prompt hiện tại cho dữ liệu sinh từ phiên bản/mode khác; cần dùng provenance có thật |

`prompt_signature` hiện nhận hướng dẫn và danh sách tên quan hệ; giữ khả năng đọc ID cũ, nhưng không dùng một signature ngắn như toàn bộ mô hình version/request mới.

## 3. Thiết kế giao diện

Tích hợp vào **Thiết lập → Cách trích xuất**, theo layout pipeline đã có. Một editor hoạt động tại một thời điểm:

```text
Cách trích xuất: [Danh mục cố định / EDC mở / EDC+R]

Prompt cho: EDC+R                  Đang áp dụng: v4 • Đã lưu
[Nội dung hướng dẫn có thể chỉnh sửa                              ]
[                                                               ]
Ghi chú thay đổi…
[Lưu phiên bản mới] [Hủy sửa] [Lịch sử phiên bản]

Xem trước với tài liệu: […]   Đoạn: […]
[Dựng bản xem trước]
  Hướng dẫn | Phần app bổ sung | System & User | Tham số | Cảnh báo

Lịch sử: v4, v3, v2, v1
[Xem] [So sánh với bản đang dùng] [Khôi phục thành phiên bản mới]
```

### 3.1. Chuyển dự án/cấu hình

- Editor và draft có key theo `project_id + configuration_id`; không dùng key chung cho cả ba mode.
- Đổi cấu hình chỉ hiện prompt tương ứng; giữ nháp riêng trong session. Có nhãn “Có thay đổi chưa lưu”, không tự lưu khi chọn radio.
- Tách **cấu hình đang xem** khỏi **cấu hình đang áp dụng** nếu người dùng chưa lưu thay đổi chế độ. Trước chạy, summary phải chỉ đúng cấu hình đã được áp dụng.
- Đổi dự án không mang draft/preview sang dự án khác. Nếu có nháp, cho lưu hoặc giữ nháp theo dự án; không âm thầm áp dụng.
- Run chỉ dùng phiên bản đã lưu và cấu hình đã áp dụng. Nháp có thể xem trước nhưng phải gắn nhãn “Bản nháp — chưa dùng để chạy”; muốn dùng phải lưu rõ ràng.

### 3.2. Lịch sử và khôi phục

- Danh sách: số phiên bản theo cấu hình, thời gian, người/nguồn thao tác, ghi chú, hash ngắn, phiên bản đang áp dụng.
- Chọn Xem không đổi bản đang áp dụng. Chỉ tải full content của bản đang xem khi tầng lưu trữ hỗ trợ; không mở đồng thời tất cả editor lịch sử.
- So sánh bằng `difflib` chuẩn Python; xem hai bản bất kỳ trong cùng cấu hình. Chỉ cần text diff, không thêm thư viện quản lý phiên bản.
- Khôi phục bản cũ tạo **bản mới** với `restored_from_version_id`, rồi áp dụng cho cấu hình đó; không sửa/xóa bản cũ hoặc tái đánh số.
- Khôi phục cùng nội dung với bản đang dùng là no-op có thông báo, tránh sinh lịch sử rỗng.
- Không tự khôi phục catalog, token/model hoặc dự án khi khôi phục prompt. Nếu bản cũ từng dùng catalog khác, hiển thị thông tin đó ở lịch sử request/run.
- Đợt đầu không có xóa cứng version, không tự dọn bản cũ. Bản đang được run tham chiếu phải tiếp tục truy cập được.

### 3.3. Phân biệt ba loại nội dung

1. **Hướng dẫn người dùng:** có thể sửa và version hóa.
2. **Phần ứng dụng bổ sung:** hợp đồng JSON, catalog, retrieved schema, hints; read-only ở preview, lấy từ cùng builder đang chạy.
3. **Request hiệu lực:** system/user, response format và tham số sau budget/adapter preparation. Đây mới là nội dung cần đối chiếu khi gửi LLM.

Không lưu cả phần app bổ sung vào editor rồi ghép thêm lần nữa. Hợp đồng JSON có fingerprint/version để run cũ vẫn giải thích được nếu code template thay đổi.

## 4. Chuẩn dữ liệu tối thiểu

Ưu tiên mở rộng `prompt_versions` hiện có thành danh sách version chuẩn; thêm bindings và schema version. Không đồng thời duy trì thêm một `prompt_store` thứ hai chứa cùng dữ liệu.

```json
{
  "prompt_history_schema_version": 1,
  "prompt_bindings": {
    "closed": "pv_closed_01",
    "edc": "pv_edc_01",
    "edc_plus_r": "pv_edcr_04"
  },
  "prompt_versions": [
    {
      "id": "pv_edcr_04",
      "configuration_id": "edc_plus_r",
      "mode": "edc_plus_r",
      "version": 4,
      "content": "Hướng dẫn trích xuất do người dùng chỉnh sửa...",
      "content_hash": "sha256-toan-bo-noi-dung",
      "created_at": "2026-10-31T09:00:00+07:00",
      "created_by": "local_user",
      "note": "Bổ sung nguyên tắc về niên đại",
      "parent_version_id": "pv_edcr_03",
      "restored_from_version_id": null,
      "origin": "human"
    }
  ]
}
```

Ví dụ minh họa, ID/thời gian/hash do hệ thống tạo thực tế. Actor phản ánh danh tính đang có; chưa có đăng nhập thì ghi local/unknown theo chính sách, không bịa người dùng.

### 4.1. Quy tắc bất biến

- Version bất biến sau commit; ID duy nhất trong dự án, mọi lookup scope theo dự án và cấu hình.
- Binding phải trỏ version tồn tại, thuộc đúng cấu hình/mode. Số version tăng riêng cho mỗi cấu hình dưới khóa/transaction, không lấy từ vị trí dòng.
- `content_hash` dùng SHA-256 đầy đủ trên nội dung lưu thực tế. Chốt chuẩn newline lúc nhập/lưu; không casefold, gộp khoảng trắng hoặc xóa dấu để hash prompt.
- Nội dung rỗng/không hợp lệ bị từ chối. Nội dung giống bản đang dùng không tạo version mới và không snapshot vô ích.
- Lưu prompt không thay catalog; lưu catalog không tự tạo prompt version khi content không đổi.
- Các trường legacy `prompt`/`edc_prompt` chỉ là dữ liệu đọc tương thích trong giai đoạn chuyển đổi, không tiếp tục có nhiều đường ghi độc lập. Resolver mới là nguồn chọn prompt cho cả ba engine.
- Không tăng `SCHEMA_VERSION` chung một cách máy móc nếu schema history có version riêng đủ dùng; đánh giá loader/export/import/test thực tế trước khi quyết định.

### 4.2. Quan hệ với revision và transaction

- Lưu/khôi phục nhận expected project hoặc prompt revision cùng request ID; validate, tạo bản sao cần thiết, ghi qua cơ chế atomic hiện có.
- Cập nhật version, binding, audit và receipt trong cùng commit logic; lỗi I/O không để session mang binding đã đổi mà ổ đĩa chưa lưu.
- Bổ sung prompt bindings/content revision vào cơ chế chống xung đột hiện có. `compute_project_revision()` hiện không bao trùm đầy đủ prompt, không được dựa vào nó như thể đã bảo vệ trường này.
- Hai phiên sửa từ cùng base: lần commit sau phải thấy conflict, có thể tải lại/so sánh; không last-write-wins âm thầm.
- JSON còn là nguồn chính thì dùng repo/journal/snapshot hiện có; SQLite sync lỗi sau JSON commit tiếp tục trả đúng `committed + sync_pending`. Không thêm sidecar prompt file khiến một thao tác phải có hai cơ chế atomic song song.
- Nếu migration SQLite authoritative đã được thực hiện lúc agent triển khai, dùng transaction/repository đang có cho versions/bindings. Không ép quay về JSON hoặc tạo prompt DB riêng.

## 5. Luồng xem trước và gửi LLM phải dùng chung

### 5.1. DTO tối thiểu

Đề xuất bổ sung vào `shared/schemas/prompts.py`:

- `PromptVersionDTO`: record ở mục 4.
- `PromptSaveRequestDTO`: project/configuration, base version, content, note, expected revision, request ID, optional restored-from.
- `PromptPreviewRequestDTO`: project/configuration, version hoặc draft có nhãn rõ, doc/chunk ID/span, tham số chạy và expected revision.
- `PreparedExtractionRequestDTO`: prompt version/config snapshot, loop index, system/user, effective input, response format, temperature, output cap, warnings, component fingerprints, request hash và nguồn chunk.

DTO prepared không chứa API key, header Authorization hoặc đối tượng SDK. Thông tin kết nối nhạy cảm nằm ngoài dữ liệu preview/history; hash nhận diện request không gồm secret. Các override theo provider phải được mô tả đủ để hiểu payload sau adaptation, không hiển thị thông tin xác thực.

### 5.2. Trình tự chuẩn

```text
Chọn project/config/version + chunk + tham số
  → Resolve bản hướng dẫn đã lưu hoặc draft preview
  → Ghép catalog/retrieval/hints bằng logic engine hiện có
  → Ghép hợp đồng đầu ra
  → Fit input budget, dựng user message, clamp output
  → Chuẩn bị dữ liệu adapter/provider
  → Prepared request + hash + warnings
       ├─ Preview: chỉ hiển thị
       └─ Execute: validate dependency → gửi cùng prepared request
  → Ghi attempted/sent request và kết quả/fallback vào trace
```

1. Tách phần chuẩn bị thuần trong `LLMGateway.extract()` thành hàm dùng chung, ví dụ `prepare_extraction_request()`. `extract()` hiện có tiếp tục là entrypoint tương thích và dùng hàm này; không tạo một gateway preview riêng.
2. Dùng lại `edc_prompt()`, `EDC_SCHEMA`, `build_user_message()`, `fit_chunk_to_input_budget()` và `clamp_output_tokens()`. Không copy chuỗi prompt hoặc công thức budget sang frontend.
3. Engine cung cấp đúng context/mode khi dựng prompt, không tạm đổi `project['extraction_mode']` chỉ để builder chọn nhánh. Resolver nhận mode/configuration rõ ràng; tránh preview làm mutate dự án.
4. Nếu cần tách chuẩn bị provider options trong adapter, tái dùng cùng helper cho preview và `_call`; không tái hiện toàn bộ SDK transport ở lớp domain/UI. Anthropic có system riêng, OpenAI-compatible dùng messages; UI biểu diễn đúng sự khác nhau.
5. Chạy từ bản preview đã lưu phải dùng artifact prepared đúng hash hoặc chặn khi dependency thay đổi. Không dựng lại retrieval ngẫu nhiên sau preview rồi vẫn gọi đó là cùng request.
6. Chạy không mở preview vẫn đi cùng builder; xem trước là quyền kiểm tra, không thêm một hộp xác nhận bắt buộc cho mọi chunk.

### 5.3. Nội dung preview bắt buộc

- Dự án, cấu hình/mode, version, content hash, provider/model, tài liệu/chunk và loop được xem.
- Base instructions và từng phần app bổ sung: catalog đầy đủ ở closed hoặc Top-K thực tế ở EDC+R, hints, hợp đồng đầu ra.
- **System và User sau khi xử lý**, phần chunk thực tế sẽ gửi, cảnh báo phần bị cắt và số ký tự gốc/hiệu lực.
- Output cap sau clamp, temperature và response format dự kiến. Token đầu vào hiện đang ước lượng theo ký tự; hiển thị là ước lượng, không hứa đúng tokenizer của mọi model.
- Trường hợp system/user/schema overhead vượt ngân sách phải hiện lỗi/cảnh báo có thể xử lý. Không chỉ cắt chunk bằng `MIN_CHUNK_TOKENS` rồi tuyên bố toàn request chắc chắn vừa context; overhead phải xét cả user wrapper, allowed relations và response schema theo quy tắc provider.
- Bản tóm tắt thay đổi nếu catalog, source text, model hoặc version đã khác lần dựng trước. Tự vô hiệu preview cũ.
- Có thể sao chép/tải bản preview sạch secret khi cần; không cần thêm công cụ export riêng hoặc dependency mới.

### 5.4. EDC+R nhiều vòng

- Preview cụ thể trước chạy áp dụng cho **chunk được chọn, vòng 1**, đã có Top-K thật. Dựng preview có thể gọi embedding theo cấu hình; thông báo rõ, không gửi request trích xuất LLM và không tự chạy align/ingest.
- Vòng 2 trở đi có hints từ kết quả trước, chưa biết trước khi gọi LLM. Không hiển thị một mẫu giả rồi gọi đó là request chính xác của mọi vòng.
- Mỗi vòng chuẩn bị và ghi request riêng trước gửi. Sau chạy xem được request thật từng vòng, kể cả lỗi/fallback; có thể xem mẫu vòng sau với nhãn mô phỏng nhưng không bắt buộc trong đợt đầu.
- Không bắt dừng từng vòng để hỏi người dùng. Nếu sau này cần chế độ duyệt từng request, đó là tùy chọn debug riêng.
- Run/job pin prompt version và cấu hình lúc bắt đầu. User sửa prompt trong khi đang chạy không làm các chunk sau tự đổi hướng dẫn.
- Nếu catalog được cập nhật trong chính pipeline, ghi catalog/retrieval snapshot của từng request; nếu thay đổi từ ngoài trước gửi một preview đã chốt thì báo stale. Không nhầm hai trường hợp này.

### 5.5. Request chính và request phụ

Phạm vi editor là hướng dẫn **trích xuất**, không mở luôn editor cho prompt xác minh Target Alignment, kết nối thử hoặc embedding instruction. Trace dùng `request_kind` để phân biệt chúng. Có thể xem request phụ trong chẩn đoán hiện có, không làm lịch sử prompt người dùng lẫn với prompt nội bộ.

Fallback response format do provider từ chối chỉ biết sau lần gửi. Preview trình bày format ban đầu và khả năng fallback; trace ghi format của từng attempt thực tế. Prompt preview khớp payload không có nghĩa đầu ra LLM sẽ tái lập hoàn toàn.

## 6. Provenance: lấy lại đúng phiên bản đã chạy

Run/chunk/request cần tham chiếu:

```text
project_id, job_id/run_id, request_id, request_kind
configuration_id, mode, prompt_version_id, prompt_content_hash
instruction_template_hash/version, catalog_hash, retrieval/model fingerprint
source_text_fingerprint, chunk_hash, loop_index, attempt_index
config_snapshot_hash, prepared_request_hash, request_snapshot_ref
status, warnings, actual response-format/fallback metadata
```

- Dùng run ID thống nhất từ engine tới facade và ingest. Hiện engine tự tạo run ID còn facade tự tạo run record; agent phải kiểm tra và nối lại để version/request không treo sai lượt.
- `prompt_version_id` là phiên bản hướng dẫn, `prepared_request_hash` là request cụ thể: cùng một version có thể sinh nhiều request vì khác chunk/catalog/model/hints.
- Giữ `prompt_id` legacy để đọc dữ liệu cũ; thêm provenance mới có nghĩa rõ. Không suy luận full request từ signature ngắn hiện có.
- Lưu request snapshot một lần theo hash/run artifact và tham chiếu từ trace, không copy full system/user vào mọi node/cạnh. Snapshot thành phần cần đủ để giải thích và đối chiếu payload thực tế, không chỉ lưu tên Top-K.
- Đường save snapshot phải hoàn tất trước khi gửi nếu đã bật yêu cầu audit request bền vững; snapshot đã chuẩn bị nhưng chưa gửi có trạng thái riêng, tránh ghi nó là thành công sau crash.
- Lỗi API vẫn giữ thông tin attempted request/version. Secret không đi vào snapshot, job config, export hoặc test fixture.
- Thực thể/quan hệ mới tham chiếu run/request thích hợp, giữ nguồn/bằng chứng đang có. Không đổi dữ kiện cũ khi người dùng khôi phục prompt.

### Tương thích ML exporter

Không tiếp tục gán `project['prompt']` hiện tại cho toàn bộ dữ liệu huấn luyện lịch sử. Dùng version/request liên kết với quan sát thực tế nếu có. Cùng một đối tượng có nhiều quan sát từ nhiều run phải giữ ranh giới provenance.

Nếu SFT record được tổng hợp lại sau kiểm duyệt và không có một request gốc duy nhất, ghi rõ nguồn gốc là mẫu tổng hợp và dùng một template được định danh riêng; không giả rằng đó là prompt thực tế từng sinh ra kết quả. Run cũ thiếu provenance được đánh dấu unknown/legacy, không bịa ánh xạ. Không mở rộng đợt này thành tái thiết kế toàn bộ ML Lab.

## 7. Migration không làm mất prompt cũ

1. Kiểm tra cấu trúc project thực tế, tạo backup/snapshot bằng cơ chế hiện có trước lần ghi migration. Migration trên bản đọc trong RAM có thể chuẩn bị shape nhưng không tự ghi nhiều lần mỗi rerun.
2. Nếu chưa có history schema mới, tạo version ban đầu cho `closed` từ `prompt`; cho `edc` và `edc_plus_r` từ `edc_prompt` hiện có. Hai bản EDC có thể cùng content nhưng binding/ID độc lập.
3. Khi prompt không có trong dự án cũ, dùng default tại thời điểm migration và đánh dấu `origin=default_seed`. Sau đó default toàn ứng dụng đổi không được ghi đè prompt đã seed.
4. Chuyển các entry `prompt_versions` cũ sang record có schema mới khi xác định được content và mode. Giữ nguyên thời gian/metadata thực có; thiếu thời gian ghi unknown, không tạo thời gian lịch sử giả.
5. History cũ lưu cả catalog thì bảo toàn phần đó trong `legacy_context`/record archival của migration; UI khôi phục **content prompt** riêng. Chỉ các record không ánh xạ được mới giữ ở nhánh legacy riêng, không copy toàn bộ history thành hai kho lâu dài.
6. Không suy ra EDC prompt quá khứ từ một history entry chỉ có prompt closed. Không phục dựng request cũ từ cấu hình hiện tại rồi gắn nhãn đã gửi.
7. Lần lưu migration đầu ghi versions + bindings + migration marker cùng giao dịch; chạy lại không sinh version trùng. ID migration cần ổn định/receipt để phục hồi sau lỗi ghi.
8. Sau migration chuyển mọi caller qua resolver mới. `save_prompt_settings()` trở thành wrapper tương thích nếu còn caller thật: catalog save độc lập và prompt change đi qua service chung; bỏ ghi history trùng ở wrapper.
9. Chỉ loại bỏ fallback/field legacy sau khi đã kiểm tra import/export, snapshot restore và toàn bộ caller/test. Không giữ mã chết vô hạn với lý do “có thể dùng sau”.

Lịch sử prompt dạng JSON trong project còn tốn RAM nếu loader vẫn nạp toàn dự án. Đợt này không hứa lazy load vật lý chỉ nhờ phân trang UI. Khi hạ tầng query/storage của plan hiệu năng sẵn sàng, dùng metadata pagination và content lookup theo ID; không triển khai prompt DB/worker mới để giải quyết riêng vấn đề này.

## 8. Hướng dẫn agent triển khai theo thứ tự

### Bước 0 — Xác nhận nền hiện tại

- Đọc `structure.md` và tìm mọi caller bằng `rg` với `prompt_versions`, `edc_prompt`, `extraction_prompt`, `save_prompt_settings`, `prompt_signature`, `build_user_message`.
- Kiểm tra code mới từ agent khác, nhất là pipeline layout và storage migration. Tài liệu này không phải căn cứ ghi đè những thay đổi chưa đọc.
- Chạy bộ test hiện tại để ghi baseline. Không lấy số lượng pass ghi trong tài liệu cũ làm kết quả.
- Xác nhận interpreter thực tế; dùng venv app đang chạy, không cài thêm thư viện cho tính năng này.

### Bước 1 — Chốt schema, migration và resolver

- Tạo DTO nhỏ; mở rộng loader/empty project cho schema mới.
- Tách nghiệp vụ prompt vào `backend/domain/prompts/service.py` nếu cần để không tiếp tục kéo dài catalog service.
- Implement list/get current version, save, restore, resolve. Validator cấm cross-project/cross-configuration, nội dung rỗng và conflict.
- Giữ catalog service chịu trách nhiệm catalog; wrapper cũ delegate prompt logic thay vì append history trực tiếp.
- Viết test migration, isolation, no-op và concurrent save trước khi nối UI.

### Bước 2 — Một editor theo cấu hình

- Chỉnh `render_edc_mode_settings` và vùng prompt fixed ở trang 2 thành một luồng editor dùng chung.
- Tái sử dụng component có sẵn nếu phù hợp; chỉ tạo `prompt_editor.py` khi có đủ logic/UI cần tách. Không có ba editor gần giống nhau cho ba mode.
- Nối draft keys, save, history read-only, diff, restore; phân biệt mode đang xem/đang áp dụng.
- Xóa nút/đường ghi prompt cũ đã được thay thế để tránh lưu hai lần.

### Bước 3 — Builder request chung và preview

- Refactor phần chuẩn bị gateway/adapter tại chỗ, giữ API extraction cũ qua wrapper thật sự cần thiết.
- Cho cả ba engine dùng resolver và chuẩn bị request chung với context rõ ràng.
- Dựng preview từ tài liệu/chunk thật; closed có catalog, EDC có schema, EDC+R có retrieval vòng 1.
- Thêm invalidation và request hash. Test so sánh preview với fake SDK payload, không chỉ test text chứa vài từ khóa.

### Bước 4 — Pin version và ghi trace

- Job/chunk pin version + config snapshot trước thực thi. Nối request refs vào `EngineOutput`, run và ingest với run ID thống nhất.
- Lưu request từng loop/attempt theo artifact đã có hoặc mở rộng nhỏ; không nhân bản payload vào mọi record.
- Ghi lỗi/fallback, tích hợp xem request đã gửi trong trace viewer.
- Chỉnh exporter chỗ đang gán current project prompt để không tạo provenance sai.

### Bước 5 — Hồi quy, dọn mã và tài liệu

- Chạy test mới và test hiện có; smoke UI đầy đủ với project tạm.
- Kiểm tra không còn đường ghi `edc_prompt`/`prompt_versions` trực tiếp ngoài migration/service/wrapper được chủ ý giữ.
- Kiểm tra tương thích import/snapshot/export và dự án cũ. Ghi rõ những run legacy không phục dựng được request.
- Cập nhật `structure.md` và hướng dẫn sử dụng sau khi code đã qua kiểm thử; báo file thay đổi, kết quả test thực và giới hạn còn lại.

## 9. Bản đồ file và ranh giới trách nhiệm

| File/module | Việc cần làm / dùng lại |
| --- | --- |
| `shared/schemas/prompts.py` — mới | DTO version/save/preview/prepared; không chứa UI hoặc SDK |
| `backend/domain/prompts/service.py` — mới khi tách nghiệp vụ | Migration shape, resolver, version/save/restore; không ghi tệp trực tiếp từ domain |
| `backend/domain/catalogs/service.py` | Delegate prompt; giữ catalog/prompt composition helper cần thiết; revision có prompt dependency |
| `backend/repositories/json_repo.py` | Seed/normalize/load/save theo schema; dùng atomic bundle/journal hiện có |
| `backend/facade.py`, `frontend/client.py`, API nếu đang dùng | Điều phối version command/preview, revision, idempotency, save và query theo project/config ID |
| `frontend/components/edc_alignment_panel.py`, `p02_catalogs_prompts.py`, session state | Một editor; draft tách cấu hình; lịch sử/diff/restore, preview đã lưu hoặc nháp có nhãn |
| `shared/catalog_utils.py`, `llm/parsing.py`, `llm/token_budget.py` | Dùng lại hợp đồng/message/budget; sửa nhỏ tại nguồn nếu cần, không copy logic |
| `backend/integrations/llm/gateway.py`, `clients.py` | Chuẩn bị request dùng chung, gửi prepared payload và ghi attempt/fallback |
| `extraction/base_engine.py`, ba engine, facade ingest/run | Pin version, composition context, thống nhất ID/provenance |
| `frontend/components/step_traces_viewer.py`, trang trích xuất | Xem request thực tế theo vòng/attempt, không dựng lại từ current prompt |
| `backend/domain/dataset_exporter/exporter.py` | Dùng provenance đúng hoặc ghi mẫu tổng hợp/legacy rõ ràng |
| `tests/test_prompt_versions.py` — mới | Version/migration/isolation/draft + facade lưu/khôi phục |
| `tests/test_llm_package.py`, test engine hiện có | Mở rộng fake client để kiểm tra preview/send; tránh tạo fake SDK thứ hai trùng chức năng |

Nếu helper hiện có đủ trách nhiệm, mở rộng tại chỗ thay vì tạo thêm một module một hàm. Không thêm repository hoặc bảng SQL prompt mới trừ khi storage mode thực tế đã yêu cầu.

## 10. Kiểm thử bắt buộc

### 10.1. Version và lưu trữ

| Kịch bản | Kết quả cần kiểm tra |
| --- | --- |
| Hai dự án A/B cùng mode, khác prompt | A lưu/khôi phục không đổi B; ID từ A bị từ chối khi dùng trong B |
| EDC và EDC+R ban đầu cùng text | Sửa EDC không đổi binding/content EDC+R |
| Lưu từ v1 sang v2 rồi mở lại app | v2 đang áp dụng, v1 vẫn đọc được đúng content |
| Lưu lại đúng nội dung hiện hành | Không thêm version/snapshot/audit quyết định mới |
| Khôi phục v1 khi đang dùng v3 | Tạo v4 trỏ restored-from v1; v1–v3 nguyên vẹn, catalog không đổi |
| Migration chạy hai lần / bị lỗi I/O | Không tạo version trùng; không có binding hỏng hoặc session đi trước đĩa |
| History legacy có catalog, thiếu EDC prompt | Bảo toàn metadata; không bịa EDC version quá khứ, không restore catalog theo prompt |
| Hai session lưu cùng base | Một commit thành công, lần sau conflict hoặc replay hợp lệ theo request ID |
| SQLite sync lỗi sau JSON commit | Báo committed + sync pending; thử đồng bộ không sinh version mới |
| Restore snapshot/import chứa schema prompt cũ | Normalize đúng, không mất bản đang áp dụng hoặc field mở rộng |

### 10.2. Preview và nội dung gửi thực tế

- Fake OpenAI-compatible và fake Anthropic ghi lại SDK kwargs; so sánh system/user hoặc messages với prepared preview đúng provider, cùng version và effective limits.
- Closed/EDC/EDC+R đều dùng đúng prompt binding; phần schema/catalog chỉ ghép một lần, không lọt prompt của mode khác.
- Input bị trim/output bị clamp: preview ghi đúng chunk/cap/warning; fake client nhận đúng những giá trị đó.
- Prompt/overhead quá lớn: không báo preview hợp lệ khi payload không còn ngân sách phù hợp; không âm thầm gửi chunk rỗng/không đủ dữ liệu rồi báo thành công.
- Đổi prompt, text chunk, catalog, model, tham số hoặc template giữa preview và gửi: invalidation hoặc reject, không gửi âm thầm nội dung khác.
- Preview draft không đổi binding, catalog, graph hoặc history; không gọi LLM extraction/verify. Mock retrieval/embedder xác nhận preview EDC+R chỉ lấy ứng viên cần thiết.
- EDC+R hai vòng có hints khác: mỗi request có hash/loop ref đúng, vòng 2 truy vết theo payload thật; vòng 1 preview không bị gắn cho cả run.
- Provider từ chối response format: giữ prompt/version, ghi initial attempt và fallback thực tế; không ghi format ban đầu như thể đã được chấp nhận.
- Gateway lỗi/timeout vẫn truy được attempted request; test không chứa secret trong snapshot/hash/export hoặc error representation.
- Thay binding trong lúc job đang chạy: chunk tiếp theo vẫn dùng version được pin; job mới dùng version mới.
- Node/edge và run/trace liên kết nhất quán; exporter không lấy current prompt để giả làm prompt lịch sử.

### 10.3. UI và hiệu năng

- Chọn mode chỉ có một editor đúng prompt; đổi qua lại giữ draft riêng, không ghi đè prompt mode khác do widget key.
- Xem history không kích hoạt restore; preview nháp có nhãn; lưu/khôi phục không nhảy về bước đầu.
- Mở lịch sử không gọi LLM hoặc embedding; xem preview chỉ gọi retrieval khi mode yêu cầu.
- Không tạo version theo rerun/keystroke; không hash/serialize toàn history chỉ để đổi một bộ lọc.
- Payload chỉ được snapshot một lần theo ref, không có một bản full prompt cho mỗi node/cạnh; test kiểm tra cấu trúc record và số lần ghi có ý nghĩa.
- Diff, Unicode tiếng Việt, newline và prompt nhiều dòng giữ đúng nội dung.

Test dùng `unittest`, `tempfile`, fake client/retriever đang có và fixture nhỏ. Không gọi model thật, không cần GPU, mạng hoặc thêm framework test cho đợt này. AppTest nếu phù hợp phiên bản Streamlit thực tế, kèm smoke thủ công cho editor/history/preview.

### 10.4. Lệnh kiểm tra

Chạy từ terminal với đúng interpreter của ứng dụng:

```powershell
Set-Location D:\DATN\CrawData\KG_Studio
python -m unittest tests.test_prompt_versions -v
python -m unittest tests.test_llm_package -v
python -m unittest discover -s tests -t . -v
```

`tests.test_prompt_versions` là file cần tạo ở bước triển khai, chưa có chỉ nhờ tài liệu này. Không báo đã kiểm thử tính năng trước khi tồn tại implementation và kết quả chạy thực tế.

## 11. Quy tắc tránh code dư thừa

1. Một resolver prompt, một luồng version/save/restore và một phần chuẩn bị request dùng chung. Không có `build_preview_prompt()` tự ghép khác `build_run_prompt()`.
2. Không tạo ba editor hoặc ba service chỉ khác mode; truyền ID/context vào thành phần chung.
3. Không thêm LangChain, prompt CMS, Git repo cho mỗi prompt, DB/vector store hoặc templating engine chỉ để lưu text và diff. Thư viện chuẩn và hạ tầng hiện tại đủ cho phạm vi đầu.
4. Hợp đồng JSON, user wrapper, budget và provider options có một nguồn; frontend hiển thị DTO, không tự dựng payload.
5. Legacy wrapper chỉ giữ khi còn caller hoặc cần đọc dữ liệu cũ; delegate thật, có test và điều kiện loại bỏ. Xóa đường ghi cũ bị thay thế, tránh append history hai lần.
6. Prompt text history không chứa full catalog/document/run mỗi phiên bản. Lịch sử request dùng refs/snapshot fingerprint; context lớn lưu một lần theo cơ chế artifact có sẵn.
7. Không kết hợp đợt này với thay framework, sửa toàn bộ storage, thiết kế named profile phức tạp hoặc mở editor cho mọi prompt nội bộ.
8. Chỉ thêm abstraction khi có ít nhất một trách nhiệm cụ thể cần giữ hoặc nhiều caller cần dùng; tránh lớp chỉ chuyển tiếp không có giá trị.

## 12. Checklist hoàn thành

- [ ] Prompt tách theo dự án và từng cấu hình; EDC/EDC+R không còn dùng chung một field mutable.
- [ ] Một editor đúng cấu hình, có nháp/lưu/hủy và lịch sử.
- [ ] Lưu mới và khôi phục bảo toàn phiên bản cũ, không đổi catalog ngoài ý muốn.
- [ ] Migration idempotent, dữ liệu legacy giữ được và không bịa lịch sử.
- [ ] Preview và execution đi chung request preparation; budget/retrieval/provider được phản ánh đúng.
- [ ] Pin version theo job; trace thật theo loop/attempt, run ID nhất quán, không ghi secret.
- [ ] Request cũ mở lại từ snapshot/provenance, không dựng lại từ prompt hiện tại.
- [ ] Fake SDK payload parity, persistence/conflict/rollback và UI smoke đã qua.
- [ ] Không còn đường ghi/ghép prompt trùng; không thêm dependency không cần thiết.
- [ ] Báo cáo bàn giao có file đổi, test thực tế, migration/rollback và giới hạn đối với run legacy.
