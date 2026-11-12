# Baseline B: trích xuất bộ ba tự do (`free_triples`)

Ngày triển khai: 12/11/2026. Phạm vi: một baseline trích xuất riêng, không thay thế các modes `closed`, `edc`, `edc_plus_r` và không bổ sung entity resolution/từ điển ngữ nghĩa.

**Cập nhật tiếp theo cùng ngày:** đã bổ sung KG dẫn xuất từ các runs tại Bước 5, chuẩn hóa kỹ thuật tối thiểu cho khóa node và dùng chung thuật toán graph. Engine và artifacts thô mô tả trong tài liệu này giữ nguyên. Xem [báo cáo KG baseline hiện tại](baseline-graph-implementation.md); số test 181 bên dưới là mốc lịch sử của đợt xây engine, không phải số suite hiện tại.

## Hợp đồng thí nghiệm

- Tự do về vocabulary/nhãn quan hệ, không phải đầu ra văn bản tùy ý. JSON chỉ là hợp đồng cấu trúc, không chứa enum quan hệ hoặc loại thực thể miền.
- Một bước extraction trên mỗi chunk; không yêu cầu định nghĩa, không retrieval, refinement, verifier, canonicalization, schema proposals, entity merge hoặc graph ingestion. SDK vẫn có thể retry/fallback theo cấu hình provider hiện có.
- Nhãn, Unicode, khoảng trắng trong giá trị và triple lặp được giữ nguyên. Không gọi bộ làm sạch tên quan hệ EDC.
- Parse toàn bộ JSON, chấp nhận một code fence bao ngoài; không sửa JSON hỏng, lấy object đầu rồi bỏ phần còn lại, hoặc nhận duplicate JSON keys/NaN/số overflow thành Infinity.
- Sai top-level JSON/truncation tạo lượt lỗi có raw response/token/provenance. Triple sai cấu trúc riêng lẻ, quote không khớp và duplicates được giữ trong payload, kèm report theo index; không lọc mất trước khi đánh giá.
- `valid_triples` chỉ có nghĩa **đúng cấu trúc**, không chứng minh fact đúng lịch sử. Evidence được đối chiếu nguyên văn với `fitted_chunk_text` thực gửi.

```json
{
  "triples": [
    {
      "subject": "Công trình A",
      "predicate": "được trùng tu vào khoảng",
      "object": "đầu thế kỷ XX",
      "evidence": "Công trình A được trùng tu vào khoảng đầu thế kỷ XX."
    }
  ]
}
```

Đây là ví dụ giả định về format, không phải khẳng định lịch sử.

## Source ownership và lưu kết quả

| Phần | Implementation |
| --- | --- |
| Prompt/mode mặc định | `shared/constants.py`, prompt history có binding `free_triples` riêng |
| Output format, strict parser, diagnostics thuần | `shared/schemas/free_triples.py` |
| Provider/token budget/fallback | `LLMGateway` với `output_contract="free_triples"`; default legacy contracts giữ nguyên |
| Engine dùng injected LLM port | `backend/modules/extraction/application/free_triples_engine.py` |
| Record/export artifacts và lỗi | `backend/modules/extraction/application/free_triples_runs.py` |
| Registration/wiring | `AppContainer` và extraction service nhận injected gateway; registry thiếu baseline phải báo lỗi, không fallback sang fixed mode |
| Giao diện | Chọn mode tại Bước 2; preview và chạy/tải artifacts tại Bước 3 |

Engine không tạo node/edge hay sửa catalog/proposal. Application ghi kết quả trong `project["runs"]`, gồm `run_id`, mode/stage/policy, source chunk, payload, diagnostics, raw output, prompt/version/hash, request/fitted input, token counts và trạng thái. Lượt lỗi không được đánh dấu processed. Lượt chạy lại là attempt riêng, không bị deduplicate trong bộ kết quả thí nghiệm.

Việc persist artifacts sử dụng commit coordinator hiện có để snapshot/atomic save; không tạo đường ghi JSON thứ hai. `save_after_chunk=False` trong chạy batch giữ kết quả trong memory, không tự ghi disk. Baseline tránh gọi secondary `save_project` từ UI sau khi đã commit.

Raw response baseline được giữ đầy đủ, không áp giới hạn hiển thị 100.000 ký tự của modes cũ. Nếu provider vô tình echo API credential, bản ghi/export redacts đúng credential và đặt `credentials_redacted=true`; không tuyên bố đó là raw byte-for-byte. Không đưa credential vào prepared request hoặc log error message.

