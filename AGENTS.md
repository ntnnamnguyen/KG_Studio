# Hướng dẫn làm việc với KG Studio

Áp dụng cho toàn repository. Cập nhật: **2026-11-13**.

## 1. Định hướng và cách đọc tài liệu

KG Studio là ứng dụng Python theo **Modular Monolith theo nghiệp vụ/use case, với Ports & Adapters có chọn lọc**. Giữ in-process execution mặc định. Mục tiêu: dễ hiểu, dễ kiểm thử, mở rộng có ranh giới và bảo toàn dữ liệu; không giảm LOC bằng cách che dependency hoặc mất semantics.

- **PHẢI/KHÔNG ĐƯỢC** là yêu cầu cho code mới và phần được migrate.
- **Hiện trạng/legacy** mô tả giới hạn đang tồn tại, không cấp phép sao chép vi phạm sang code mới.
- Chỉ công bố một bất biến đã đạt khi đã kiểm chứng implementation và kiểm thử tương ứng. Quy tắc trong file này không tự chứng minh source đã tuân thủ.
- Không rewrite toàn dự án trong một đợt cleanup. Tách refactor khỏi thay thuật toán/prompt, schema lưu trữ và nâng dependency.

| Tài liệu | Cách sử dụng |
| --- | --- |
| [Bản đồ dự án](AI/structure.md) | Định vị luồng/file; có phần mô tả legacy, cần đối chiếu source |
| [Kế hoạch P0–P7](AI/report/code-optimization-architecture-plan.md) | Gate migration và hiệu năng; không coi mọi gate đã hoàn tất |
| [Phản biện kiến trúc](AI/report/architecture-review-2026-11-13.md) | Bằng chứng và ưu tiên F1–F8/R0–R5 tại thời điểm audit |
| [Kế hoạch UI/UX](AI/layout/ui-ux-improvement-plan.md) | Định hướng UI, kiểm tra tiến độ thực tế trước triển khai |
| [Đặc tả UI](AI/layout/current_ui_layout_spec.md) | Điểm bắt đầu định vị giao diện, không thay cho source hiện tại |

Source và phép kiểm chứng quyết định hiện trạng. Khi tài liệu/graph khác source, ghi sai khác và cập nhật trong phạm vi nhiệm vụ. Không dùng tuyên bố “100%”, “production-ready” hoặc số test trong báo cáo cũ thay bằng chứng mới.

## 2. Graphify và khám phá code

Repository có knowledge graph tại graphify-out/.

1. Khi người dùng gọi /graphify, đọc và áp dụng skill/instructions Graphify được cài trước các thao tác khác.
2. Khi graphify-out/graph.json tồn tại, chạy **graphify query "<câu hỏi>" trước lần grep/search/đọc source đầu tiên** cho câu hỏi về codebase. Nếu có giao việc cho subagent khám phá code, đưa quy tắc này vào prompt; mục này không yêu cầu tự tạo subagent.
3. Dùng graphify path "<A>" "<B>" cho quan hệ; graphify explain "<khái niệm>" cho nội dung hẹp. Chỉ đọc source có phạm vi tại vị trí graph hoặc lần đọc trước đã định vị.
4. Nếu có graphify-out/wiki/index.md, dùng để điều hướng tổng quan. Đọc GRAPH_REPORT.md khi review kiến trúc rộng hoặc query/path/explain chưa đủ.
5. Graph dirty là bình thường, không phải lý do bỏ Graphify. Chỉ bỏ khi nhiệm vụ là sửa/đánh giá graph sai, stale hoặc người dùng yêu cầu không dùng.
6. Nếu CLI không chạy: báo lệnh/lỗi, kiểm tra môi trường cài đặt được phép; dùng graph JSON/report có phạm vi làm fallback và kiểm chứng source. Không lặp vô ích executable đã thất bại. Trước deletion phải đối chiếu trạng thái graph với HEAD và callers hiện tại.
7. Sau thay đổi **mã nguồn**, chạy **graphify update .** (AST-only, không gọi LLM). Nếu bị chặn, ghi phần chưa cập nhật và lý do; không sửa generated graph bằng tay hoặc báo đã cập nhật.
8. graph.json có thể được rewrite toàn bộ; diff lớn do build không tự nó là lỗi hay lý do bỏ hooks/rebuild. Không xóa graphify-out/ để giảm diff. Sửa tài liệu đơn thuần không yêu cầu rebuild source graph.

