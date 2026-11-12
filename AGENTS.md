## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.

## Kiến trúc và tối ưu mã nguồn — quy tắc bắt buộc

Kế hoạch chuyển đổi: [AI/report/code-optimization-architecture-plan.md](AI/report/code-optimization-architecture-plan.md). Bản đồ hiện trạng: [AI/structure.md](AI/structure.md). Phải kiểm chứng nguồn khi tài liệu hoặc graph khác implementation; không coi số test PASS trong báo cáo cũ là kết quả hiện tại.

### 1. Phạm vi áp dụng và chuyển đổi

- Kiến trúc đích là **Modular Monolith theo nghiệp vụ/use case, với Ports & Adapters có chọn lọc**. Áp dụng cho code mới và phần được migrate; không rewrite toàn dự án trong một đợt cleanup.
- Thực hiện theo các gate P0–P7 trong kế hoạch. Chỉ tạo package/layer khi có chức năng thật; không thêm mediator, generic service/repository, event bus hoặc microservices nếu chưa có nhu cầu cụ thể và lý do được ghi lại.
- Tồn tại legacy không cho phép phát sinh vi phạm mới. Architecture tests phải quản lý ngoại lệ theo cạnh import cụ thể, kèm lý do và đợt gỡ; không bỏ qua cả package. Rút ngoại lệ khi migrate xong.
- Giữ nguyên thay đổi sẵn có của người dùng. Refactor, thay thuật toán/prompt, đổi schema lưu trữ và nâng dependency phải tách phạm vi để review và rollback được.

### 2. Ranh giới trách nhiệm và chiều phụ thuộc

- Domain chứa quy tắc/thuật toán nghiệp vụ; không import Streamlit, HTTP framework, concrete repositories, SDK gateway, filesystem/config I/O hoặc frontend. Code đang ở `backend/domain` nhưng làm orchestration/I/O phải được phân loại trước khi chuyển; không chỉ đổi tên thư mục.
- Application điều phối use case qua ports thuộc core. Concrete adapters được dựng ở composition root (`backend/bootstrap.py` khi triển khai), rồi inject; application/domain mới không tự tạo gateway/repository hoặc lấy global singleton.
- UI, HTTP và CLI chỉ mapping input/output và gọi public application APIs. Không đưa validation nghiệp vụ, merge, snapshot/save sequence hoặc transaction policy vào UI/transport.
- Module khác chỉ dùng public API/contracts được công bố; không import implementation private của nhau. Không tạo import cycle; kiểm tra cycle graph bằng nguồn/import test trước khi kết luận lỗi.
- `shared` không import `backend`, `frontend` hoặc `ml_lab`. Chỉ đưa vào shared contract/helper có cùng ý nghĩa và dùng xuyên phân hệ; I/O/config/secrets phải có owner rõ ràng, không lan vào pure domain.
- `KGStudioFacade` là boundary legacy cần thu nhỏ khi migrate; không bổ sung nghiệp vụ mới vào facade hoặc tạo một god service thay thế. ML UI gọi application boundary; training code không phụ thuộc frontend/facade.

### 3. Tái sử dụng và quản lý độ phức tạp

- Kiểm tra implementation hiện có trước khi viết helper. Tái sử dụng `merge_core`, `selection_core`, shared pagination/action bar, extraction lifecycle và train/serve formatting khi cùng semantics.
- Mỗi rule nghiệp vụ và lifecycle commit phải có một owner chuẩn. Chỉ trích abstraction khi có consumer/test seam cụ thể; không gom code chỉ vì giống cú pháp hoặc tên.
- Không dùng wildcard import hoặc `__getattr__` delegation trong code mới để che dependency. Public re-export phải tường minh và có consumer/compatibility purpose.
- File >500 dòng hoặc một class xử lý nhiều capability phải được review trách nhiệm khi sửa đáng kể; ghi lý do giữ hoặc kế hoạch tách. LOC không là hard gate; không chia file cơ học để đạt ngưỡng.

### 4. Tính toàn vẹn dữ liệu và commit

