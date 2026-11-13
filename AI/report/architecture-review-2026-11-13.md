# Phản biện kiến trúc hiện tại KG Studio

Ngày: 2026-11-13. Đối tượng: working tree hiện tại trên HEAD `c92a6d6`, bao gồm thay đổi tracked và untracked. Đây là báo cáo đánh giá, không phải chứng nhận production hay báo cáo đã sửa lỗi.

## 1. Kết luận phản biện

**Hướng Modular Monolith theo nghiệp vụ, với Ports & Adapters có chọn lọc phù hợp dự án Python nghiên cứu KG này. Nền tảng đã có implementation và kiểm thử đáng kể, nhưng việc thực thi ranh giới và tính thống nhất của đường ghi chưa hoàn tất.**

Có thể bảo vệ lựa chọn kiến trúc cho công cụ nghiên cứu chạy local/in-process. Chưa nên bảo vệ các khẳng định “mọi ghi đều qua coordinator”, “chỉ một nơi dựng adapters”, “domain thuần hoàn toàn”, “HTTP tương đương local”, “an toàn đa tiến trình” hoặc “production-ready”. Những khẳng định đó vượt quá bằng chứng hiện tại.

Không cần rewrite hoặc chuyển microservices. Cần sửa các lỗ hổng ở commit/locking, projection freshness và architecture guard trước khi mở rộng số use case. Không chấm điểm tổng hợp tùy ý vì chưa có rubric trọng số và kiểm thử tải đại diện.

## 2. Phương pháp và phạm vi xác minh

- Đọc `AI/structure.md`, hướng dẫn AGENTS người dùng cung cấp, composition root, facade, frontend composition/client, application services trọng yếu, coordinator, ports/public API và architecture tests.
- Đọc code theo đường dẫn được tài liệu/graph hoặc lần đọc trước định vị. `graphify query "architecture module boundaries composition root commit coordinator facade tests violations"` thất bại do CLI không có trong PATH. Dùng `graphify-out/graph.json` có phạm vi để định vị và kiểm chứng source; không dùng đồ thị làm bằng chứng thay cho implementation.
- Working tree có thay đổi UI, domain, repository và tests chưa commit; không reset, không sửa chúng. Kết luận chỉ áp dụng cho trạng thái được đọc/chạy ở lượt đánh giá này, không đồng nhất với HEAD sạch.
- Chạy `& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py`. Lần đầu sandbox không mở được Python base; chạy lại với quyền thực thi được phê duyệt thành công. Interpreter Python **3.13.2**.
- Runner sao chép source sang workspace tạm, dùng dữ liệu tổng hợp, chặn external network và ghi ngoài workspace. Không gọi live LLM/Neo4j hoặc sửa project thật.
- Chưa thực hiện stress test, fault injection bổ sung, kiểm thử đa tiến trình, kiểm tra browser/accessibility hay thực nghiệm chất lượng KG trên corpus lịch sử.

## 3. Những yếu tố đạt

| Yếu tố | Bằng chứng | Ý nghĩa và giới hạn |
| --- | --- | --- |
| Phân chia theo năng lực nghiệp vụ | `backend/bootstrap.py:60` dựng projects, schema intelligence, extraction, curation, graph QA, training | Có ownership thực tế, phù hợp mở rộng trong một ứng dụng; chưa đồng nghĩa mọi boundary đã kín |
| Có composition root và dependency injection | `AppContainer`, constructor services; graph QA nhận baseline source qua port | Có test seam và đường inject; vẫn còn fallback tự dựng adapter ngoài root |
| Có public APIs/ports | `backend/modules/projects/public.py`, `ports.py`; baseline run source port | Hướng phụ thuộc đúng đã hình thành, có thể migrate dần thay vì rewrite |
| Có lifecycle commit trung tâm | `ProjectCommitCoordinator.commit`, tests commit coordinator | Có revision, request hash/idempotency, snapshot, cập nhật memory sau save, báo lỗi projection; còn đường ghi bypass |
| Phân biệt authoritative và derived data | JSON store, SQLite projection, vector index; baseline snapshot dẫn xuất | Hợp lý cho ứng dụng local và nghiên cứu; phải cưỡng chế freshness của projection |
| Tách baseline khỏi chuẩn hóa ngữ nghĩa | Graph QA build qua source port, snapshot theo nguồn tường minh | Cùng thuật toán đọc được nhiều nguồn mà không biến baseline thành dữ liệu đã duyệt; tests baseline graph đều đạt trong lượt này |
| Có kiểm chứng kiến trúc và hành vi | 4 architecture boundary tests và 6 coordinator tests đạt | Bằng chứng tốt hơn việc chỉ trình bày sơ đồ; phạm vi guard còn hẹp |
| Có kiểm thử hợp đồng dữ liệu và cache | Suite gồm roundtrip, invalid graph, source isolation, cache fingerprint, revision/replay | Có ý thức bảo toàn dữ liệu; số test không thay thế coverage theo yêu cầu |

