# Kế hoạch bàn giao tái cấu trúc KG Studio cho AI Agent

- Ngày lập: **12/11/2026**.
- Trạng thái: **READY FOR IMPLEMENTATION — chưa thực thi các bước R00–R13 trong tài liệu này**.
- Phạm vi hiện tại: lập kế hoạch. Không coi tài liệu này là bằng chứng đã xóa code, sửa lỗi hoặc chạy lại tests.
- Đích: **Modular Monolith theo nghiệp vụ/use case, Ports & Adapters có chọn lọc**.
- Không thêm kỹ thuật entity resolution mới; không xây tính năng quản trị/tích hợp từ điển ngữ nghĩa mới. Giữ nguyên duplicate suggestions, merge, semantic clustering và synonym expansion đang có.
- Quy tắc nền: [AGENTS.md](../../AGENTS.md). Tài liệu tham chiếu: [structure.md](../structure.md), [kế hoạch kiến trúc ban đầu](code-optimization-architecture-plan.md), [deletion ledger](deletion-ledger.md), [graph report](../../graphify-out/GRAPH_REPORT.md).

## 1. Cách agent tiếp nhận và sử dụng kế hoạch

Đây là checklist thực thi chi tiết cho phần chuyển đổi còn lại. Kế hoạch kiến trúc ban đầu giữ vai trò thiết kế nền; không lặp lại các hạng mục đã được triển khai một phần. Nếu tên file, signature hoặc caller đã thay đổi khi nhận việc, agent phải cập nhật mapping bằng bằng chứng nguồn trước khi sửa.

1. Đọc AGENTS.md và tài liệu này; nhận **một mã bước Rxx** hoặc một nhóm bước có dependency đã hoàn tất.
2. Chạy `graphify query "<câu hỏi của bước>"` trước khi tìm/đọc nguồn; dùng path/explain cho quan hệ. Nếu CLI lỗi, ghi lỗi và dùng graph JSON/report để định vị theo fallback trong AGENTS.md.
3. Chốt input revision + working-tree fingerprint, đọc output/report của bước phụ thuộc. Không đồng nhất HEAD với toàn bộ workspace khi có untracked/modified files.
4. Xác nhận phạm vi file được sửa và hợp đồng phải giữ. Chỉ chạy tests sau khi dữ liệu/cấu hình test được cô lập.
5. Implement, migrate callers, xóa implementation cũ đủ điều kiện, chạy targeted tests và full offline suite tại gate. Không dừng ở tạo folder/interface hoặc viết báo cáo.
6. Giao output source + tests + evidence + báo cáo bước. Agent sau chỉ tiếp nhận khi gate PASS; `BLOCKED`/`PARTIAL` không được đổi tên thành DONE.

Mỗi bước có đúng một owner chịu trách nhiệm nghiệm thu. Có thể giao nhiều agent các module khác nhau sau R03, nhưng các file chung như bootstrap, public contracts, facade, session và API phải được tích hợp tuần tự bởi owner; không cho nhiều agent cùng sửa chúng.

## 2. Baseline đã quan sát, chưa phải kết quả kiểm thử

- HEAD tại lúc khảo sát: `5351cfa6b8a4f60d8ef832676c33fe602cef8ae3`.
- Working tree có nhiều thay đổi/untracked/deletions do các đợt trước; phải giữ nguyên và tiếp tục trên snapshot này. Không reset về HEAD để dựng baseline.
- Graph hiện ghi cùng HEAD, có **2.013 nodes / 6.424 edges**. Cùng commit không chứng minh graph khớp mọi thay đổi chưa commit; kiểm chứng file/symbol khi làm việc.
- CLI `graphify query` chưa có trong PATH của phiên lập kế hoạch. Không sửa generated graph bằng tay; R00 xác định executable hợp lệ, R13 cập nhật lại graph bằng công cụ.
- Đã có `backend/bootstrap.py`, `frontend/composition.py`, projects ports/service/coordinator, catalog split và relation merge split. Cần sửa/hoàn thiện chúng, không tạo bản thứ hai.
- Đã bỏ `_post_api`, worker package và LLM legacy shim trong working tree. Agent chỉ verify việc xóa và consumer parity; không dựng lại rồi xóa lại.
- Số dòng nguồn hiện tại: facade 1.585; client 502; session 1.370; curation table 1.197; entity merge 642; graph retriever 1.208; QA generator 1.365. Đây là tín hiệu phân chia trách nhiệm, không là chỉ tiêu cắt LOC.
- Đếm tĩnh thấy **20 file `test_*.py`, 142 test methods**. Runner đang liệt kê 19 file. Các con số này chưa là số tests đã discovery/chạy thành công.

### Những điểm phải xử lý ở các bước đầu

| Mã | Bằng chứng nguồn lúc khảo sát | Yêu cầu xử lý |
| --- | --- | --- |
| B01 | `tools/run_all_tests.py:21` liệt kê cứng 19 suites; không có `test_edc_plus_r_live.py` | Discovery đầy đủ, đối chiếu test IDs, không bỏ test chỉ vì tên có `live` |
| B02 | `test_edc_plus_r_live.py:8` import `apply_relations` từ catalog barrel hiện không export symbol; file dùng fake LLM | Sửa supported import/compatibility có chủ đích, xác nhận collection của test lifecycle hiện hữu |
| B03 | `test_standalone_architecture.py:371`, một số tests composition/project/prompt gọi service mặc định | Cô lập data/config/registry/cache trước baseline, không load/sync dự án thật |
| B04 | Projects port `create_snapshot(project,note)->dict`; JSON repo thực nhận keyword `copy_from_disk_if_clean` và trả `Path`; list/restore cũng khác | Chốt contract và adapter mapping; test với JSON repository thật trong thư mục tạm |
| B05 | Bootstrap và facade tự tạo projects service; UI composition lấy cả container và facade | Một runtime owner cho store/service/coordinator/locks trong cùng application instance |
| B06 | `bootstrap.py` đọc storage keys ở top level, trong khi TOML dùng `[storage]`; key vector cũng cần đối chiếu | Config contract test với toàn bộ đường dẫn tùy biến, tránh fallback ghi `data/` thật |
| B07 | Revision state nằm trong cả service và coordinator; facade alias private dictionaries | Một owner state, truy cập qua API rõ ràng; save/commit/restore không tách trạng thái |
| B08 | Coordinator có filesystem stat/unlink và fallback snapshot `/tmp/...` khi store thiếu capability | Filesystem do adapter quản lý; thiếu snapshot phải lỗi rõ ràng, không báo snapshot giả |
| B09 | Query service đọc projection trực tiếp dù save/load có thể đặt `sync_pending` | Xác định read freshness và test stale/pending/resync |
| B10 | Architecture scanner bỏ qua parse errors, chưa resolve relative imports, chưa kiểm đầy đủ `backend/modules`/UI | Architecture test phải fail closed và kiểm cả kiến trúc mới |