- Giữ JSON project bundle là authoritative, SQLite là read projection và vector index là dữ liệu dẫn xuất cho đến khi có migration riêng. Không tự đổi nguồn sự thật trong cleanup.
- Preview không mutate/ghi dữ liệu nghiệp vụ. Apply phải kiểm tra lại project scope, expected revision, stale state, request hash/idempotency và semantics `all_or_nothing`/`valid_only`.
- Bảo toàn khóa, snapshot, atomic JSON commit/rollback và thời điểm cập nhật state. SQLite sync lỗi phải báo `sync_pending` và hỗ trợ resync; query không được âm thầm dùng projection stale như dữ liệu mới nhất.
- Dùng lifecycle commit chuẩn sau khi coordinator được triển khai; không sao chép lock/revision/idempotency/snapshot/save sang use case mới. Trước đó phải đi qua commit path hiện có tương ứng.
- Merge phải bảo toàn observations, evidence/offsets, aliases, redirects, document links, trạng thái và audit history; chỉ collapse/self-loop theo policy đã được kiểm chứng.
- Giữ prompt version pinning, prepared-request parity/hash, provenance từng attempt/run, token accounting, cache fingerprint/invalidation và train/serve formatting đồng nhất.
- Không ghi API key/secret vào project, snapshot, trace, log hoặc fixture. `RLock` trong process không được mô tả là bảo đảm multi-process concurrency.

### 5. Contracts và transport

- Dùng Pydantic v2 hiện có cho contracts tại biên phù hợp; không ép toàn bộ project dict qua DTO thiếu trường rồi ghi đè storage. Phải test unknown fields, default/null, ID, Unicode và serialization trước khi thay conversion.
- Không đổi global `extra` policy hoặc xóa `.from_dict/.to_dict` chỉ để rút ngắn code. Các hành vi compatibility còn consumer phải có kế hoạch migrate và test tương đương.
- Giữ in-process execution mặc định. Transport local/HTTP phải được chọn tường minh; không fallback từ lỗi HTTP sang local mutation. Capability remote chưa hỗ trợ phải trả lỗi rõ ràng.
- Giữ public API/CLI/engine registrations và định dạng export đang được hỗ trợ trong migration. Chỉ bỏ compatibility shim sau khi migrate callers và giải quyết nghĩa vụ tương thích; ghi điều kiện gỡ, không giữ vô hạn.
- UI giữ session keys/selection theo ID, draft invalidation, phân trang, hai bảng EDC và return context. Khi sửa UI, đối chiếu Streamlit version thực tế và quy ước tại `AI/structure.md`; không nâng framework kèm refactor.

### 6. Điều kiện bắt buộc trước khi xóa

- Phải có bằng chứng caller/import và audit `__all__`, dynamic import, registry, CLI, config, side effects, test seams và public consumers. Graph không có cạnh, ít caller hoặc static analyzer báo unused chỉ tạo ứng viên điều tra.
- Ghi deletion ledger trong báo cáo của đợt: path/symbol, lý do, consumers đã kiểm tra, thay thế, compatibility condition và tests/kết quả. Migrate caller trước rồi mới xóa implementation cũ.
- Không xóa test còn bảo vệ hành vi để làm suite xanh; chuyển test sang public boundary mới. Không xóa package marker/re-export hợp lệ chỉ vì file ngắn.
- Cleanup source không cho phép xóa project data, snapshots, catalogs/history, prompt versions, training exports, model artifacts hoặc `graphify-out`. Giữ báo cáo lịch sử; chỉ rõ trạng thái cũ khi khác hiện tại.

### 7. Kiểm chứng và nghiệm thu