Kết luận “đạt” ở đây là đạt một năng lực cụ thể trong phạm vi được kiểm chứng, không phải mọi nhánh của capability đều đúng.

## 4. Những yếu tố chưa đạt và cần cải tiến

### F1 — Đường ghi chưa thống nhất; phạm vi khóa chưa thống nhất [ưu tiên cao]

**Bằng chứng xác nhận:**

- `backend/modules/extraction/application/service.py:68`: `get_project_lock()` chỉ ủy quyền khi coordinator có public `get_project_lock`. Coordinator hiện có `_get_lock`/`_get_internal_lock`, không có public method đó; extraction đi vào `_project_locks` riêng.
- Cùng file dòng 76: `_save_project_safe()` truy cập `commit_coordinator.project_store.save_project()` trực tiếp. `extract_chunks_parallel` dùng đường này cho các engine không phải baseline.
- `backend/modules/projects/application/service.py:64`: `save_project()` tự lưu/sync/invalidate, không gọi `commit()`.
- `backend/modules/curation/application/service.py:94` trở đi: khi không inject coordinator, fallback mutate project rồi có thể save trực tiếp. Schema application cũng có fallback cập nhật memory khi coordinator vắng mặt.
- `restore_snapshot()` khóa theo tên dự án trong khi các đường khác thường khóa theo project ID; đây là thêm một điểm cần thống nhất identity khóa.

**Tác động:** bảo đảm coordinator không bao phủ mọi mutation; khóa extraction và curation có thể không loại trừ nhau. Có nguy cơ overwrite hoặc sai đồng bộ khi cùng project được cập nhật qua nhiều đường. Chưa tái hiện một ca mất dữ liệu thực tế trong lượt này; đây là mismatch xác nhận ở code và rủi ro concurrency có cơ sở.

**Cải tiến:** có một contract lock/commit công khai, cùng project identity; inject vào extraction/curation. Migrate các command ghi vào lifecycle chuẩn. API dành cho pure preview/test phải tách rõ, không cho mutation có persistence chạy khi thiếu coordinator.

**Nghiệm thu:** test extraction và curation đồng thời trên cùng ID bằng barrier; test hai object cùng project; stale revision bị từ chối; lỗi save không đổi memory; replay không ghi lần hai; audit không còn đường bypass của mutation đã migrate. Không giữ lock trong toàn thời gian chờ LLM nếu có thể tính candidate ngoài lock rồi kiểm tra lại khi commit.

### F2 — Projection có thể được đọc mà không kiểm tra độ mới [ưu tiên cao]

**Bằng chứng:** `ProjectsApplicationService.query_edges_page/query_nodes_page/query_proposals_page` tại dòng 150 trở đi chỉ lấy ID rồi gọi projection, không kiểm tra `sync_pending` hoặc revision tương ứng. Có API nhận chỉ ID nên trạng thái lỗi trên object project không đủ bảo vệ caller. SQLite query implementations được tìm thấy không có kiểm tra `sync_pending`.

**Tác động:** đường commit đã báo sync lỗi, nhưng đọc sau đó có thể vẫn trả dữ liệu cũ mà application boundary không thể hiện. UI có kiểm tra riêng ở đâu đó cũng không thay thế contract cho mọi consumer.

**Cải tiến:** lưu/đối chiếu revision projection; quy định resync, đọc authoritative hoặc trả trạng thái stale rõ. Không trả thành công như dữ liệu mới khi chưa bảo đảm freshness.

**Nghiệm thu:** ép sync lỗi → gọi các query bằng object và ID → không nhận dữ liệu stale như kết quả mới; resync phục hồi; không mất JSON đã commit.

### F3 — Vi phạm public module boundary [ưu tiên cao, sửa nhỏ nhưng cần guard]