Các dòng trên là bằng chứng tĩnh cần xác nhận bằng tests. Lỗi baseline phải được ghi riêng và sửa tối thiểu trước migration; không lấy lỗi hiện hữu làm golden behavior cần bảo toàn. Không tin tuyên bố “141 tests PASS” trong báo cáo lịch sử để bỏ qua B01–B10.

## 3. Kết quả cuối cùng phải đạt

1. Use cases hiện có nằm trong module sở hữu; UI/HTTP/CLI gọi public application API, không tự điều phối ghi dữ liệu hoặc gọi concrete SDK.
2. Một composition root dựng graph dependency. Trong cùng process/application instance, UI, facade tương thích và HTTP dùng cùng projects service, coordinator, lock registry và state cần chia sẻ.
3. Có một implementation chuẩn cho lifecycle commit; không có phiên bản snapshot/revision/idempotency/sync khác nhau tùy caller.
4. Domain thuần không import storage, SDK, frontend, config hoặc filesystem I/O. Các cross-module imports đi qua public contracts; không còn ngoại lệ legacy đã hết lý do.
5. Existing behavior, persistent schema, ID, evidence, prompt provenance, export/train formatting và UI state contracts được bảo toàn, trừ baseline defect đã có test sửa riêng.
6. Implementation cũ hết caller được xóa thực sự; compatibility còn cần thiết được giữ tường minh, có lý do/điều kiện gỡ, không phát triển nghiệp vụ song song.
7. Mọi feature/scenario trong test matrix có kết quả; không có mandatory test bị bỏ sót/import error hoặc skip không giải thích.
8. Tài liệu current-state và graph khớp implementation cuối. Có báo cáo pass/fail/error/skip, hiệu năng, dữ liệu trước/sau và deletion evidence.

Không cam kết “không còn bug” hoặc “100% mọi tổ hợp input”. Nghiệm thu dựa trên inventory tính năng, scenarios và bằng chứng kiểm thử có thể chạy lại.

## 4. Thiết kế đích và hợp đồng chung

```text
backend/
  bootstrap.py                    # App instance/config/dependency wiring duy nhất
  modules/
    projects/                     # Lifecycle, project revision, commit, read freshness
    schema_intelligence/          # Catalogs, proposals, EDC review, retrieval/alignment
    extraction/                   # Documents/chunking, prompt versions, engines, provenance
    curation/                     # Existing review/evidence/entity/relation/type/triplet merge
    graph_qa/                     # Approved graph, retrieval, QA, benchmark, graph export
    training/                     # Existing dataset export/training/evaluation use cases
  integrations/                   # SDK adapters hiện có, được inject qua ports
  repositories/                   # Storage adapters hiện có, được bọc khi cần
  api/                            # Stdlib HTTP inbound mapping
  facade.py                       # Explicit compatibility delegates còn nghĩa vụ hỗ trợ
frontend/
  composition.py                  # Nhận app instance, cấp module APIs cho UI
  state/                          # Navigation, LLM widgets, EDC, curation state
  pages/                          # Năm bước UI hiện có
  components/                     # Render/presenters, không có transaction workflow
shared/                           # Pure common contracts/formatting; I/O legacy có lộ trình gỡ
ml_lab/                           # Trainers/evaluation hiện hữu, chạy qua training boundary
```

Trong mỗi module, tạo `public.py`, `application/`, `domain/`, `ports.py`, `adapters/` khi có implementation thật. Không tạo đủ năm thư mục trống cho đẹp sơ đồ. Tên dưới các thư mục này có thể điều chỉnh; ownership và dependency là bắt buộc.

| Contract | Quyết định bắt buộc |
| --- | --- |
| Nguồn dữ liệu | JSON bundle authoritative; SQLite read projection có thể dựng lại; vector index là dẫn xuất. Không migration schema/nguồn sự thật trong đợt này |
| State/lock | Một runtime state owner; name/slug/project_id của cùng project phải quy về một lock key. Không tuyên bố bảo vệ nhiều process nhờ `RLock` |
| Snapshot | Internal port trả reference/metadata có kiểu rõ; adapter quản lý path/create/list/restore/cleanup. Compatibility mapping giữ return shape/path semantics đang công khai |
| Project revision | Chuyển hàm về projects nhưng giữ chính xác fields/hash semantics; không thay revision chỉ vì move file |
| Catalog change | Schema module tính thay đổi và cung cấp invalidation intent/contract; coordinator không phụ thuộc catalog barrel để hiểu toàn bộ nghiệp vụ |
| Mutations | Preview thuần; apply revalidate scope/revision/hash/stale; domain tạo candidate/result; coordinator commit. Giữ `all_or_nothing`/`valid_only` |
| Read freshness | Sau JSON commit, SQLite lỗi vẫn là commit thành công kèm pending. Resync thất bại phải trả stale/pending rõ ràng; không trả dữ liệu cũ như mới |
| Contracts | Giữ Pydantic v2 và extra policy hiện có; không serialize project qua DTO thiếu fields. `.from_dict/.to_dict` chỉ bỏ sau migration caller có bằng chứng |
| External integration | Giữ provider/mode/prompt/token policies và thuật toán hiện hữu; inject port thay SDK. Không tự nâng dependency/model/prompt |
| Transport | In-process mặc định; giữ stdlib API và supported endpoint contracts. Không xây remote workflow mới; phần remote chưa hỗ trợ trả lỗi rõ, không fallback sang local mutation |
| Compatibility | Facade/client/barrels chỉ explicit forwarding/mapping; không wildcard hoặc dynamic `__getattr__` dispatcher để che dependency |

