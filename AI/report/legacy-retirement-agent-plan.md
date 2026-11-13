# Kế hoạch thay thế và loại bỏ code legacy — bàn giao AI Agent

Ngày lập: **2026-11-13**. Trạng thái: **kế hoạch, chưa thực hiện refactor hoặc deletion**.

## 1. Mục tiêu, thẩm quyền và phạm vi

Mục tiêu cuối: code rõ trách nhiệm, đúng Modular Monolith theo nghiệp vụ/use case với Ports & Adapters có chọn lọc, dễ bảo trì/nâng cấp; mỗi hành vi có một implementation chuẩn, comment/docstring giải thích đúng contract và lý do.

Đọc [AGENTS.md](../../AGENTS.md) trước khi triển khai. Tài liệu này cụ thể hóa phần retirement trên nền [P0–P7](code-optimization-architecture-plan.md), [handoff R00–R13](modular-monolith-refactor-agent-handoff-plan.md) và [audit F1–F8](architecture-review-2026-11-13.md). Dùng mã **L00–L09** bên dưới để không nhầm các mã R đã có. Không khởi động lại mọi công việc trong kế hoạch cũ: kiểm chứng phần đã làm, tái sử dụng và chỉ xử lý phần thiếu.

Các mốc L là kế hoạch công việc, không phải bằng chứng source đã đạt. Hướng dẫn mới của người dùng và AGENTS hiện hành quyết định phạm vi. Nếu thay đổi contract làm đổi hành vi ngoài refactor, tách thành quyết định/đợt sửa riêng và ghi expected difference.

### Trong phạm vi

- Loại bỏ đường ghi/khóa song song, fallback không rõ semantics, wiring rải rác, private imports và orchestration/I/O đặt sai tầng.
- Migrate UI/API/CLI/tests về public application APIs; thu nhỏ rồi loại bỏ shim nội bộ không còn nghĩa vụ tương thích.
- Xóa code thật sự không còn cần thiết sau audit; giữ primitive/contract/re-export còn chức năng.
- Chuẩn hóa docstring/comments, ownership, evidence và kiểm thử hồi quy.

### Ngoài phạm vi

- Không thêm phương pháp extraction, entity resolution hoặc từ điển ngữ nghĩa mới. Bảo toàn gazetteer/bí danh hiện có.
- Không thay model/prompt/threshold, thuật toán retrieval, schema bundle hoặc nguồn sự thật chỉ để cleanup.
- Không nâng framework/dependencies, đổi toàn bộ frontend, triển khai microservices hoặc hỗ trợ đa tiến trình ngầm trong đợt này.
- Không xóa project data, snapshots, catalogs/history, prompt versions, training exports, model artifacts, graphify-out hoặc báo cáo lịch sử.
- Không đặt quota số dòng/file phải xóa. Code ngắn hơn nhưng khó hiểu hơn hoặc mất bảo đảm là không đạt.

## 2. Bằng chứng hiện trạng và giới hạn

Điểm xuất phát khi lập kế hoạch: HEAD `c92a6d6`, working tree có thay đổi tracked/untracked do các đợt UI/domain trước. Phải giữ chúng và chụp lại inventory khi Agent nhận việc.

- Graphify query đã thử và lỗi không tìm thấy command. Đã dùng graph JSON có phạm vi định vị rồi đọc source/callers. Agent triển khai vẫn phải thử môi trường Graphify hợp lệ theo AGENTS, không coi lỗi lần này là ngoại lệ vĩnh viễn.
- `ExtractionApplicationService.get_project_lock` và `_save_project_safe` vẫn có fallback khóa riêng/save trực tiếp. Graph QA service vẫn tự dựng Neo4j gateway khi không được inject.
- `backend/domain/catalogs/service.py`, `backend/domain/curation/service.py`, `frontend/state/session.py` là re-export/compatibility surface, còn callers thực tế. Ví dụ projects service/coordinator dùng catalog service; curation application dùng curation service; nhiều pages/components dùng session facade.
- UI sau khi tách file vẫn có import trực tiếp domain: `curation_table/entity_view.py`, `edge_logic.py`, `edc_review_table/drawer.py`, `evidence_panel/edge_inspector.py` và các merge components. Chia file đã cải thiện tổ chức nhưng chưa tự hoàn thành application boundary.
- Bốn file UI đơn tệp đang có trạng thái deleted trong git và được thay bằng package cùng tên. Không xóa package thay thế hoặc khôi phục file cũ chỉ vì kế hoạch trước nhắc đường dẫn cũ.
- Hai đường dẫn từng được nhắc trong kế hoạch cũ, `backend/integrations/llm_gateway.py` và `backend/workers/job_manager.py`, **không tồn tại** ở lần kiểm tra này. Chỉ ghi “không còn tại path này”; chưa chứng minh symbol đã biến mất mọi nơi. Không tạo lại chúng để rồi cleanup.
- Lần audit trước chạy isolated suite phát hiện 239 tests, 237 đạt, 1 failure/1 error do thiếu theme và template trong shadow workspace. Báo cáo frontend trước đó chạy lệnh khác và ghi 239 PASS. Không gộp các kết quả này; L00 phải tái lập đúng môi trường và log hiện tại.