## 3. Hiện trạng và nợ migration

Đã có 6 modules, backend/bootstrap.py, ProjectCommitCoordinator, ports/public APIs, snapshot đồ thị dùng chung và bộ kiểm thử offline. **Migration chưa hoàn tất.** Các điểm dưới đây được đối chiếu source ngày cập nhật; phải kiểm tra lại trước khi sửa, không mặc định lỗi còn tồn tại mãi.

| Hiện trạng | Vị trí cần kiểm tra | Quy tắc khi can thiệp | Trạng thái (2026-11-13) |
| --- | --- | --- | --- |
| Đã loại bỏ fallback ghi thiếu coordinator trong curation/schema | curation/schema application services | Yêu cầu commit_coordinator bắt buộc; cấm bypass commit lifecycle | ĐÃ GIẢI QUYẾT (L03) |
| Extraction và Projects dùng chung lock từ coordinator | extraction service, commit coordinator | Thống nhất get_project_lock trên CommitCoordinatorPort | ĐÃ GIẢI QUYẾT (L02, L03) |
| Projection queries đã có freshness guard | projects service (query_*_page) | Trả về cờ sync_pending và sync_error rõ ràng | ĐÃ GIẢI QUYẾT (L04) |
| Cross-module private import & wiring rải rác đã được dọn sạch | bootstrap, facade, frontend composition | 100% qua .public; AST guard Quy tắc 5, 6, 7 bảo vệ | ĐÃ GIẢI QUYẾT (L01, L02) |
| Domain còn cạnh infrastructure được allowlist (13 cạnh) | architecture tests | Giữ lý do/gate gỡ cụ thể, không phát sinh cạnh mới | ĐANG KIỂM SOÁT (L05) |
| Architecture tests được mở rộng thành 8 rules | tests/test_architecture_boundaries.py | Bắt cross-module private import, repo direct import, public only | ĐÃ MỞ RỘNG (L01) |
| Runner offline thiếu tài nguyên tại lần audit cũ | tools/run_isolated_tests.py | Khai báo fixture/theme chính xác (.streamlit, hanoi gazetteer) | ĐÃ GIẢI QUYẾT (L00) — 239/239 PASS |

Không bắt buộc sửa toàn bộ legacy trong một nhiệm vụ nhỏ. Giữ hành vi còn consumer, ghi nợ ngoài phạm vi. Nếu chức năng mới cần invariant còn thiếu, hoàn thiện phần đó hoặc báo rõ giới hạn; không dựa vào bảo đảm chưa tồn tại.

## 4. Ownership và chiều phụ thuộc

### 4.1. Sáu module nghiệp vụ

Mỗi use case mới có một module chịu trách nhiệm chính. public.py công bố exports tường minh; application/ điều phối use cases. Chỉ thêm ports/domain/adapters/package khi có nhu cầu thật, không tạo layer rỗng.

| Module | Trách nhiệm |
| --- | --- |
| projects | Project lifecycle, identity/revision, commit coordinator, snapshots, freshness/resync của projection |
| schema_intelligence | Danh mục, đề xuất và quyết định EDC, retrieval/alignment, invalidation liên quan |
| extraction | Tài liệu/chunking, phiên bản prompt, prepared request, engine registry, attempts/runs, orchestration trích xuất |
| curation | Duyệt/sửa dữ kiện/hồ sơ, bằng chứng, gộp thực thể/quan hệ/bộ ba, bí danh và phản hồi từ điển hiện có |
| graph_qa | Graph snapshots, baseline KG dẫn xuất, retrieval/QA, benchmark, graph export và Neo4j |
| training | Boundary xuất dữ liệu huấn luyện và tích hợp ml_lab; train/serve formatting thống nhất |

UI đặt quản lý từ điển ở trang nào không đổi ownership nghiệp vụ. Phối hợp liên module qua public contracts, không gọi implementation private.

### 4.2. Ranh giới bắt buộc