## 5. Bàn giao artifacts và trạng thái

R00 tạo thư mục evidence theo convention `AI/report/refactor-evidence/<run-id>/` (không chứa secrets/dữ liệu thật), với:

- `baseline.md`: Python/dependency versions, HEAD + dirty/untracked inventory/hash, đường dẫn cấu hình test, lỗi baseline, discovery IDs và invocation.
- `contracts.md`: feature/public API/endpoint/session-key inventory; field/hash/return contracts và những baseline defect được phép sửa.
- `fixtures-manifest.json`: fixture ID, seed, dimensions, checksum và phép chuẩn hóa volatile fields được phép.
- `Rxx-result.md`: status, source input/output mapping, files changed/deleted, targeted/full test commands/results, performance nếu liên quan, remaining gaps.
- `feature-test-matrix.md`: từng scenario → test ID/expected outcome/actual evidence/status.
- `final-acceptance.md`: tổng hợp R00–R13, compatibility còn lại và kiểm tra dữ liệu/graph.

Deletion entries bổ sung vào ledger hiện có, giữ lịch sử. Logs dài có thể để cạnh báo cáo bước; không ghi “PASS” nếu thiếu log/exit status. Trạng thái hợp lệ: `NOT_STARTED`, `IN_PROGRESS`, `PASS`, `PARTIAL`, `BLOCKED`; chỉ `PASS` cho phép bước phụ thuộc hoàn tất.

## 6. Thứ tự thực hiện và mapping với kế hoạch cũ

| Bước | Giao việc | Phụ thuộc | Gate P0–P7 tương ứng |
| --- | --- | --- | --- |
| R00 | Cô lập test, collection, baseline | Không | P0 |
| R01 | Chốt contracts, adapter tests, architecture guard | R00 | P0/P6 |
| R02 | Thống nhất config và runtime wiring | R01 | P2 |
| R03 | Hoàn thiện commit/state/freshness | R02 | P3 |
| R04 | Module schema intelligence | R03 | P2/P5 |
| R05 | Module extraction/documents/prompts | R04 | P2/P5/P6 |
| R06 | Module curation hiện có | R04, R05 | P2/P5 |
| R07 | Module graph QA/export/benchmark | R06 | P2/P5 |
| R08 | Module training/export và ML boundary | R07 | P2/P6 |
| R09 | Tách frontend state/presenters | R04–R08 | P4/P5 |
| R10 | Migrate toàn bộ UI/API/CLI consumers | R09 | P4 |
| R11 | Xóa residue, kết thúc compatibility nội bộ | R10 | P1/P7 |
| R12 | Regression toàn bộ logic và hiệu năng | R11 | P6/P7 |
| R13 | Tài liệu, graph, nghiệm thu cuối | R12 | P7 |

Đây là thứ tự mặc định cho một agent. Có thể phân công preparation/read-only cho R04–R08 song song sau R03, nhưng chỉ tích hợp khi các contracts phụ thuộc sẵn sàng. Không chạy deletion/final acceptance song song với mutation source của agent khác.

## 7. Đặc tả từng bước

### R00 — Cô lập môi trường, thu đủ tests và tạo baseline

**Đầu vào:** AGENTS.md, dirty worktree hiện tại, `pyproject.toml`, tests, `tools/run_all_tests.py`, `tools/benchmark_performance.py`, config và singleton initialization paths.

**Công việc:**

1. Ghi manifest của working tree trước khi sửa; không reset/clean/commit thay người dùng. Chốt interpreter Python >=3.11 của KG Studio; nếu cần dependency, cài đúng metadata hiện tại trong môi trường dự án, không dùng venv MVP làm dependency cố định.
2. Thiết lập temp roots cho projects/SQLite/vector/model registry/training exports/secrets/config; inject adapters và reset singleton/cache giữa tests. `KG_STUDIO_CONFIG`/projects override phải có trước imports đọc global config; chỉ env override chưa đủ nếu bootstrap bỏ qua `[storage]`. Trong test process, thay credentials kế thừa bằng dummy, không log giá trị, restore environment sau test; harness chặn kết nối mạng ngoài, chỉ cho loopback khi test HTTP transport tường minh cần dùng.
3. Thay test đọc dự án thật bằng fixture synthetic/copy scrubbed trong temp; không sửa hoặc sync dự án thật. Kiểm tra runner, AppTest, benchmark và defaults đều nằm trong sandbox test.
4. Thu tất cả `test_*.py`, kiểm tra import/collection. Sửa B02 bằng import từ owner chuẩn hoặc deliberate compatibility export sau audit; không skip file để né lỗi.
5. Runner dùng discovery hoặc so tập IDs với discovery; fail khi thiếu file/import/load errors; tính PASS = run − failure − error − skipped, báo skip riêng. Phân loại offline/live theo hành vi, không theo tên file.
6. Chạy full offline suite và benchmark baseline trong temp. Nếu có lỗi cũ, lưu reproduction nhỏ, phân loại và sửa tối thiểu trước các bước migration. Không đóng gate bằng số test của báo cáo cũ.

**Đầu ra:** môi trường/harness test cô lập, runner đầy đủ, baseline.md, fixture manifest, test IDs, baseline failures/fixes và benchmark artifacts.

**Kiểm chứng:** hash các config/catalog/dữ liệu thật liên quan trước/sau không đổi; offline tests không cần internet/GPU/Neo4j thật; collection có đủ lifecycle EDC+R; runner và discovery không bỏ sót nhau.

**Kết quả cần đạt:** baseline có thể chạy lại, lỗi collection và side effects đã xử lý; mọi test mandatory đã pass hoặc lỗi baseline còn lại được đánh dấu BLOCKED để chưa migrate vùng liên quan. Baseline BLOCKED không là PASS toàn bước. Nếu baseline fail do B04–B09 thuộc R01–R03, cho phép subtask sửa tối thiểu đúng defect/contract ID, có reproduction trước/sau để mở khóa R00; không kéo toàn bộ migration tương lai vào bước baseline.

### R01 — Chốt contracts và bảo vệ ranh giới

**Đầu vào:** R00 artifacts; projects ports/service/coordinator, JSON/SQLite/vector adapters, tests architecture/Pydantic/API, toàn bộ public consumers.