Lượt lập kế hoạch này không chạy lại tests. Tất cả milestone bắt đầu ở NOT_STARTED; việc nào source đã hoàn thành phải được nghiệm thu lại bằng evidence rồi mới ghi VERIFIED_EXISTING.

## 3. Phân loại trước khi xóa

| Loại | Ý nghĩa | Hành động |
| --- | --- | --- |
| REPLACE | Còn được dùng nhưng sai boundary hoặc thiếu bảo đảm | Xây/hoàn thiện owner chuẩn, migrate consumers, test rồi bỏ implementation cũ |
| MIGRATE_CALLERS | Hành vi đúng nhưng caller đi qua tầng không phù hợp | Đổi boundary với parity, không viết lại thuật toán |
| KEEP_PUBLIC | Public contract/re-export có mục đích và consumer | Giữ tường minh; không xem là dead code |
| COMPAT_TEMP | Alias/shim phục vụ consumer cũ | Không thêm nghiệp vụ; có owner, consumers, điều kiện và đợt gỡ |
| DELETE_CANDIDATE | Có tín hiệu unused/duplicate | Audit đầy đủ, chưa được phép xóa chỉ từ static scan |
| REMOVED_OR_MOVED | Path cũ không còn hoặc đã chuyển | Xác nhận replacement/imports, tránh làm lại công việc |

**Quy tắc quyết định:** nếu không chứng minh được compatibility condition đã hết, giữ shim tối thiểu có hồ sơ; không kết luận “không có public consumers” chỉ vì rg không thấy. Một public module được cố ý hỗ trợ lâu dài có thể giữ nguyên, không cần đặt hạn xóa giả. Điều phải xóa là implementation trùng hoặc bypass không còn cần thiết.

## 4. Inventory ứng viên khởi đầu

Đây là danh sách điều tra, không phải danh sách lệnh xóa. L00 bổ sung symbol/caller đầy đủ và cập nhật theo working tree.