- **Domain:** quy tắc/thuật toán thuần; không import UI/framework, concrete repository/gateway/SDK, không đọc config/secrets/filesystem. Phân loại code legacy theo trách nhiệm trước khi chuyển, không chỉ đổi thư mục.
- **Application:** orchestration qua ports/core contracts; không tự tạo concrete adapters hoặc lấy global singleton để giải quyết dependency mới.
- **Adapters:** I/O và chuyển đổi cho ports; không tự quyết định policy nghiệp vụ thuộc use case.
- **Composition root:** backend/bootstrap.py wiring concrete dependencies, được import implementation cần thiết cho wiring; không chứa thuật toán nghiệp vụ. Quyền này không áp dụng cho module tùy ý import nhau.
- **Frontend composition:** frontend/composition.py cung cấp application boundaries đã được root dựng, không tạo root nghiệp vụ thứ hai. UI/HTTP/CLI mới gọi public application APIs; không chứa merge, business validation, snapshot/save sequence hoặc transaction policy.
- **Public boundary:** module A chỉ dùng backend.modules.B.public hoặc contract B công bố. Không cross-module internal import. Không wildcard import hoặc __getattr__ delegation để che dependency.
- **Shared:** không import backend/frontend/ml_lab. Chỉ chia sẻ helper/contract cùng semantics thực sự; config/secrets/I/O legacy phải có owner, không lan vào pure domain.
- **Facade:** KGStudioFacade là compatibility boundary, không bổ sung nghiệp vụ. Giữ forwarding và mapping tương thích tối thiểu; không ép “một dòng” nếu mất semantics. Migrate callers/test seams rồi mới bỏ shim hoặc nhánh wiring cũ.
- **ML:** training code không phụ thuộc frontend/facade. Dùng contracts/formatters chung với serving; không khẳng định zero skew khi chưa test parity.
- Không tạo import cycle; kiểm tra import graph/AST/runtime phù hợp trước khi kết luận. Không thêm mediator, event bus, generic repository/service hoặc microservices khi chưa có nhu cầu cụ thể được ghi lại.

## 5. Dữ liệu, khóa và commit

### 5.1. Nguồn sự thật và phạm vi lưu

- **JSON project bundle là authoritative; SQLite là read projection; vector index và baseline graph là derived data.** Không gọi SQLite là nguồn sự thật thứ hai. Đổi storage cần migration riêng.
- Mutation nghiệp vụ ghi project bundle mới hoặc được migrate phải qua lifecycle ProjectCommitCoordinator. Không truy cập coordinator.project_store.save_project() để lách commit().
- Cấu hình ứng dụng, secrets, file export và model artifacts có adapter/use case riêng; không ép chúng vào transaction project một cách máy móc. UI không tự thực hiện nghiệp vụ I/O.
- Project creation, restore/resync có lifecycle policy rõ thuộc projects. Không sao chép sequence lock/snapshot/save sang module khác; giữ API legacy có consumer trong giai đoạn migration.

### 5.2. Invariants cần bảo toàn

1. Preview không mutate/ghi dữ liệu nghiệp vụ. Apply kiểm tra scope, expected revision, stale state, request hash/idempotency và policy all_or_nothing/valid_only tương ứng.
2. Dùng cùng project identity và lock contract giữa các use case ghi. Không tạo lock độc lập rồi mô tả là khóa toàn hệ thống. RLock chỉ bảo vệ trong process; nhiều process/worker cần giải pháp và tests riêng.
3. Candidate tách khỏi state đang sử dụng; chỉ cập nhật memory sau authoritative commit thành công. Coordinator hiện gọi executor(project), nên caller phải bảo đảm không mutate đầu vào trước save. Thay contract này cần fault tests và đo chi phí.
4. Giữ snapshot, atomic bundle/rollback và khôi phục đã hỗ trợ. Thiếu snapshot capability phải báo lỗi, không trả đường dẫn snapshot giả.
5. SQLite sync lỗi thể hiện sync_pending và hỗ trợ resync. Query mới/migrate xử lý freshness theo contract: kiểm tra revision, resync, đọc authoritative hoặc trả trạng thái stale rõ; không trả như dữ liệu mới khi chưa bảo đảm.
6. Vector/cache invalidation gắn với fingerprint dữ liệu/cấu hình thực dùng. Không báo derived data hợp lệ khi cập nhật thất bại; không dùng số lượng phần tử làm cache identity duy nhất.
7. Merge bảo toàn observations, evidence/offsets, aliases, redirects, document links, trạng thái và audit history. Collapse cạnh/self-loop chỉ theo policy đã kiểm chứng.
8. Không ghi secrets vào project/snapshot/trace/log/export/fixture. Lỗi phải đủ thông tin chẩn đoán mà không lộ credentials.