**Công việc:** lập feature/public export/HTTP/session inventory; chốt parameter/result/error/in-place semantics; sửa snapshot port–adapter mismatch bằng explicit mapping. Thêm adapter contract tests dùng JSON repository thật trong temp, rồi chạy cùng contract cho fake; không sửa fake để che khác biệt adapter. Ghi owner của revision/catalog hash/prompt và DTO. Thêm fixtures metadata lạ ở nested project, evidence/observations và Unicode để kiểm tra persistence round-trip.

Architecture scanner phải báo lỗi read/parse, resolve relative imports, scan `backend/modules/**/domain` và `application`, UI concrete storage/SDK, cross-module internals, shared independence và cycle. Dùng allowlist cạnh cụ thể cho legacy, kèm Rxx gỡ; không dùng allowlist cả package hay số dòng.

**Đầu ra:** contracts.md + feature-test matrix khởi tạo; ports/mapping khớp adapter thật; real/fake contract tests; architecture guards và precise allowlist.

**Kiểm chứng:** create/list/restore snapshot bằng adapter thật; default/null/unknown fields không mất trong storage; public response signatures giữ nguyên hoặc có compatibility adapter đã test. Thử một import vi phạm và một parse lỗi trong fixture kiểm tra phải bị phát hiện.

**Kết quả cần đạt:** không còn mâu thuẫn contract ở đường projects/snapshot trước khi migrate callers. Contracts là input bắt buộc cho R02–R10.

### R02 — Một composition root và runtime owner

**Đầu vào:** R01 contracts; `backend/bootstrap.py`, facade constructor/getter, frontend composition, projects service, config loader/TOML và service factories.

**Công việc:** đọc đúng `[storage]` và đúng key names; dựng một app instance chứa adapters và services. Facade compatibility nhận services đã inject thay vì tự dựng store/service thứ hai; UI composition/HTTP nhận cùng instance. Tách runtime state/lock owner với public operations, không alias private dictionaries. Giữ khả năng tạo hai app instances độc lập cho tests; giữ default getter ở composition boundary.

**Đầu ra:** factory/config mapping đúng; facade/UI/HTTP wiring dùng chung instance; identity/config isolation tests.

**Kiểm chứng:** `is` identity của service/coordinator/shared lock qua các entrypoints trong cùng app; same project name/ID cùng lock; app A/B khác store/lock/cache; mọi custom path trỏ vào temp, không có file mới trong production roots. Import package không tự tạo file hoặc gọi mạng.

**Kết quả cần đạt:** composition root là owner dựng runtime/projects/facade dependencies trong phạm vi R02; không có shared state ngầm giữa hai app và không có hai lock registries cho cùng app. Những concrete dependencies còn trong extraction/alignment/QA được migrate ở R04–R08, phải có allowlist tạm; yêu cầu loại hết chúng khỏi core/UI là gate cuối R10, không mở rộng R02 sang mọi module.

### R03 — Một lifecycle commit, revision và read freshness

**Đầu vào:** runtime R02, commit coordinator, project service/facade helper paths, JSON bundle/journal/snapshot, projection và vector adapters.

**Công việc:** thống nhất save/commit/restore paths về một owner state; di chuyển filesystem stat/delete vào adapter ports; bỏ snapshot fallback giả. Giữ các helper compatibility còn caller đến khi migrate xong. Chuyển project revision về pure projects owner, catalog invalidation qua contract thay vì import legacy catalog barrel. Hoàn thiện persisted idempotency/restart replay, durable pending marker và read freshness: đọc phải resync từ authoritative project hoặc trả stale rõ ràng nếu chưa thể sync.

**Đầu ra:** coordinator hoàn chỉnh, projects API, explicit storage/snapshot/projection/invalidation contracts; fault/concurrency/real-adapter integration tests.

**Kiểm chứng bắt buộc:** preview không đổi memory/disk; double-click chỉ commit một lần; cùng ID khác payload bị từ chối; revision stale bị từ chối; snapshot fail/JSON fail không đổi committed state; SQLite fail giữ JSON committed + pending; vector fail không đảo commit nhưng không được báo invalidation thành công hoặc dùng index cũ như còn hợp lệ. Test lần retrieval kế tiếp phải rebuild, bỏ qua index stale hoặc trả lỗi có trạng thái đúng contract; resync/restore nhất quán; save → commit → restore → restart → replay giữ contract; unknown metadata/evidence không mất. Test gọi từ hai references UI/API trong cùng runtime.

**Kết quả cần đạt:** không còn lifecycle copy-paste hoặc snapshot thành công giả; reads không báo fresh khi projection stale. Không mở rộng multi-process concurrency trong đợt này; ghi rõ giới hạn hiện có.

### R04 — Module schema intelligence và catalog/EDC ownership

**Đầu vào:** `backend/domain/catalogs/{core,proposals,review,service}.py`, schema retriever/aligner, catalog helpers, DTOs, facade EDC methods và R03 commit contracts.

**Công việc:** chuyển catalog CRUD/hash, proposal ingestion/impact, EDC preview/apply và retrieval/alignment vào owner chuẩn trong `modules/schema_intelligence`. Domain giữ policy thuần; application inject vector/embedding/LLM ports và gọi commit. Đưa workflow `FrontendClient.decide_single_proposal` (snapshot → quyết định EDC → save) vào schema application use case, giữ response và commit contracts. Revision thuộc projects; prompt ownership chuyển extraction ở R05. `service.py` và `__init__` chỉ explicit compatibility khi còn callers; không expose private cache/helper như public API mới.

**Đầu ra:** public application API + migrated policies/ports/adapters; facade delegates tương ứng; source→target map; legacy import allowlist giảm.

**Kiểm chứng:** empty/upload catalog; validation Unicode; hai kind độc lập; impact/dependency conflicts; approve/merge/reject; `all_or_nothing`/`valid_only`; stale candidates khi đổi catalog/model; refresh chỉ scope chọn; existing auto-align/verifier semantics; preview/apply parity qua application và facade.

**Kết quả cần đạt:** nghiệp vụ schema có một owner, thay vector/provider không sửa domain; không thêm từ điển hoặc kỹ thuật resolution mới.

### R05 — Module documents, extraction và prompt versioning