| ID | Path/symbol | Phân loại | Thay thế/owner chuẩn | Điều kiện bỏ phần cũ |
| --- | --- | --- | --- | --- |
| C01 | extraction application: get_project_lock, _project_locks, _save_project_safe | REPLACE | Public lock/commit contract do projects sở hữu | L03 chứng minh extraction và curation dùng cùng khóa và lifecycle |
| C02 | projects application: save_project, restore_snapshot; curation/schema fallback không coordinator | REPLACE | Command lifecycle explicit; pure transform tách persistence | Mọi consumer/fixture migrate, rollback/replay đạt; giữ tên API nếu còn nghĩa vụ tương thích |
| C03 | GraphQAApplicationService fallback Neo4jGateway; schema retriever/aligner/default_embedder wiring | REPLACE | Adapters/factories inject từ bootstrap | Fake adapter tests, toàn bộ bootstrap/test seams cập nhật |
| C04 | KGStudioFacade constructor wiring và forwarding methods | COMPAT_TEMP/MIGRATE_CALLERS | AppContainer + public use cases | Migrate UI/API/CLI/tests trước; chỉ bỏ symbol hết consumer/contract |
| C05 | frontend/composition.py direct implementation imports; cross-module private imports | MIGRATE_CALLERS | Public contracts; root giữ quyền wiring cần thiết | Guard và import tests đạt, không tạo cycle |
| C06 | domain extraction engines, schema retriever/aligner, semantic_clustering, graph QA gọi I/O | REPLACE theo trách nhiệm | Pure algorithm ở domain; orchestration application; SDK/file/network adapters | Parity theo engine/use case, rút cạnh allowlist đã migrate |
| C07 | catalogs/service.py, curation/service.py re-exports | MIGRATE_CALLERS/KEEP_PUBLIC/COMPAT_TEMP | Owner modules và public APIs | Không xóa cả file khi một symbol vẫn cần; xử lý cả test monkeypatch và __all__ |
| C08 | UI *_logic.py, inspectors, merge views import domain hoặc get_facade trực tiếp | MIGRATE_CALLERS | Presenter thuần hiển thị + application boundary | Không chuyển nghiệp vụ sang helper UI khác; AppTest và use case tests đạt |
| C09 | FrontendClient mixed local/HTTP, fallback và helpers | REPLACE/DELETE_CANDIDATE | Explicit transport/capability contract | Remote không local-mutate; audit từng method; không xóa nguyên client |
| C10 | frontend/state/session.py và components/*/__init__.py | KEEP_PUBLIC hoặc COMPAT_TEMP | State modules chuyên biệt; public re-export có mục đích | Giữ keys/ID/order; không xóa package marker hợp lệ; entry point package có thể giữ lâu dài |
| C11 | Hàm trùng, imports/dependencies/shims/config cũ phát hiện trong L00 | DELETE_CANDIDATE | Owner hiện có hoặc không cần replacement | Audit runtime/dynamic/registry/CLI/public; tests và packaging xác nhận |
| C12 | Comment/docstring tuyên bố “100%”, “atomic/SSOT” sai phạm vi, nhắc path đã chuyển | REPLACE | Contract mô tả đúng thực tế, liên kết ADR/evidence | Đọc code/test để sửa, không đổi behavior chỉ để khớp comment |

Không coi mọi file dưới backend/domain là legacy cần chuyển hết. Thuật toán thuần đang đúng trách nhiệm có thể giữ tại chỗ; ổn định public boundaries quan trọng hơn đồng nhất tên thư mục.

## 5. Artifacts bàn giao và trạng thái

L00 tạo `AI/report/legacy-retirement-evidence/<run-id>/`, với run-id theo ngày và hậu tố tránh ghi đè. Không tạo trước hàng loạt file rỗng trong lượt lập kế hoạch.

| Artifact | Nội dung bắt buộc |
| --- | --- |
| baseline.md | HEAD, dirty/untracked inventory/hash, Python/dependency versions, lệnh, test IDs/results, giới hạn |
| candidates.md | Cxx, path/symbol, loại, owner, callers/dynamic consumers, quyết định và milestone |
| contracts.md | Public APIs, engine IDs, exports, DTO/field semantics, state keys, local/remote capabilities |
| decisions.md | Quyết định architecture, compatibility policy, expected behavior corrections, alternatives/tradeoff |
| deletion-ledger.md | Mỗi phần đã xóa và chứng cứ trước/sau |
| feature-test-matrix.md | Feature/scenario → test ID → expected → actual → log |
| Lxx-result.md | Input revision/hash, phạm vi, files/symbols thay đổi, tests, graph, gaps và status |
| final-acceptance.md | Tổng hợp gate, remaining compatibility, hiệu năng, hướng dẫn bảo trì |

Trạng thái: NOT_STARTED, IN_PROGRESS, VERIFIED_EXISTING, PASS, PARTIAL, BLOCKED. PASS/VERIFIED_EXISTING cần đủ evidence. Milestone phụ thuộc không được nghiệm thu khi prerequisite còn PARTIAL/BLOCKED. Có thể làm read-only preparation độc lập, không xóa hoặc tích hợp trên contract chưa chốt.

Lệnh/tests thất bại phải giữ log đã loại secrets. Thư mục evidence không chứa bản sao project thật hay credentials.

## 6. Lộ trình và điều kiện chuyển mốc

| Mốc | Mục tiêu | Phụ thuộc | Liên hệ kế hoạch trước |
| --- | --- | --- | --- |
| L00 | Baseline tái lập và inventory | Không | R00, audit R0 |
| L01 | Contracts, ownership và guards | L00 | R01 |
| L02 | Wiring và public boundaries | L01 | R02 |
| L03 | Một lifecycle ghi và phạm vi khóa | L02 | R03, audit F1/F7 |
| L04 | Projection/cache freshness | L03 | R03, audit F2 |
| L05 | Tách I/O/orchestration khỏi domain | L04 | R04–R08 |
| L06 | Migrate UI/API/CLI và transport | L05 | R09–R10 |
| L07 | Retire compatibility và code dư | L06 | R11 |
| L08 | Chuẩn hóa comments và tài liệu | L07; thực hiện dần từ L01 | R13 một phần |
| L09 | Regression, hiệu năng, nghiệm thu | L08 | R12–R13 |

Mỗi mốc có thể chia nhiều thay đổi nhỏ theo use case. Ưu tiên schema → extraction → curation → graph QA → training trong L05, nhưng không tạo dependencies giả nếu các năng lực độc lập.

### L00 — Chốt baseline an toàn

**Đầu vào:** working tree, AGENTS, graph, reports và runner hiện tại.

**Thực hiện:**
1. Chụp HEAD/diff/untracked và xác định thay đổi người dùng cần giữ. Dùng Graphify hoặc fallback đúng quy định, đối chiếu graph provenance/HEAD; không suy luận freshness từ dirty flag.
2. Đếm test bằng discovery hiện tại, đọc runner và tài nguyên các test cần. Sửa đóng gói theme/template theo allowlist chính xác, dùng fixtures công khai/synthetic; không chạy suite trực tiếp trên data thật để né lỗi isolation.
3. Audit inventory C01–C12: imports, __all__, references, dynamic import, registry strings, CLI/config, side effects, packaging, monkeypatch và public consumers. Ghi một trong các loại ở mục 3 cho từng symbol.
4. Chạy full isolated suite làm baseline; tách lỗi harness, product bug và environment. Nếu lỗi ngoài phạm vi chưa xử lý, ghi BLOCKED cho gate liên quan, không xóa test.
5. Đo đường nóng sẽ đổi bằng fixture/seed/environment nhất quán; chưa có baseline thì không hứa tăng tốc.

**Đầu ra:** baseline/candidates/contracts sơ bộ, test/fixture manifest và log.

**Gate:** baseline tái lập, biết rõ failures; không bắt đầu deletion khi còn lỗi che hành vi cần bảo vệ. Path đã chuyển không bị xử lý như code thừa mới. Không dùng “239” làm số cố định cần giữ.

### L01 — Chốt ownership/contracts và mở rộng guards

**Đầu vào:** L00, public APIs/ports và guard hiện có.

**Thực hiện:** xác định owner từng use case, contract lock/commit/projection và consumer boundaries. Với APIs công khai cần giữ, ghi rõ thời hạn/điều kiện tương thích; chưa biết consumer ngoài repo thì giữ shell công khai và ghi giới hạn.

Bổ sung kiểm tra cross-module private imports, frontend → private backend/domain, adapters được dựng ngoài root và cycle module ở phạm vi phù hợp. AST guard chỉ là một lớp; dùng runtime/fake adapter/fault tests cho hành vi AST không chứng minh được. Có negative fixtures chứng minh guard bắt lỗi, bao gồm relative imports; không đánh dấu mọi dependency đồ thị là cycle sai kiến trúc.

Ngoại lệ legacy phải inventory cạnh cụ thể kèm milestone gỡ. Không thêm allowlist để hợp thức hóa vi phạm mới; thay đổi/nới guard phải tuân thủ AGENTS và phạm vi người dùng cho phép.

**Đầu ra:** contracts/decisions hoàn chỉnh và guard có bằng chứng phạm vi.

**Gate:** kiến trúc đích có tiêu chí tự động/kiểm tra thủ công tương ứng; lỗi mẫu khiến guard fail; không tạo Protocol/generic abstraction không có consumer.

### L02 — Thống nhất wiring và public imports

**Đầu vào:** L01; bootstrap, facade, frontend composition, schema/extraction/graph QA constructors.

**Thực hiện:**
1. Root dựng adapters hoặc factories có lifecycle rõ; inject qua ports. Chọn eager/lazy theo nhu cầu thật, không gọi mạng/đọc dữ liệu nặng khi import.
2. Chuyển service fallback dựng Neo4j/embedder/vector/LLM về root. Cập nhật test fixtures cùng đợt; không biến domain/application thành service locator.
3. Cross-module callers dùng public exports. Frontend composition nhận instance từ root; không dựng một container độc lập ngoài ý muốn.
4. Facade còn consumers thì forward/mapping tối thiểu. Nhánh constructor cũ có thể delegate factory tại root để giữ signature; không xóa trước khi migrate consumer/test seams.

**Đầu ra:** đường wiring chuẩn; adapters không còn bị dựng lại trong application đã migrate; danh sách compatibility còn giữ.

**Gate:** fake ports thay thế được provider/store; import không tạo I/O không mong đợi; không còn private cross-module import đã đưa vào phạm vi; smoke test UI/API composition và guard đạt.

### L03 — Thay đường ghi và khóa legacy

**Đầu vào:** L02; C01/C02, coordinator, mutation callers và revision/hash tests.

**Thực hiện theo use case, không thay save toàn cục bằng search/replace:**
1. Projects công bố contract dùng chung cho project identity/lock; xác nhận cùng ID cho load/save/extract/curate/restore. Tách `get_lock` khỏi protocol tùy ý nếu consumer thực sự cần; không truy cập field private.
2. Quy định candidate ownership và expected revision/idempotency. Executor không mutate state đang dùng trước save; enforce hoặc test contract, đo deepcopy nếu chọn.
3. Migrate extraction persistence về coordinator, giữ run/attempt/error semantics và thời điểm callback. Công việc gọi LLM có thể thực hiện ngoài lock rồi revalidate lúc commit; không kéo lock dài chỉ để dễ viết.
4. Migrate saves của curation/schema và mutation callers. Thiếu coordinator với persisted command phải lỗi rõ; pure simulation dùng API riêng không giả lập commit.
5. Define create/restore lifecycle của projects, tránh snapshot đệ quy hoặc đổi policy rollback ngoài ý muốn. Giữ export/config/secrets ngoài transaction project, qua adapters riêng.
6. Migrate callers rồi xóa `_save_project_safe`/lock fallback/sequence trùng nếu đủ điều kiện. Nếu phải giữ method API, nó chỉ forward vào lifecycle mới.

**Đầu ra:** mutation inventory → một commit lifecycle có policy theo command; compatibility forwarding không có đường ghi thứ hai.

**Gate bắt buộc:** preview không mutate; lỗi executor/snapshot/save giữ memory/disk theo contract; extraction–curation đồng thời có barrier test; hai object cùng project xử lý stale; replay và request hash conflict đúng; restart replay phù hợp; không mất evidence/history; không fake snapshot. Không tuyên bố multi-process safety bằng RLock.

### L04 — Thay đọc projection và cache thiếu độ mới

**Đầu vào:** L03; projects queries, SQLite adapter, vector/cache consumers.

**Thực hiện:** xác định freshness contract cho cả query nhận project object và query chỉ ID. Chọn resync, authoritative fallback hoặc kết quả stale/error tường minh; ghi lựa chọn. Migrate query callers để hiển thị/xử lý đúng. Derived status phải phản ánh lỗi thực, không nuốt lỗi invalidate rồi báo valid. Giữ JSON commit thành công khi projection sync lỗi.

**Đầu ra:** query boundary biết revision/freshness, resync chuẩn, cache identity theo nội dung/cấu hình liên quan. Chỉ thêm metadata tối thiểu qua quyết định contract; thay schema storage rộng phải tách đợt riêng.

**Gate:** fault sync → query không trả stale như mới; resync phục hồi; graph cùng số node/edge nhưng đổi nội dung không dùng cache cũ; đổi catalog/prompt/model làm invalidation đúng phạm vi; replay không mô tả sai trạng thái derived sau restart.

### L05 — Thay orchestration sai tầng bằng use cases và adapters

**Đầu vào:** L04; allowlist domain–infrastructure, C06/C07.

Chia theo 5 lát cắt. Với mỗi lát: ghi source symbol → target owner → input/output → consumers → parity tests, migrate rồi gỡ cạnh legacy tương ứng.

| Lát cắt | Phần giữ thuần | Phần cần chuyển/inject | Kết quả cần bảo toàn |
| --- | --- | --- | --- |
| Schema intelligence | Catalog rules, candidate scoring/validation đúng nghĩa thuần | Embedding/vector I/O, LLM verifier, orchestration | Catalog/model fingerprint, stale candidate policy, decisions |
| Extraction | Parsing/validation/normalization/chunk rules phù hợp | LLM calls, run lifecycle, settings/filesystem I/O | 4 engine IDs, prepared request/prompt pinning, token/error attempts |
| Curation | merge_core, evidence matching, eligibility, redirect rules | Semantic clustering I/O, persistence/orchestration | Evidence/offsets/observations/aliases/history/gazetteer feedback |
| Graph QA | Index/retrieval algorithms, sampling/text formatting thuần | LLM answering/paraphrase, file loading/export orchestration, Neo4j | Snapshot source isolation, PCST/PPR/Naive behavior, gold/demo distinction |
| Training | Train/serve formatters, record validation | Dataset export/model registry/filesystem boundary | JSONL/export format, split/provenance, optional dependency behavior |

Đọc hàm thực tế trước phân loại; tên file không chứng minh purity. Không đổi heuristic/model/prompt để “tối ưu” trong migration. Không gom sáu services thành god service mới; chia use case khi có trách nhiệm độc lập, không mỗi hàm một layer.

**Đầu ra:** domain thuần ở phần migrate, application qua ports, adapter I/O; các re-export service cũ chỉ còn vai trò được ghi.

**Gate:** parity từng lát + full offline/architecture trước đóng đợt; fixtures cover lỗi provider và unknown fields; allowlist rút đúng cạnh đã hết; các cạnh chưa xử lý không bị che dưới package-wide exemption.

### L06 — Migrate consumers, state và transport

**Đầu vào:** L05; pages, components, frontend client/composition, HTTP/CLI và tests.

**Thực hiện:**
1. UI mới gọi application APIs; business validation/merge/commit policy chuyển về owner. Presenter chỉ lọc/sắp xếp/format phục vụ hiển thị theo semantics đã thống nhất; không chuyển rule sang *_logic.py rồi gọi là đã tách nghiệp vụ.
2. Thay get_facade callers theo từng capability, giữ shell cho consumers chưa migrate. Test monkeypatch chuyển sang public boundary/fake port; giữ assertion hành vi.
3. FrontendClient chọn local/remote tường minh; matrix phương thức hỗ trợ. Remote unsupported báo lỗi, không local mutation; bỏ fallback mơ hồ sau khi caller xử lý đúng.
4. Giữ state modules đã tách. Quyết định `session.py` là public facade ổn định hay shim tạm; không tự xóa. Giữ keys/selection IDs, pagination, hai bảng EDC, draft invalidation và return context.
5. Migrate HTTP/CLI về cùng APIs, giữ endpoints/exports được hỗ trợ. Không mở endpoint mới hoặc thay framework chỉ để chứng minh layering.

**Đầu ra:** consumer matrix cập nhật; không còn business calls trực tiếp private domain trong UI đã migrate; transport rõ.

**Gate:** AppTest cho đổi project/source, chọn sau sort/filter/pagination, preview→apply, lỗi/stale/draft; local adapter spy không bị gọi khi chọn remote mutation; CLI/API smoke tests; baseline dùng chung graph và không giả approval.

### L07 — Xóa residue và kết thúc compatibility không còn cần

**Đầu vào:** L06, ledger/candidates và toàn bộ callers hiện tại.

**Thuật toán quyết định cho từng symbol:**
1. Quét lại source và metadata sau migration, không dùng caller list của L00 thay kiểm tra mới.
2. Xác nhận replacement đã dùng thực tế; nếu dead code thì ghi không cần replacement và lý do.
3. Kiểm tra public API/CLI/registry/config/dynamic imports/side effects/packaging/test seams; consumer ngoài repo chưa xác định thì không tùy tiện phá contract.
4. Ghi quyết định KEEP_PUBLIC, COMPAT_TEMP hoặc DELETE_APPROVED với evidence cụ thể. Trạng thái này là kết luận audit kỹ thuật, không thay yêu cầu phê duyệt nếu phạm vi người dùng chưa cho phép hành động phá tương thích.
5. Xóa implementation cũ, imports và private exports mất chức năng; chạy tests phù hợp và import/package smoke tests. Không giữ bản sao `_old.py`, `_v2.py` hay code commented-out để dự phòng; dùng version control trong phạm vi thay đổi riêng.
6. Cập nhật ledger, docs, graph. Nếu cần rollback, chỉ revert phạm vi đợt, không reset working tree hoặc phục hồi dữ liệu project thật.

**Đầu ra:** mỗi ứng viên có quyết định; code trùng/bypass nội bộ hết vai trò bị bỏ; compatibility có owner và condition, không tồn tại vô hạn do quên.

**Gate:** không có reference không chủ đích tới symbol đã xóa; registry/CLI/import tests đầy đủ; không xóa tests bảo vệ behavior; package public entry points hợp lệ còn nguyên. Facade không bắt buộc biến mất nếu vẫn có contract công khai; không được còn orchestration/persistence trùng trong facade.

### L08 — Chuẩn hóa comments/docstrings và cập nhật hiện trạng

**Đầu vào:** source sau L07, decisions/contracts, chuẩn mục 8.

**Thực hiện:** review comment/docstring ngay các file đã đổi; sửa mô tả trách nhiệm, mutation, concurrency, failure và compatibility. Gỡ comment sai, code chết bị comment-out, heading boilerplate không giúp hiểu. Mỗi comment giữ lại phải giải thích contract/lý do hoặc giới hạn khó thấy từ code.

Cập nhật structure/README/public API docs, AGENTS mục hiện trạng khi có evidence đóng debt; không biến AGENTS thành báo cáo dài. Giữ báo cáo lịch sử, thêm liên kết trạng thái mới khi cần. Sơ đồ mô tả dependency thực, phân biệt wiring với runtime calls.

**Đầu ra:** comments/docstrings đúng code, migration map và docs hiện trạng; không có tuyên bố zero skew/pure/atomic vượt kiểm chứng.

**Gate:** public use cases/ports/module đã migrate có documentation đủ; reviewer đọc contract biết input/output/side effects/errors và giới hạn khóa; examples không chứa secret và không hứa behavior chưa có.

### L09 — Nghiệm thu cuối và bàn giao nâng cấp

**Đầu vào:** L00–L08 PASS/VERIFIED_EXISTING và evidence.

**Thực hiện:** chạy full isolated suite hiện tại; architecture guard; các end-to-end offline mục 7; benchmark cùng fixtures; import/package/CLI smoke tests. Kiểm tra diff không chứa xóa dữ liệu hoặc đổi prompt/model/dependencies ngoài phạm vi. Chạy graphify update .; nếu tool bị chặn, ghi blocker và chưa coi gate cập nhật graph đạt.

**Đầu ra:** final-acceptance.md với test counts/exit/log, behavior corrections đã chấp thuận, số candidates đã xử lý theo loại, exceptions còn lại và hướng dẫn thêm use case/adapter.

**Gate cuối:** toàn bộ tiêu chí mục 10 đạt; mọi hạn chế còn lại được phân loại, không gọi PARTIAL thành PASS. Test xanh không thay thế kiểm tra compatibility/dependency bằng chứng.

## 7. Ma trận kiểm chứng tối thiểu

L00 ánh xạ scenario sang test IDs thực tế; tái sử dụng tests hiện có trước thêm mới.

| Nhóm | Scenario cần bảo vệ |
| --- | --- |
| Projects/storage | Create/load/save/restore, unknown fields, Unicode IDs, snapshot error, atomic rollback, stale revision |
| Concurrency/replay | Extraction và curation đồng thời; hai session objects; cùng request retry/hash khác; replay sau restart |
| Projection/cache | JSON commit rồi SQLite lỗi; query bằng ID/object; resync; same-size changed graph; vector invalidation |
| Schema/EDC | Hai bảng đề xuất, preview/apply, all_or_nothing/valid_only, stale candidates, định nghĩa/catalog/hash |
| Extraction | Bốn engines, prepared request parity, pinned prompt, chunk/attempt/error provenance, parallel callback/token accounting |
| Curation | Evidence ambiguous/missing, edit/approve/reject, merge N nodes, relations/types/triples, aliases/redirects/gazetteer/history |
| Baseline/graph | Raw artifacts không nhập approved graph; minimal normalization; diagnostics; snapshot isolation; PCST/PPR/Naive; export roundtrip |
| Evaluation/training | Gold độc lập khác demo graph-local, duplicate observations không tăng hit sai, export formatting/splits, optional deps |
| UI/API/CLI | Project/source switch, keys/selection/filter/page/draft/return context, remote unsupported/error không local mutation, endpoints/entrypoints |
| Packaging/secrets | Public imports/resources; synthetic fixture isolation; không credential trong log/artifact; import không gọi mạng |

End-to-end offline tối thiểu: (a) tài liệu → schema/EDC extraction → review/merge → approved snapshot → retrieval/export; (b) free triples → artifact → baseline graph → cùng retrieval/benchmark; (c) sync failure → đọc có trạng thái → resync; (d) lựa chọn remote → command unsupported/error → không local write.

Lệnh thực thi dùng runner hiện tại sau khi kiểm tra isolation, ví dụ:

```powershell
& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py tests.test_commit_coordinator
& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py tests.test_architecture_boundaries
& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py
graphify update .
```

Chỉ chạy targeted tests phù hợp; full suite đã bao gồm architecture thì không cần lặp riêng khi không có thay đổi mới. Ghi interpreter/version thực tế; live LLM/Neo4j chỉ opt-in. Nếu thay hot path, p95/peak memory hồi quy >10% phải điều tra/giải thích cùng fixture/seed; không so số có tracing với số không tracing như cùng benchmark.

## 8. Chuẩn comment và docstring

### Quy ước

- Giữ tên identifiers tiếng Anh hiện có; docstring/comment mới trong phần migrate dùng tiếng Việt rõ ràng, giữ thuật ngữ kỹ thuật chính xác. Không dịch hàng loạt source ngoài phạm vi.
- Module docstring: trách nhiệm, owner/layer, boundary quan trọng và compatibility nếu có. Không chép sơ đồ toàn dự án vào mỗi file.
- Public use case/port và thuật toán có invariant khó: một câu tóm tắt; Args/Returns/Raises theo Google style khi cần; nêu mutation, persistence, concurrency/idempotency và units/normalization khi ảnh hưởng caller. Không lặp type hints vô ích.
- Helper hiển nhiên không bắt buộc docstring dài. Inline comment giải thích **vì sao** và điều kiện an toàn; không kể lại `for`, `if`, gán biến.
- TODO/FIXME chỉ tồn tại khi có ID candidate/decision, điều kiện hoàn thành và owner/milestone. Không viết “cleanup later” không đầu mối.
- Comment compatibility ghi consumer/contract còn giữ và điều kiện gỡ. Không xóa comment provenance/license có nghĩa vụ.
- Không dùng “thread-safe”, “atomic”, “immutable”, “100%”, “zero skew” nếu không nêu phạm vi và bằng chứng; không nói cả bundle atomic chỉ vì một file dùng replace.
- Sửa code phải cập nhật comment trong cùng đợt. Không giữ code cũ trong comment; lịch sử nằm ở version control và ledger.

### Ví dụ minh họa, không phải API đã tồn tại

```python
def apply_change(project, request):
    """Áp dụng thay đổi đã xác thực qua lifecycle commit của projects.

    Args:
        project: Trạng thái dự án tại revision mà caller đang sử dụng.
        request: Phạm vi và khóa idempotency của thao tác.

    Returns:
        Kết quả authoritative commit và trạng thái đồng bộ projection.

    Raises:
        ValueError: Request không hợp lệ hoặc revision đã thay đổi.

    Notes:
        Chỉ cập nhật project sau khi lưu authoritative thành công.
        Khóa trong process không bảo đảm an toàn giữa nhiều process.
    """
    ...

# Không dùng số dòng làm ID: sort/filter có thể đổi thứ tự giữa hai rerun.
selected_ids = resolve_selected_ids(rows, selection)

# COMPAT C04 / L07: giữ import path cho consumer được ghi trong candidates.md.
# Gỡ khi consumer matrix và nghĩa vụ public API đều đã được xử lý.
```

Agent phải chỉnh docstring theo chữ ký và exception thật; không copy ví dụ như bảo đảm implementation hiện tại. Không thêm dependency lint chỉ để kiểm tra comment trong đợt refactor; dùng review checklist và tooling sẵn có.

## 9. Mẫu bàn giao cho Agent và deletion ledger

### Task packet

```text
Milestone: Lxx; trạng thái prerequisite và link evidence.
Input: HEAD + dirty inventory/hash; paths/symbols đã kiểm chứng.
Goal: hành vi/boundary cuối cùng cần đạt.
Allowed scope: files/modules có thể sửa; protected behavior/data.
Contract: input/output/errors/mutation/compatibility phải giữ.
Steps: implement owner → migrate callers/tests → audit → retire.
Validation: targeted tests, full suite, architecture, perf nếu cần.
Deliverables: source mapping, Lxx-result, ledger, docs, graph status.
Stop/gap: consumer chưa xác định, parity fail, schema/prompt cần đổi ngoài scope.
```

Agent đọc AGENTS và dùng Graphify trước khám phá source. Không tự spawn thêm agents từ tài liệu này. Nếu nhiều người cùng làm, không deletion/final acceptance trong khi source đang được người khác mutate; phối hợp ownership và nhận lại baseline mới.

### Một dòng ledger bắt buộc

| ID | Path/symbol và hành vi cũ | Quyết định/lý do | Consumers đã audit | Replacement | Compatibility condition | Tests/log | Status/đợt |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Cxx | Điền đường dẫn/symbol cụ thể | Replace/delete/keep | Static, dynamic, CLI/config, public, monkeypatch | API mới hoặc không cần | Bằng chứng điều kiện gỡ đã đạt | Lệnh, exit, file log | Chưa đánh dấu DONE nếu thiếu |

Rollback theo change set độc lập; không dùng hard reset/clean để xóa thay đổi người dùng. Lưu thông tin rollback trước khi xóa symbol, không giữ bản sao implementation cũ trong runtime package. Nếu rollback cần đổi persisted format thì thay đổi đó đã vượt cleanup và phải có migration design riêng.

## 10. Định nghĩa kết quả cuối cùng

Chỉ ghi hoàn thành toàn bộ khi:

1. Mỗi use case có owner, public contract và một implementation nghiệp vụ chuẩn; wiring ở root, I/O ở adapters, domain đã migrate thuần.
2. Không còn persisted mutation bypass lifecycle trong phạm vi đã cam kết; khóa/project identity thống nhất; concurrency/rollback/replay có bằng chứng.
3. Projection/cache không âm thầm trả dữ liệu stale như mới; authoritative/derived roles rõ.
4. UI/API/CLI dùng application boundary; transport không âm thầm local-mutate khi remote được chọn.
5. Mọi candidate được xử lý hoặc có quyết định giữ có lý do; không còn implementation trùng chỉ để tương thích. Public shim còn nghĩa vụ được giữ tối thiểu, có consumer/điều kiện gỡ hoặc xác định là stable public API.
6. Public registrations/exports/DTO/state contracts và hành vi baseline được bảo toàn; không đổi thuật toán/prompt hoặc dữ liệu thật ngoài phạm vi.
7. Comments/docstrings đúng code, đủ giải thích invariant và giới hạn; không có code cũ commented-out hoặc tuyên bố quá mức.
8. Full offline suite, architecture checks và các scenario bắt buộc đạt; số liệu performance có baseline tương đương nếu hot path đổi.
9. Ledger, contract/consumer matrix, docs hiện trạng và graph được cập nhật/kiểm chứng; blocker còn tồn tại được báo, không che bằng trạng thái PASS.

Thước đo thành công là giảm số nơi phải sửa khi thêm một use case/adapter, làm rõ ownership và tăng khả năng kiểm chứng. Số LOC giảm chỉ là số liệu phụ; giữ một public re-export rõ ràng có thể tốt hơn xóa nó rồi làm caller phụ thuộc private implementation.