Code mới không fallback mutation thiếu coordinator. Pure transform/preview phục vụ test là API riêng, không giả lập commit thành công.

## 6. Extraction, baseline và tính đúng đắn nghiên cứu

- Giữ registrations closed, edc, edc_plus_r, free_triples và public formats đang hỗ trợ. Refactor không tự đổi thuật toán/prompt/model, ngưỡng, schema hay chuẩn hóa tên.
- Giữ prompt version pinning, prepared-request parity/hash, actual fitted input, provenance từng attempt/run, token accounting và train/serve formatting.
- **free_triples là baseline B:** extraction chỉ lưu artifacts thô. Không gọi EDC ingestion/definitions/retrieval/alignment/semantic merge hoặc ghi graph vào project.nodes/edges. Giữ raw labels, duplicates, failed attempts và invalid items kèm diagnostics.
- KG baseline thuộc graph_qa, đọc runs qua public API extraction được inject bằng port. Policy surface-nfc-casefold-v1 chỉ chuẩn hóa Unicode NFC/khoảng trắng/casefold cho khóa node; giữ raw forms/predicate/observations. Không dùng catalog/aliases/redirects làm giàu baseline.
- Không tự chọn attempt “tốt nhất” hoặc trộn nhiều attempt cùng đoạn trái policy; không giả lập human approval.
- Dùng chung GraphSnapshotDTO và graph application APIs. Chọn nguồn tường minh; không fallback approved rỗng sang all hoặc graph cũ. Export/training kiểm tra nguồn/scope thực tế, không tin riêng metadata của file nhập.
- So các KG cần gold độc lập và điều kiện thí nghiệm rõ. Câu hỏi tự sinh trên mỗi graph phải được ghi là demo trong graph đó. Đúng cấu trúc, đã duyệt và đúng lịch sử là ba khái niệm khác nhau.

## 7. Contracts, transport và UI

- Dùng Pydantic v2 tại biên phù hợp; bundle dict vẫn hợp lệ. Không ép qua DTO thiếu trường rồi ghi đè storage. Đổi conversion phải test unknown fields, default/null, IDs, Unicode và roundtrip.
- Không đổi global extra policy hoặc xóa .from_dict/.to_dict để giảm LOC. Compatibility còn consumer cần kế hoạch migrate và parity tests.
- Local/HTTP có lựa chọn và capability rõ. Code mới không gọi local mutation khi remote đã được chọn; lỗi HTTP không fallback ghi local. Capability chưa hỗ trợ trả lỗi rõ.
- Giữ public API/CLI/exports. Chỉ gỡ shim sau khi migrate consumers và xử lý nghĩa vụ tương thích; ghi điều kiện gỡ.
- UI hướng nhiệm vụ, ưu tiên người không chuyên; ẩn cấu hình nâng cao không được tự đổi semantics. Thao tác phá hủy/lô phải thể hiện phạm vi và tác động trước apply.
- Giữ session keys hoặc có migration rõ; selection theo ID, draft invalidation, pagination, hai bảng EDC và return context. Đổi project/nguồn phải vô hiệu state không còn phù hợp.
- Đối chiếu Streamlit version thực tế và API hỗ trợ; không nâng framework kèm refactor. Ưu tiên widget/theme chính thức, hạn chế CSS phụ thuộc DOM nội bộ.
- AppTest chứng minh state/hành vi, không thay kiểm tra trình duyệt về bố cục/focus/accessibility hoặc usability với người thật. Ghi rõ loại kiểm thử đã thực hiện.

## 8. Tái sử dụng và xóa code