`export_free_triples_results(project)` của extraction application trả UTF-8 JSON bytes với `format="kg-studio.free-triples.v1"`, mode và **tất cả** baseline attempts (cả lỗi), không qua `approved_graph` hoặc schema approval. Payload không chứa các runs của modes khác.

## Sử dụng

1. Tại **Bước 2 — Thiết lập**, chọn **B. Bộ ba tự do — baseline (không chuẩn hóa)** và áp dụng. Không cần nạp danh mục.
2. Có thể preview request cho mode này ngay cả khi project đang chọn mode khác; preview không thay active mode hoặc seed history trên project nguồn.
3. Tại **Bước 3 — Trích xuất**, chạy mẫu hoặc batch. Kết quả hiển thị số triples thô, lỗi cấu trúc, bằng chứng không khớp; node/edge additions là 0 theo thiết kế.
4. Xem payload/report/provenance trong nhật ký, tải **toàn bộ kết quả baseline B (JSON)** để chấm với gold độc lập.

API lập trình: đặt `project["extraction_mode"]="free_triples"`, gọi `get_container().extraction_service.extract_chunk(...)` hoặc `extract_chunks_parallel(...)`, rồi gọi `export_free_triples_results(project)`. Người gọi tự cấp model/provider/credential qua tham số runtime như modes cũ; không hardcode secret.

## Kiểm chứng

```powershell
& '.\.venv-win\Scripts\python.exe' tools/run_isolated_tests.py tests.test_free_triples_baseline tests.test_free_triples_gateway tests.test_free_triples_ui
& '.\.venv-win\Scripts\python.exe' tools/run_isolated_tests.py
```

Runner tạo bản sao source hiện tại (kể cả code chưa commit), config/storage riêng và project synthetic; dùng cùng Python executable nhưng chặn ghi ngoài workspace tạm và kết nối mạng ngoài. Không copy dữ liệu dự án, `.env` hoặc secrets thật. Đây là kiểm thử hành vi/phần mềm; không gọi LLM/Neo4j thật và không đo precision/recall của model.

Đã chạy targeted suite trên Python 3.13.2: **39 tests PASS**, gồm fake OpenAI/DeepSeek/Anthropic, fallback, truncation, raw preservation, prompt migration, preview parity, storage round-trip, rollback, parallel execution và hai Streamlit AppTest flows.

Nghiệm thu source cuối ngày 12/11/2026: lệnh full discovery ở trên **181 tests PASS, 5.149 giây, exit code 0**, gồm architecture checks và 39 tests baseline. Không có test bị skip. Đã kiểm tra health API cả wiring mặc định và facade dùng repositories tùy chỉnh. Runner chỉ ẩn warning Streamlit lặp về `missing ScriptRunContext` khi chạy bare mode; không ẩn failures/errors.

Audit độc lập đã kiểm tra tính nguyên bản của nhãn/duplicates, không có EDC ingestion và provenance của lỗi. Đã chặn JSON exponent overflow trước khi serialize, yêu cầu engine được inject LLM port, khóa đọc prompt cùng khóa commit trong process, và che credential cả ở JSON key của mục không hợp lệ.

Đã chạy `C:\Users\thena\AppData\Local\Programs\Python\Python313\Scripts\graphify.exe update .`: **exit code 0**, AST-only, không gọi LLM; graph cập nhật **2.338 nodes / 7.272 edges / 93 communities**. CLI cảnh báo community labels cũ chưa đồng bộ sau thay đổi cấu trúc; không chạy semantic relabel có gọi LLM. Các generated graph files được giữ theo quy tắc dự án.

Đợt này bổ sung baseline, không xóa source hoặc dữ liệu hiện có; không có mục deletion ledger mới. Các thay đổi refactor sẵn có trong working tree được giữ nguyên.

## Giới hạn khi dùng để so A/B/C

- Dùng projects/runs độc lập, đóng băng corpus/chunks/model/prompt và giữ cả failures; không chấm B qua graph đã duyệt.
- So `fitted_chunk_text` giữa các phương án: cùng raw chunk chưa bảo đảm cùng input nếu prompt có độ dài khác và token fitter cắt khác nhau.
- `response_format` trong prepared request là định dạng **yêu cầu**; provider có thể fallback và có warning. Token counts là usage provider trả về, không phải chứng nhận đầy đủ chi phí billing/retries.
- Prompt baseline có thể chỉnh/version như modes khác. Khi báo cáo thí nghiệm, freeze và công bố đúng prompt/hash; việc user tự thêm chỉ dẫn schema vào prompt sẽ làm mất tính chất baseline thuần.
- Baseline này chưa phải evaluator P/R/F1 hoặc bằng chứng B tốt hơn A/C; cần gold từ văn bản nguồn và protocol đánh giá riêng.