**Bằng chứng:** `backend/modules/schema_intelligence/application/service.py:33` import thẳng `backend.modules.projects.application.commit_coordinator`, trong khi `projects/public.py` đã export coordinator. `frontend/composition.py` cũng import trực tiếp application implementations của 6 modules.

**Tác động:** bên tiêu thụ gắn vào cấu trúc nội bộ; tách/đổi implementation có thể kéo sửa xuyên module. Đây là vi phạm cụ thể với quy tắc public APIs, không chỉ vấn đề thẩm mỹ.

**Cải tiến:** dùng public contracts; chỉ composition root có quyền wiring implementation khi cần và quy định rõ phạm vi đó. Thêm AST guard cho cross-module private imports và UI imports.

**Nghiệm thu:** fixture import sai phải làm guard fail, relative import cũng bị phát hiện; không nới allowlist cả package để suite xanh.

### F4 — Dependency inversion và domain purity mới đạt một phần [ưu tiên trung bình]

**Bằng chứng:**

- `GraphQAApplicationService.__init__` nhận concrete `Neo4jGateway` và fallback `Neo4jGateway()`.
- Schema application tự tạo `SchemaRetriever`, `TargetAligner`, gọi `default_embedder`.
- Facade constructor nhánh compatibility tự dựng repositories/services khi truyền một phần adapters; mặc định bình thường vẫn đi qua AppContainer.
- Architecture guard cho phép 13 cạnh domain → infrastructure với lý do/gate P2/P5, gồm engines, retriever, aligner, graph QA. Đây là nợ migration đã được ghi, không nên báo thành vi phạm mới ngoài allowlist.

**Cải tiến:** inject ports/factories từ root cho phần đang migrate; không tạo Protocol cho mọi helper thuần. Thu nhỏ nhánh dựng dependencies của facade sau khi migrate consumers/test seams. Mỗi allowlist cần điều kiện và bằng chứng để gỡ.

**Nghiệm thu:** test bằng fake adapter không tạo provider/repo thật; import domain không gây I/O; rút đúng cạnh legacy đã migrate.

### F5 — Architecture tests chưa bảo vệ toàn bộ kiến trúc được công bố [ưu tiên cao]

**Bằng chứng:** `tests/test_architecture_boundaries.py` có 4 kiểm tra: shared import, backend/shared → frontend, domain → infrastructure ngoài allowlist, import LLM. Chưa kiểm tra private import giữa modules, application tự tạo adapters, mọi write qua coordinator, hoặc chu trình toàn bộ module graph.

**Tác động:** suite architecture xanh nhưng F1/F3/F4 vẫn tồn tại. Không được dùng “architecture checks PASS” làm chứng minh tuân thủ mọi bất biến.

**Cải tiến:** thêm guard theo invariant thực sự quan trọng, kèm tests cho chính guard; test hành vi cho commit/locks thay vì chỉ kiểm tra chuỗi source. Động imports/call graph cần audit riêng. Chưa chạy SCC toàn codebase nên không kết luận có hay không có import cycle toàn cục.

### F6 — Transport remote chưa có contract đồng nhất [ưu tiên trung bình]

**Bằng chứng:** `frontend/client.py:35` gọi HTTP cho embedding models rồi fallback local khi lỗi; `refresh_proposal_candidates`, `apply_proposal_decisions` và một số phương thức tiếp theo gọi facade trực tiếp kể cả khi `api_base_url` đã được đặt.

**Phân biệt:** fallback thấy ở `get_embedding_models` là đọc, không phải bằng chứng HTTP mutation thất bại rồi ghi local. Tuy nhiên client đang trộn đường HTTP/local theo phương thức, chưa đủ để quảng bá “remote mode” thống nhất.

**Cải tiến:** chọn transport tường minh cho mỗi client, capability matrix local/remote. Remote chưa hỗ trợ command phải từ chối rõ; không thực hiện local mutation bất ngờ.

**Nghiệm thu:** khi remote được chọn, fake local mutation adapter không được gọi; HTTP error không ghi local; unsupported trả lỗi có chủ đích.

### F7 — Contract coordinator còn phụ thuộc quy ước caller [ưu tiên trung bình]