**Đầu vào:** documents processor, extraction registry/base/engines/validator, prompts service, prepared-request DTO, gateway/token/parsing, facade extraction methods và R04 APIs.

**Công việc:** chuyển orchestration hiện có vào `modules/extraction/application`; tách parsing I/O adapters khỏi chunking/validation thuần; inject LLM/schema retrieval/alignment ports. Giữ engine registry và BaseExtractionEngine behavior; prompt versions thuộc extraction, serving/training formatting dùng chung ở shared. Định nghĩa rõ mutation dưới khóa, kết quả worker, progress/error/partial-save; không giữ khóa trong request mạng nếu không cần theo consistency contract đã chốt.

**Đầu ra:** documents/extraction/prompt public APIs, injected engines/adapters, explicit run/provenance lifecycle; facade forwarding; parser và lifecycle tests.

**Kiểm chứng:** TXT/PDF/DOCX hợp lệ/lỗi; chunk overlap/page/offset/hash; ba modes `closed`, `edc`, `edc_plus_r`; nhiều refinement loops với fake provider; malformed/truncated JSON, timeout/auth/rate-limit branches; token limits; prompt immutable versions/project-mode isolation; preview-execution parity; parallel success/partial/error; evidence source và run history bảo toàn.

**Kết quả cần đạt:** engine chạy được không cần UI/server/provider thật; không đổi prompt/threshold/model/thuật toán kết quả trong move-only refactor.

### R06 — Module curation, evidence và merge hiện có

**Đầu vào:** curation service/common/evidence/validation/review/entities/merge/relation_merge/semantic_clustering/merge_core, DTOs, facade mutation methods, R03/R04/R05 contracts.

**Công việc:** chuyển existing review/edit/merge workflows vào curation application; policies và merge primitives thuần vào domain; semantic clustering hiện có gọi LLM qua port. Bảo toàn duplicate suggestions/blacklist/scoring hiện hữu. Các workflow curation dùng coordinator, không thêm write workflow thứ hai; quyết định proposal EDC vẫn thuộc schema application R04, curation chỉ dùng public API khi cần.

**Đầu ra:** curation public APIs cho preview/apply/edit/evidence/merge/dismiss; policies một implementation; compatibility mapping và deletion entries.

**Kiểm chứng:** evidence exact/span/page; edit làm invalidation đúng; approve/reject/check và schema blocking; entity/relation/entity-type merge, bulk và triplet collapse; aliases/observations/evidences/redirects/doc links/history lossless; cycle/self-loop policies; dismiss được tôn trọng; request/revision/idempotency/error contracts.

**Kết quả cần đạt:** mọi mutation curation đi qua use case/coordinator; không bổ sung entity resolution mới hoặc thay độ chính xác thuật toán hiện hữu.

### R07 — Module graph QA, export và benchmark

**Đầu vào:** graph service/g_retriever/qa_generator, current export/QA UI consumers, index caches, fake LLM, deterministic graph fixtures.

**Công việc:** tách index/cache, scoring/PCST/PPR/Top-K, textualization/question rules thành units có owner; application điều phối QA/paraphrase/evaluation/export; filesystem/archive/Neo4j/LLM qua adapters. Giữ output schema và tie/order semantics; chuyển consumers khỏi re-export QA qua g_retriever khi sẵn sàng.

**Đầu ra:** graph_qa public APIs và policies; tested export/Neo4j adapter; facade compatibility; fixture before/after comparison artifacts.

**Kiểm chứng:** approved-only graph; unresolved schema/evidence constraints; ba retrieval modes và empty/disconnected graph; ranking/ties/path/evidence/citations; deterministic QA/benchmark datasets với seed; JSON/CSV/ZIP round-trip; Neo4j fake-driver parameterization/idempotent project-scoped write/delete/error transaction.

**Kết quả cần đạt:** không sửa thuật toán hoặc claim retrieval tốt hơn vì refactor. Scores có tolerance được chốt trước nếu cần; không nới tolerance sau khi test fail để che thay đổi.

### R08 — Module training/export và ML boundary

**Đầu vào:** dataset exporter, `ml_lab/trainers/*`, evaluation, model registry/embedder integration, shared formatting, ML UI, R05/R07 contracts.

**Công việc:** tạo training application APIs cho những thao tác đã có; UI không import trainers trực tiếp. Chốt thư viện dùng chung cho registry metadata/formatting mà serving và trainers cùng dùng, không phụ thuộc facade/UI. Giữ lazy heavy imports; temp artifact paths được inject.

**Đầu ra:** training public API/adapters, existing trainer/CLI delegates, train/serve contract tests và dataset fixtures.

**Kiểm chứng:** SR triplets/canonicalization/SFT schema; human-vs-auto decision filtering; rejection filtering; format/tokenization parity; tiny offline trainer/evaluation, metadata/fingerprint; LoRA bundle generation trong temp. Không yêu cầu train GPU thật để xác minh orchestration; phân biệt phần chưa chạy do optional dependency.

**Kết quả cần đạt:** mọi existing ML action có boundary dùng chung cho UI/CLI; không nâng model, thêm dictionary management hoặc thay nội dung dữ liệu huấn luyện.

### R09 — Tách frontend state và presenters

**Đầu vào:** session/selection_core, curation/EDC tables/actions, evidence panel, merge/export components, five-page navigation; R04–R08 APIs.

**Công việc:** chia state theo navigation/project, LLM widgets, EDC drafts/selection, curation và graph/QA. Giữ session keys/callback signatures qua explicit forwarding trong transition. Reuse selection dispatcher/callback factory đã có, không giao tạo lại. Tách filter/sort/row/pagination thuần khỏi render; component nhận application API từ composition, không tạo store/service.

**Đầu ra:** state/presenter modules, UI dependency injection, interaction tests, compatibility mapping và updated caller inventory.

**Kiểm chứng:** selection theo ID qua sort/page/filter; scope hai bảng EDC; project reset; draft edit/preview invalidation; fill Top-1 chỉ khi candidate hợp lệ; pending-only actions; return context schema→edge/entity; widget state sau rerun; secrets không xuất hiện trên trace/export.

**Kết quả cần đạt:** UI giữ hành vi/năm bước hiện tại; không thay bảng sang thư viện/UI model khác để giảm LOC trong cùng đợt.