- Dùng interpreter Python >=3.11 thực tế của KG Studio, ưu tiên `.venv-win`; không thêm dependency runtime vào source hoặc venv của `KG_Studio_MVP`. Ghi lệnh/version thực tế; không tuyên bố PASS khi chưa chạy.
- Chạy tests đúng phạm vi; thay commit/merge/contracts cần fault/concurrency/replay hoặc lossless parity tests phù hợp. Trước khi kết thúc đợt refactor phải chạy full offline suite và architecture checks; live LLM/Neo4j chỉ opt-in.
- Tests và benchmarks dùng thư mục tạm/fake adapters; không sửa dữ liệu dự án, cấu hình hoặc secrets thật. Chỉ thêm test bảo vệ contract/invariant/rủi ro thực tế, không mirror implementation.
- Thay đường nóng phải có baseline và phép đo sau cùng fixture/seed/environment. Hồi quy p95/peak memory >10% cần điều tra và giải thích tradeoff theo kế hoạch; không suy đoán hiệu năng từ LOC.
- Cập nhật `AI/structure.md`, README, imports/exports và contract documentation khi implementation thay đổi. Không viết kiến trúc đích thành hiện trạng trước khi triển khai.
- Sau code changes, bắt buộc `graphify update .` theo quy tắc phía trên. Nếu CLI/runtime bị chặn: thử xác định môi trường cài đặt được phép, ghi lệnh/lỗi và phần chưa xác minh; không tự sửa generated graph bằng tay hoặc bỏ qua rồi báo hoàn tất.
- Nếu `graphify query` không khả dụng, phải báo rõ và dùng graph JSON/report có phạm vi để định vị; so graph commit với HEAD, kiểm chứng source/callers trước mọi deletion. Đây là fallback khi công cụ không chạy được, không phải ngoại lệ để bỏ graph khi graph bị dirty.

### 8. Quy tắc bắt buộc cho Modular Monolith và Ports & Adapters (Architectural Invariants)

Bất kỳ AI Agent nào can thiệp mã nguồn KG Studio đều **PHẢI TUÂN THỦ TUYỆT ĐỐI** các bất biến kiến trúc sau đây, không có ngoại lệ:

1. **Hệ thống 6 Module Nghiệp vụ Chuẩn (`backend/modules/`)**:
   - Toàn bộ use case và nghiệp vụ hệ thống bắt buộc phải thuộc quyền sở hữu của đúng 1 trong 6 modules:
     - `backend/modules/projects/`: Quản lý dự án, revision tracking, SSOT read projection và trọng tài commit duy nhất (`ProjectCommitCoordinator`).
     - `backend/modules/schema_intelligence/`: Quản lý danh mục, đề xuất EDC, xem trước/áp dụng quyết định duyệt schema, Target Alignment và Schema Retrieval (+R).
     - `backend/modules/extraction/`: Quản lý tài liệu thô, chunking, phiên bản prompt bất biến, engine registry (`closed`, `edc`, `edc_plus_r`, `free_triples`) và trích xuất song song an toàn đa luồng. `free_triples` là baseline B chỉ lưu artifacts thô; không gọi EDC ingestion/definitions/retrieval/alignment/merge hoặc nhập đồ thị. Giữ nguyên nhãn, duplicates và các mục không hợp lệ kèm diagnostics để đánh giá độc lập.
     - `backend/modules/curation/`: Duyệt cạnh, chỉnh sửa fact/profile, quy trình gộp 3 tầng (thực thể, quan hệ, bộ ba), đối chiếu bằng chứng span ký tự và gom cụm ngữ nghĩa.
     - `backend/modules/graph_qa/`: Đồ thị đã duyệt, KG baseline dẫn xuất chỉ đọc, thuật toán G-Retriever PCST, sinh bộ câu hỏi benchmark QA, đồng bộ Cypher Neo4j và xuất dữ liệu. KG baseline lấy runs qua public API của extraction được inject bằng port; không nhập vào `project.nodes/edges`. Policy `surface-nfc-casefold-v1` chỉ dùng Unicode/khoảng trắng/casefold cho khóa node, giữ raw labels, predicate và observations; không dùng aliases, redirects hoặc catalog. Các nguồn graph dùng chung `GraphSnapshotDTO`; đường snapshot chọn nguồn tường minh, không fallback approved sang all và không giả lập human approval. So các KG phải dùng cùng gold độc lập hoặc ghi rõ chỉ là demo câu hỏi tự sinh trên từng graph.
     - `backend/modules/training/`: Xuất 3 tập dữ liệu Active Learning chuẩn (SR Triplets, Canonicalization Pairs, SFT Extractions), đóng vai trò ranh giới an toàn duy nhất với `ml_lab/`.
   - Mỗi module phải tuân thủ cấu trúc tối thiểu: `ports.py` (khai báo Protocol trừu tượng), `application/service.py` (Application Service điều phối nghiệp vụ), `public.py` (hợp đồng công khai export ra ngoài).
   - **Cấm tuyệt đối cross-module internal import**: Module A không được import file nội bộ của Module B (ví dụ: cấm `from backend.modules.projects.application.commit_coordinator import ...`). Mọi giao tiếp liên module phải đi qua `backend.modules.<name>.public`.