**Bằng chứng:** docstring coordinator nói executor chạy trên bản sao, nhưng `commit()` gọi `executor(project)` trực tiếp. Callers đã đọc có dùng executor/domain trả candidate copy; coordinator không tự cưỡng chế nguyên tắc này. Một số dependency là `Any`, có nhiều `hasattr`; disk-read exceptions và vector invalidation exceptions có nhánh bỏ qua.

**Tác động:** caller mới có thể mutate input trước save; khi lỗi sẽ làm lệch memory và storage. Việc nuốt lỗi giảm khả năng giải thích trạng thái, nhưng chưa chứng minh tất cả các nhánh đó gây corruption.

**Cải tiến:** quy định candidate contract rõ, chọn enforcement phù hợp chi phí; test executor cố ý mutate rồi throw. Định nghĩa trạng thái/lỗi cho invalidate và đọc revision; không chuyển tất cả sang deepcopy thiếu đo lường.

**Nghiệm thu:** fault injection ở các ranh giới trước/sau snapshot/save/sync; test replay sau restart và sync failure; không trả trạng thái derived data hợp lệ khi thao tác tương ứng thất bại.

### F8 — Tài liệu hiện trạng và khả năng tái lập còn thiếu chính xác [ưu tiên cao trước bảo vệ]

**Bằng chứng:** đầu `AI/structure.md` vẫn vẽ facade là Central Orchestrator, mô tả loại bỏ hoàn toàn `dict.get/from_dict`, trong khi application hiện tại vẫn dùng dict và `.from_dict`. Có các tuyên bố “100%”, “Zero Training-Serving Skew”, “Production” chưa được lượt kiểm tra này chứng minh. `ReadProjectionPort` docstring còn gọi SQLite là SSOT dù authoritative theo AGENTS là JSON.

**Cải tiến:** dùng tên “Modular Monolith đang hoàn thiện ranh giới”; phân biệt hiện trạng, legacy và đích. Một sơ đồ runtime đúng + ADR nguồn sự thật + bảng invariant/bằng chứng có giá trị hơn các khẳng định tuyệt đối. Dùng dict cho bundle không tự nó là sai; cần contract ở biên và parity/lossless tests.

**Nghiệm thu:** mọi tuyên bố quan trọng có file/test/đo lường hỗ trợ; dependency/runtime và fixture tái lập được; không lấy báo cáo cũ thay kết quả hiện tại.

## 5. Kết quả kiểm thử hiện tại

Lệnh: `& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py`

- Discovered/run: **239 tests**.
- Kết quả: **237 đạt, 1 failure, 1 error**, exit code **1**.
- Thời gian test runner báo: **9.861 giây**; không phải benchmark hiệu năng ứng dụng.
- 4 architecture boundary tests và 6 commit coordinator tests đạt.

| Ca chưa đạt | Bằng chứng | Diễn giải |
| --- | --- | --- |
| `tests.test_gazetteer_feedback_loop.TestGazetteerFeedbackLoop.test_preload_historical_template` | Dòng 265 assert `Path("data/hanoi_historical_gazetteer.json").exists()` thất bại | Runner không copy data template này vào shadow workspace; chưa đi tới assert nội dung để kết luận domain sai |
| `tests.test_ui_ux_improvements.TestUIUXImprovements.test_u1_theme_config_and_pipeline_banner_hierarchy` | Dòng 148 đọc `.streamlit/config.toml` → FileNotFoundError | Runner không copy `.streamlit` vào shadow workspace; chưa kiểm chứng phần còn lại của ca |

`tools/run_isolated_tests.py` chỉ copy các source/config directories được liệt kê, không copy hai tài nguyên trên. File tương ứng tồn tại trong working tree; đây là thiếu sót ở test packaging/isolation cần sửa, không được xóa/skip test để báo xanh. Chỉ copy chính xác theme và fixture công khai cần thiết, không copy toàn bộ `data/` hoặc secrets. Đối với từ điển mẫu, cân nhắc resource của package hoặc test fixture thay vì dựa vào cwd dữ liệu dự án.

Không sửa runner/source trong lượt audit này. Chưa chạy lại với fixture bổ sung, do đó **không công bố full suite PASS**.

## 6. Kế hoạch cải tiến theo thứ tự