- Kiểm tra implementation trước viết helper. Tái sử dụng merge_core, selection_core, pagination/action bar, extraction lifecycle và formatters khi cùng semantics.
- Một rule/lifecycle có một owner. Chỉ trích abstraction khi có consumer/test seam thật; không gom chỉ vì giống cú pháp.
- File >500 dòng hoặc class nhiều capability cần review trách nhiệm khi sửa đáng kể. Ghi lý do giữ hoặc kế hoạch tách; LOC không là hard gate.
- Trước xóa audit callers/imports, __all__, dynamic import, registry, CLI, config, side effects, test seams và public consumers. Graph thiếu cạnh/static analyzer báo unused chỉ tạo ứng viên điều tra.
- Migrate caller trước; ghi **deletion ledger** trong báo cáo đợt: path/symbol, lý do, consumers đã kiểm tra, thay thế, compatibility condition, tests/kết quả.
- Không xóa test còn bảo vệ hành vi để làm suite xanh; chuyển test sang boundary mới. Không xóa package markers/re-exports có chức năng chỉ vì ngắn.
- Cleanup source không cho phép xóa project data, snapshots, catalogs/history, prompt versions, training exports, model artifacts, báo cáo lịch sử hoặc graphify-out/.

## 9. Quy trình kiểm chứng và hoàn thành

### Trước khi sửa

1. Xác định phạm vi và working tree; không reset/ghi đè thay đổi sẵn có ngoài nhiệm vụ.
2. Dùng Graphify theo mục 2, đọc public contracts/source/tests liên quan, xác định owner và caller.
3. Chọn tiêu chí nghiệm thu. Tách refactor khỏi thay thuật toán/prompt, storage schema hoặc dependency; với lỗi cần sửa, xác định phép tái hiện.

### Khi triển khai

- Không nhân rộng legacy. Ngoại lệ phải theo cạnh import/đường gọi cụ thể, lý do, đợt/điều kiện gỡ và test bảo vệ; không allowlist cả package.
- Không nới/xóa guard hoặc allowlist chỉ để PASS. Rút ngoại lệ sau migration là bắt buộc; thêm/nới ngoại lệ cần quyết định được ghi và nằm trong phạm vi người dùng cho phép.
- Guard hiện chưa bao phủ mọi invariant. Thay boundary cần negative tests cho guard và kiểm thử hành vi cần bảo vệ; không chỉ kiểm tra chuỗi source.
- Tests/benchmarks dùng thư mục tạm, synthetic fixtures/fake adapters; không sửa config/dữ liệu/secrets thật. Tài nguyên test công khai phải khai báo/copy chính xác, không copy toàn data/.

### Chạy kiểm thử

Dùng Python >=3.11 của chính KG Studio, ưu tiên .venv-win; ghi version/lệnh thực tế. Không cài dependency vào KG_Studio_MVP hoặc môi trường ngoài phạm vi nhiệm vụ.

Lệnh PowerShell mẫu:

```powershell
# Test liên quan: thay module theo phạm vi thay đổi
& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py tests.test_commit_coordinator

# Architecture checks trong workspace cô lập
& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py tests.test_architecture_boundaries

# Full offline suite, đã bao gồm architecture checks
& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py
```

Yêu cầu:

- Commit/lock: fault injection, đồng thời giữa use cases, stale revision, replay/restart theo rủi ro thay đổi. Merge/contracts: lossless parity và rollback phù hợp.
- Trước kết thúc đợt refactor source phải chạy full offline suite, bao gồm architecture checks. Không cần chạy lặp riêng khi full đã đạt nếu không có thay đổi/lo ngại mới. Live LLM/Neo4j chỉ opt-in.
- Lỗi fixture/runner vẫn là ca chưa đạt; sửa đóng gói an toàn hoặc báo giới hạn, không skip/xóa để công bố xanh. Không lấy số test lịch sử làm mục tiêu cố định.
- Thay đường nóng phải đo trước/sau cùng fixture/seed/environment. Hồi quy p95 hoặc peak memory >10% cần điều tra, giải thích tradeoff; không suy đoán nhanh hơn từ LOC.
- Chỉ sửa tài liệu: kiểm tra nội dung, links và diff. Không yêu cầu suite chạy lại và không tuyên bố đã chạy nếu chưa chạy.

### Trước khi báo hoàn thành

1. Kiểm tra diff/phạm vi và bảo toàn thay đổi ngoài nhiệm vụ.
2. Khi implementation đổi, cập nhật AI/structure.md, README, public exports và contract docs liên quan; không viết kiến trúc đích thành hiện trạng.
3. Sau source changes, chạy graphify update . hoặc ghi blocker theo mục 2.
4. Báo kết quả, lệnh/test đã chạy, lỗi/giới hạn và việc còn lại. Không gọi toàn bộ đợt hoàn tất nếu tiêu chí bắt buộc còn chưa được xác minh.