2. **Duy Nhất Một Composition Root (`backend/bootstrap.py`)**:
   - `AppContainer` và singleton getter `get_container()` là Composition Root DUY NHẤT của toàn hệ thống.
   - Toàn bộ concrete adapters (JSON repo, SQLite repo, Vector repo, Embedder gateway, Neo4j gateway, LLM gateway) được khởi tạo tại đây và inject vào 6 Application Services.
   - **Cấm tuyệt đối**: UI components, REST API routers, CLI hay Domain logic tự ý khởi tạo concrete repositories hoặc concrete gateways.

3. **Duy Nhất Một Trọng Tài Điều Phối Commit (`ProjectCommitCoordinator`)**:
   - Mọi thao tác ghi dữ liệu, duyệt đề xuất, gộp thực thể/quan hệ, chỉnh sửa cạnh/node, hay cập nhật schema bắt buộc phải đi qua `ProjectCommitCoordinator.commit()`.
   - **Cấm tuyệt đối**: Tạo thêm quy trình snapshot/save thứ hai, tự ý lưu file JSON hay tự ý cập nhật SQLite từ UI hoặc service con mà không qua commit coordinator.
   - Cấm tạo snapshot thành công giả lập (fake path `/tmp/...`). Store thiếu snapshot port phải báo lỗi rõ ràng.

4. **Ranh Giới Giao Diện & Transport (UI, API, CLI)**:
   - Streamlit UI (`frontend/components/`, `frontend/pages/`) chỉ giao tiếp với backend thông qua Application Services được cung cấp bởi `frontend/composition.py` (`get_ui_composition()`) hoặc qua `FrontendClient`.
   - **Cấm tuyệt đối**: Đưa nghiệp vụ transaction, quy trình tạo snapshot, hoặc vòng lặp ghi đĩa trực tiếp vào các tệp UI/Presenters.
   - Khi có lỗi ở tầng transport HTTP, cấm fallback âm thầm sang ghi local mutation.

5. **Quy Tắc Tương Thích Ngược & Thu Hẹp Facade (`backend/facade.py`)**:
   - `KGStudioFacade` chỉ là lớp compatibility forwarding duy trì tính tương thích ngược cho các consumer cũ.
   - **Cấm tuyệt đối**: Bổ sung nghiệp vụ mới vào `KGStudioFacade` hoặc biến Facade thành một God Service mới.
   - Mọi phương thức trong `KGStudioFacade` chỉ được phép ủy quyền (delegate) một dòng sang Application Service tương ứng trong `backend/modules/`.

6. **Bảo Vệ Ranh Giới Kiến Trúc Tự Động (Fail-Closed Architecture Guard)**:
   - `tests/test_architecture_boundaries.py` sử dụng trình quét AST tự động kiểm tra mọi file nguồn theo nguyên tắc Fail-Closed:
     - `shared/` tuyệt đối KHÔNG import `backend`, `frontend` hay `ml_lab`.
     - `backend/` và `shared/` tuyệt đối KHÔNG import `frontend`.
     - `backend/domain/` tuyệt đối KHÔNG import concrete infrastructure ngoài allowlist có lý do cụ thể.
   - Mọi vi phạm mới sẽ khiến suite kiểm thử thất bại ngay lập tức. Cấm xóa hoặc nới lỏng allowlist mà không có sự đồng thuận bằng văn bản.