### R10 — Migrate tất cả UI/API/CLI consumers về public use cases

**Đầu vào:** module public APIs, UI composition/state R09, facade/client, stdlib handler/server, app/run entrypoints, inventory R01.

**Công việc:** chuyển từng consumer, gồm settings/model-list/test-connection và ML actions; HTTP chỉ mapping request/status/response. Giữ endpoint và URL/project-scope semantics; loại workflow nghiệp vụ khỏi client và SDK imports khỏi UI. Default app lấy cùng runtime R02; tests tiếp tục inject app riêng. Không xây HTTP capability mới chỉ để đạt symmetry.

**Đầu ra:** UI/API/CLI public-boundary callers; facade/client chỉ explicit compatibility contracts còn cần; endpoint parity tests và UI smoke script/checklist.

**Kiểm chứng:** mọi endpoint inventory có success/error/scope/unknown-project cases, invalid requests không mutate; loopback HTTP test malformed JSON/encoded URL/response status theo contract. Cùng fixture qua application/facade/handler cho equivalent results; remote error không ghi local. Smoke cả năm màn hình trên temp project và đầy đủ flow ở mục 9.

**Kết quả cần đạt:** không còn transaction sequence trong frontend hoặc concrete repository/SDK calls trong transport. Các fallback không đáp ứng contract phải được sửa tường minh như baseline defect, không âm thầm mất tính năng.

### R11 — Xóa code không còn dùng và thu hẹp compatibility

**Đầu vào:** caller/export/CLI/registry inventory sau R10, source→target map, architecture allowlist, ledger hiện có và logs parity.

**Công việc:** audit theo symbol/branch/import/dependency. Ưu tiên private lock/state/helper trùng đã hết caller, old implementations đã migrate, forwarding/barrels chỉ còn nội bộ. Với mỗi entry, xác định owner, static/dynamic/public consumers, replacement, tests, compatibility condition rồi mới xóa. Review các tests bám private cache identity: chuyển sang kiểm hành vi invalidation/selection thật, giữ regression intent.

**Đầu ra:** source thực sự thu gọn, imports/exports/callers nhất quán, ledger có evidence và compatibility-retained list rõ ràng; không tạo generic/dynamic dispatcher mới để giấu wrappers.

**Kiểm chứng:** không còn imports về code bị xóa; import tất cả package/CLI/test modules; discovery không giảm scenarios do deletion; unit/integration/full offline suite pass; architecture không còn legacy edges đã migrate.

**Kết quả cần đạt:** zero dead implementation đã được chứng minh trong phạm vi audit. Symbol chưa đủ bằng chứng phải giữ có lý do, không đoán “không có public consumer ngoài”. Không xóa data/snapshots/history/models/training exports/graph hoặc behavior hiện có vì ngoài phạm vi thêm tính năng.

### R12 — Regression toàn bộ logic, integration và hiệu năng

**Đầu vào:** source sau R11, complete feature-test matrix, fixtures/baseline R00, defects contract R01, per-step evidence.

**Công việc:** chạy test matrix mục 8, end-to-end mục 9, full discovery và consolidated runner; đối chiếu IDs/count. Thêm tests còn thiếu cho existing feature, không thêm feature mới. So fixture trước/sau và benchmark cùng input/seed/environment. Review diffs không được chạm artifacts thật.

**Đầu ra:** logs và actual test report; mỗi scenario có PASS/FAIL/SKIP kèm lý do; benchmark before/after; data equivalence report; remaining issues.

**Kiểm chứng:** mandatory offline 0 failure/error/missing/unexplained skip; persisted fields/history/evidence/provenance không mất; all supported integration branches được fake/contract-test. Real integration không cấu hình phải ghi NOT_RUN riêng, không báo đã test server/provider thật.

**Kết quả cần đạt:** regression suite chứng minh behavior contracts; p95/peak memory tăng >10% phải đo lại và giải thích/khắc phục trước nghiệm thu, không làm nhẹ workload hay bỏ asserts để đạt số.

### R13 — Đồng bộ tài liệu, graph và nghiệm thu cuối

**Đầu vào:** R12 PASS và tất cả Rxx-result, current source/caller map, README/structure/AGENTS/ledger và graph tools.

**Công việc:** cập nhật current-state docs đúng source: module ownership, bootstrap, snapshot API, execution model, runtime commands, test inventory. Bỏ mô tả về files đã xóa trong README; giữ reports lịch sử và ghi thời điểm áp dụng. Liên kết plan/result mới vào kế hoạch cũ; chỉ sửa AGENTS khi đường dẫn/quy tắc đã thực sự đổi. Chạy `graphify update .`, inspect report/import boundaries/source-map và ghi bằng chứng.

**Đầu ra:** final-acceptance.md, docs/graph đúng implementation, list compatibility/limitations, working-tree diff summary có phân biệt pre-existing changes với changes của đợt này.

**Kiểm chứng:** markdown links/commands hợp lệ, graph build thành công từ snapshot cuối, không còn claim test/feature chưa chạy; final checklist mục 12 hoàn tất. Nếu source bị sửa trong bước này, chạy lại tests tương ứng và full offline gate; docs-only không bắt chạy lại suite đã pass cùng source.

**Kết quả cần đạt:** agent khác đọc docs và report có thể chạy lại verification, biết rõ module owner và những integration chưa được chạy thật. Graph CLI bị chặn phải ghi PARTIAL/BLOCKED, không tự sửa JSON hoặc tuyên bố gate graph đã pass.

## 8. Ma trận kiểm thử tất cả nhóm tính năng hiện có

Tên test dưới đây là entrypoints đã tồn tại hoặc **tests cần bổ sung**, không phải tuyên bố đã bao phủ đầy đủ. R00 ghi test IDs thực tế; R01 thêm row nếu tìm thấy feature chưa có trong bảng.