| Đợt | Đầu vào | Công việc/đầu ra | Điều kiện đạt |
| --- | --- | --- | --- |
| R0 — Tái lập | Hai test thiếu file, runner hiện tại | Khai báo tài nguyên test an toàn; báo cáo full suite mới | 239 test hiện tại được chạy đầy đủ, xử lý đúng mọi lỗi còn lại; không đọc dữ liệu thật |
| R1 — Khóa và commit | Audit F1/F7; inventory tất cả mutation callers | Public lock contract, identity thống nhất, migrate write paths vào lifecycle | Cross-use-case concurrency, rollback, stale state và replay tests đạt |
| R2 — Độ mới projection | F2; sync_pending và revision hiện có | Freshness contract, resync/explicit stale behavior | Ép sync fail rồi query không im lặng trả stale |
| R3 — Boundary và DI | F3/F4/F5; allowlist hiện tại | Migrate public imports, inject adapter dependencies, guards bổ sung | Negative tests chứng minh guard bắt lỗi mới; giảm allowlist có bằng chứng |
| R4 — Transport và contracts | F6/F7; consumer matrix | Explicit local/remote capabilities, lỗi và contracts rõ | Không local mutation khi remote được chọn; lossless serialization/parity |
| R5 — Bằng chứng bảo vệ | Tài liệu/sơ đồ cũ, kết quả R0–R4 | Sơ đồ đúng, ADR tradeoffs, bảng giới hạn, benchmark tải đại diện | Không có tuyên bố vượt bằng chứng; tái chạy được từ môi trường khai báo |

R0 có thể làm ngay; R1/R2 ưu tiên trước thêm mutation mới. R3 không cần chờ UI làm đẹp. Mỗi đợt có phạm vi độc lập để review/rollback, không gộp thay thuật toán, nâng framework và refactor storage vào cùng đợt. Không xóa dữ liệu, lịch sử, tests hoặc generated graph trong cleanup. Sau source changes phải cập nhật graph theo AGENTS; lượt này chỉ thêm báo cáo nên không chỉnh graph.

## 7. Câu hỏi hội đồng có thể đặt và cách trả lời trung thực

**Vì sao không microservices?** Sáu năng lực cùng phục vụ một workflow, chia sẻ tính nhất quán dự án, cần triển khai local đơn giản. Module boundaries và ports cho phép thay adapter mà không cần chi phí network/deployment của nhiều service. Chỉ tách tiến trình khi có yêu cầu tải/cách ly được đo.

**Có đúng Clean Architecture hoàn toàn không?** Không nên nói hoàn toàn. Có module/use case, public API và ports; còn legacy domain–infrastructure và fallback wiring đang migrate. Công bố các ngoại lệ cụ thể và kế hoạch gỡ.

**Có bảo đảm không mất dữ liệu khi nhiều người cùng sửa?** Có cơ chế revision, idempotency và khóa trong process trên đường coordinator; hiện còn mismatch khóa/đường ghi cần sửa. Chưa có cơ sở cam kết đa tiến trình. Nếu triển khai nhiều worker phải có cơ chế concurrency liên tiến trình/storage-level và tests riêng.

**Vì sao JSON và SQLite cùng tồn tại?** JSON là authoritative bundle phục vụ lưu/khôi phục, SQLite là read projection phục vụ truy vấn. Đây là tradeoff phù hợp local nhưng tạo nghĩa vụ freshness/resync; không gọi cả hai là nguồn sự thật độc lập.

**Test xanh có chứng minh kiến trúc tốt không?** Không. Lượt này full suite còn hai ca thiếu tài nguyên; các architecture tests đạt chỉ chứng minh bốn quy tắc được encode. Phải bổ sung guard và fault/concurrency tests theo invariant, rồi đo workload thực tế.

**Kiến trúc tốt có chứng minh KG đúng lịch sử hoặc thuật toán tốt hơn baseline không?** Không. Kiến trúc hỗ trợ tái lập, provenance, kiểm chứng và so sánh công bằng. Cần gold độc lập, người chấm, định nghĩa metric và kiểm soát model/prompt/input/budget để bảo vệ chất lượng khoa học.

## 8. Phán quyết cuối

**Đạt về lựa chọn hướng kiến trúc và nhiều nền tảng triển khai; chưa đạt mức tuân thủ đầy đủ các bất biến do chính dự án công bố.** Điểm cần sửa trước tiên là tính thống nhất của commit/lock, freshness của projection và khả năng kiểm chứng boundary. Cải tiến có mục tiêu trên nền hiện tại hợp lý hơn thay kiến trúc một lần nữa.