| Nhóm | Tests hiện có để giữ/migrate | Scenarios tối thiểu và expected results |
| --- | --- | --- |
| Project/config/storage | `test_projects_module`, `test_performance_optimizations`, `test_standalone_architecture` | List/create/load/save; custom paths; UTF-8; bundle/journal recovery; manifest/header parity; unknown nested metadata giữ nguyên |
| Snapshot/restore | Projects/coordinator/curation/performance tests + real-adapter contract bổ sung | Create/list/restore khớp signatures/results; thất bại không snapshot giả; restore đúng project; cache/revision/projection được cập nhật |
| Commit/concurrency | `test_commit_coordinator`, `test_edc_bulk_review`, `test_curation_merge` | Same runtime locks; stale conflict; replay/restart; same ID different payload rejected; JSON/snapshot/projection/vector fault branches |
| Catalogs/prompts | `test_prompt_versions`, `test_edc_bulk_review`, `test_code_cleanup` | Empty/upload catalog, validation; project-mode isolation; immutable versions; restore-as-new; hashes/request preview parity |
| Documents/chunks | Existing standalone/layout tests + parser fixtures bổ sung | TXT/PDF/DOCX, empty/corrupt input; boundaries/overlap/page/offset/chunk hash; stable duplicate-document behavior |
| LLM adapters | `test_llm_package` + branch cases cần thiết | OpenAI-compatible/Anthropic/provider settings; auth/timeout/rate/token/format errors; JSON truncation/schema fallback/token limits theo behavior hiện tại |
| Extraction 3 modes | `test_parallel_extraction`, `test_standalone_architecture`, `test_edc_plus_r_live` dùng fake | Closed/EDC/EDC+R lifecycle, loops, prompt pinning, input/output/run provenance; success/partial/error; không gọi network thật |
| Schema retrieval/alignment | Standalone/EDC lifecycle/performance tests | Top-K/ranking; thresholds giữ nguyên; model/catalog stale; scoped refresh; verifier accept/reject/error; index fingerprint/invalidation |
| EDC batch review | `test_edc_bulk_review` | Hai kinds độc lập; preview không mutate; all-or-nothing/valid-only; conflict/invalid/stale/scope/request/revision scenarios |
| Curation/evidence | `test_curation_merge`, `test_curation_hub` | Approve/reject/check; schema block; edit invalidation; quote/span/page evidence; batch results và audit history |
| Existing merge/dedup/clustering | `test_curation_merge`, `test_relation_cleaning`, `test_semantic_clustering` | Entity/relation/type/bulk/triplet; redirects/cycle/self-loop; blacklist; alias/observation/evidence lossless; existing scores không đổi |
| Graph retrieval/QA | `test_g_retriever`, standalone tests | PCST/PPR/Top-K; empty/disconnected; ties/order; subgraph/path/evidence; fake answer/error/fallback; benchmark metric parity |
| Graph export/import | Existing graph/standalone tests + format fixtures | Approved-only policy; JSON/CSV/ZIP schema/round-trip; unresolved proposals không lọt approved graph; filenames/encodings giữ contract |
| Neo4j | Fake-driver contract tests cần bổ sung | Project-scoped parameterized writes/deletes, repeat sync idempotent, orphan/stale edge handling, transaction failure rollback/reporting |
| ML/export/registry | Standalone/cleanup tests + tiny fixtures | Human-approved/rejection filtering; SR/canon/SFT schema; formatting train/serve parity; tiny trainer/eval metadata; LoRA bundle; registry reload/fingerprint |
| UI/session | `test_layout_pipeline`, `test_curation_hub`, EDC/curation state tests, AppTest | Five-page routing, readiness, selection-ID/sort/filter/page, drafts/preview reset, project switch, return context, widget changes/rerun |
| Secrets/settings | `test_secrets_manager`, standalone TOML tests | Key precedence/save/delete/scrub; provider switching; no real config writes; no secrets in snapshots/trace/export |
| HTTP/CLI/composition | `test_api_v1_and_composition`, `test_projects_module`, new transport smoke | All supported route statuses/errors/scope, URL encoding, invalid JSON contract, no local mutation on HTTP errors; identical app dependencies; entrypoint import/help |
| Pydantic/contracts | `test_pydantic_contracts` + persistent round-trip tests | Defaults/null/enums/unknown request fields đúng contract; unknown persistent project fields không bị bỏ; `.from_dict/.to_dict` compatibility |
| Architecture/import | `test_architecture_boundaries`, standalone legacy checks | Parse/import errors không bị nuốt; relative imports resolved; module/public/SDK/UI/shared rules; no cycles; deleted modules không còn consumers |

Yêu cầu chung: test negative/error branches thực sự; unit fake phải đi cùng integration với adapter lưu trữ thật trong temp. Không coi test “service không phải None” là bằng chứng wiring, hoặc “DTO không crash” là bằng chứng persistence lossless.

## 9. Kịch bản end-to-end cần đạt

Thực hiện trên hai temp projects A/B, fixed clock/ID/seed khi cần. Dùng fixture TXT/PDF/DOCX và fake LLM đã chốt payload; đối chiếu backend artifacts cùng trạng thái UI/API.

1. Tạo A/B → upload tài liệu → cấu hình catalog/prompt → kiểm tra không lẫn config/selection giữa projects.
2. Chạy riêng closed, EDC và EDC+R → xem traces/token/provenance → lưu/reload → payload và evidence offsets đúng fixture.
3. Schema proposals → preview → approve/merge/reject → all-or-nothing/valid-only → quay về cạnh bị block → chỉ mở khóa theo policy.
4. Review/edit cạnh và entity → existing duplicate suggestions → entity/relation/type merge → triplet collapse → không mất evidence/observations/history/redirects.
5. Export approved JSON/CSV/ZIP → import fixture export → QA cả ba retrieval modes → benchmark/dataset export → tiny training/eval/LoRA bundle theo capability đã có.
6. Inject snapshot/JSON/SQLite/vector failures → kiểm tra memory/disk/result → retry/replay → resync/restore → state/projection nhất quán; không ghi sang B.
7. Cùng thao tác qua application và supported HTTP endpoint → giữ result/error contracts; malformed request/scope sai không mutation. UI HTTP error không chạy write local.
8. Streamlit rerun, filter/page/sort, sửa draft và đổi project → selection/preview/reset/return context đúng; refresh không tự commit.

Chạy smoke Neo4j/LLM thật chỉ khi được cấu hình và opt-in; dùng database/project sandbox. Phần đó là verification integration riêng, không là lý do skip logic tests bằng fake.

## 10. Lệnh chạy và cách ghi kết quả

Chỉ chạy sau khi R00 bảo đảm isolation. Ví dụ với venv KG Studio; đổi interpreter theo baseline thực tế, không đoán executable:

```powershell
& '.\.venv-win\Scripts\python.exe' --version
& '.\.venv-win\Scripts\python.exe' -m unittest discover -s tests -p 'test_*.py' -t . -v
& '.\.venv-win\Scripts\python.exe' tools/run_all_tests.py
& '.\.venv-win\Scripts\python.exe' -m unittest -v tests.test_commit_coordinator tests.test_projects_module
& '.\.venv-win\Scripts\python.exe' tools/benchmark_performance.py --help
graphify update .
```

`run_all_tests.py` phải được sửa ở R00 trước khi dùng làm gate. `--help` không tạo benchmark evidence; chạy benchmark theo flags thực tế đã kiểm tra, trên temp data và ghi invocation/result. Không tự đặt environment flags/CLI options chưa được harness hỗ trợ.

Mỗi lần chạy ghi: invocation, interpreter/dependency versions, input fingerprint, fixture/seed, discovered IDs, run/pass/failure/error/skipped/load-error counts, exit code, runtime và logs. Tính theo kết quả **top-level test case loại trừ nhau**, không lấy thẳng `len(result.failures/errors)` vì một case có thể có nhiều subtests lỗi. Tổng kiểm tra: `run = pass + failed_cases + error_cases + skipped + expected_failures + unexpected_successes`; nếu một case vừa failure vừa error, dùng error để phân loại case và báo đầy đủ events riêng. Báo riêng collection errors/subtest failures; expected failure hoặc unexpected success nếu có phải ghi đúng trạng thái và đánh giá gate, không cộng vào PASS hoặc âm thầm thêm để né lỗi. Không chấp nhận giảm test count do bỏ discovery/feature mà không có mapping.

## 11. Xóa mã, rollback và xử lý vướng mắc

### Điều kiện để xóa một dòng/khối/symbol/module

- Đã có implementation chuẩn thay thế hoặc đã chứng minh không còn behavior cần hỗ trợ.
- Kiểm static callers và import bindings; kiểm `__all__`, relative/dynamic imports, engine registries, CLI/config, side effects, public imports và test seams.
- Đã chuyển callers/tests/docs; test giữ nguyên regression intent. Public compatibility còn nghĩa vụ phải retained, ghi owner/điều kiện gỡ; không tự suy đoán không có consumers ngoài repo.
- Có ledger entry: `path/symbol | fingerprint | callers/dynamic/public audit | replacement | proof commands | tests/results | decision | Rxx`.
- Sau xóa phải import/discover và chạy feature parity + full offline gate; không xóa test làm fail mà chưa chuyển hành vi bảo vệ sang boundary mới.

### Rollback

Giữ checkpoint/diff cho từng bước, không xóa dirty changes đã có. Nếu gate fail, chỉ đảo edits của bước đó bằng patch/checkpoint rõ ràng; không `git reset --hard`, `git clean` hoặc checkout toàn repo. Chỉ restore temp fixture/snapshot trong tests; dữ liệu thật không thuộc phạm vi thử nghiệm.

Nếu thiếu runtime/CLI/credentials: tiếp tục phần độc lập có thể kiểm chứng, ghi chính xác bước bị chặn; không báo PASS. Nếu snapshot/schema/public contract cần thay behavior ngoài kế hoạch, mô tả bằng reproduction + phương án cụ thể rồi xin quyết định khi chưa có authority. Không tự chuyển sang microservices/framework/storage khác để gỡ vướng.

## 12. Mẫu lệnh giao việc và checklist nghiệm thu

Copy mẫu sau khi giao cho agent khác:

```text
Thực hiện bước Rxx của AI/report/modular-monolith-refactor-agent-handoff-plan.md.
Đọc AGENTS.md; chạy graphify query trước search/source read, scoped fallback nếu CLI lỗi.
Input snapshot: <HEAD + worktree fingerprint>; dependency reports: <Rxx-result paths>.
Phạm vi sửa: <files/module>; public contracts giữ nguyên: <contract IDs>.
Không thêm entity resolution hoặc từ điển ngữ nghĩa mới; bảo toàn behavior hiện hữu.
Không sửa dữ liệu/config thật hoặc dirty changes ngoài phạm vi.
Đầu ra: source/tests/caller migration/deletion proof + Rxx-result.md + matrix updates.
Chạy targeted tests và full isolated offline gate; ghi actual results và remaining gaps.
Không đánh PASS nếu chỉ tạo interface, di chuyển folder, sửa fake cho qua hoặc thiếu tests.
```

Owner nghiệm thu R13 xác nhận:

- [ ] R00–R13 đều có input fingerprint, output và gate evidence; không báo hoàn thành dựa trên tài liệu cũ.
- [ ] Đã xử lý B01–B10 bằng tests chạy thực tế, gồm snapshot adapter thật và same-instance wiring.
- [ ] Tất cả capability/use case hiện có có public owner, consumers đã migrate; không còn nghiệp vụ trong UI/transport hoặc god facade mới.
- [ ] Commit/revision/idempotency/snapshot/freshness chỉ có một lifecycle chuẩn và có fault/restart/concurrency evidence.
- [ ] Không thêm ER/dictionary features; giữ matcher/merge/synonym behavior hiện hữu và các thuật toán/prompt/threshold đã chốt.
- [ ] Các implementations hết dùng đã xóa với ledger; compatibility còn lại explicit, không có private dependency ngầm hoặc allowlist quá hạn.
- [ ] Full discovery/runner không bỏ suites; toàn bộ mandatory offline scenarios PASS; live/optional NOT_RUN được báo riêng, không tính PASS.
- [ ] UI năm bước, supported HTTP/CLI, storage round-trip, ML/export và performance checks có kết quả.
- [ ] Không mất evidence/observations/metadata/provenance và không thay file dữ liệu/config/secrets thật.
- [ ] README/structure/commands/test inventory đúng source; graph được cập nhật bằng công cụ; diff cuối phân biệt rõ edits của đợt này.

Chỉ khi các mục bắt buộc có bằng chứng mới tuyên bố hoàn tất refactor. Việc viết kế hoạch này không tự đánh dấu bất kỳ bước nào đã PASS.
