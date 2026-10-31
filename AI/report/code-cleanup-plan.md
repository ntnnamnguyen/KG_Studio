# Kế hoạch thu gọn và dùng chung mã nguồn KG Studio

- **Ngày rà soát:** 31/10/2026.
- **Phạm vi:** mã nguồn `KG_Studio`, entrypoint UI/API/CLI, public exports, test, công cụ và khai báo dependency.
- **Yêu cầu:** giảm mã dư, giảm lặp, rõ trách nhiệm; giữ nguyên logic nghiệp vụ, định dạng dữ liệu, hành vi công khai và các biện pháp bảo mật đang có.
- **Trạng thái:** đã rà soát và chạy baseline; **chưa refactor hoặc xóa mã nguồn ứng dụng**.
- **Liên quan:** [structure.md](../structure.md), [hiệu năng](performance-optimization.md), [pipeline UI](layout-pipeline-proposal.md), [prompt versioning](../features/prompt-versioning.md).

## 1. Kết luận và thứ tự ưu tiên

Nên tối ưu bằng các đợt nhỏ: **khóa hành vi bằng test → dọn mã không dùng đã xác minh → gom helper thuần → tách module lớn → dùng chung điều phối giao dịch sau cùng**.

Có các phần dư có thể xử lý sớm, nhưng không nên xóa mọi wrapper hoặc helper chuyển tiếp. Một số là hợp đồng import công khai, test seam, CLI, hoặc ranh giới frontend/backend có giá trị. Mã ngắn hơn không đồng nghĩa kiến trúc tốt hơn nếu làm mất các ranh giới đó.

Không đưa migration sang SQLite authoritative, thay thuật toán tìm node trùng, đổi prompt, nâng thư viện hoặc đổi UI vào cùng đợt thu gọn. Những thay đổi đó có kế hoạch riêng và có thể thay kết quả. Đợt này chỉ tối ưu cách tổ chức/thực thi với bằng chứng tương đương hành vi.

## 2. Baseline đã thực hiện

### 2.1. Phân tích tĩnh

Đã parse AST các file `.py`, bỏ qua dữ liệu, venv và `__pycache__`, kết hợp tìm references bằng `rg` và đọc các nhánh liên quan:

| Chỉ số | Kết quả tại lúc rà soát |
| --- | ---: |
| File Python, gồm tests/tools | 101 |
| Tổng dòng, gồm dòng trắng/comment/test | 21.073 |
| Import binding có dấu hiệu không được dùng cục bộ | 62 ứng viên |
| Cặp hàm có body AST trùng đáng chú ý | Hai loader JSONL của trainer; constructor retriever/aligner |
| Khối không thể tới sau return ở cấp thân hàm | `shared/config_loader.py::default_catalogs` |

**62 là số ứng viên, không phải 62 import được phép xóa.** Phép phân tích chỉ xét local name loads và `__all__` dạng trực tiếp; có false positive ở re-export, alias tương thích, introspection và import phục vụ side effect. AST body giống nhau cũng chưa đủ lý do tạo lớp cha.

Các file lớn cần xem xét tách theo trách nhiệm:

| File | Số dòng baseline | Nhận định |
| --- | ---: | --- |
| `backend/domain/curation/service.py` | 2.099 | Evidence, validation, review, edit, duplicate matching, merge, statistics cùng một module |
| `frontend/state/session.py` | 1.207 | Navigation/readiness, state EDC, edge/entity/merge, return context |
| `backend/facade.py` | 1.148 | Orchestration, prompt preview, commit EDC/curation, nhiều adapter công khai |
| `backend/domain/catalogs/service.py` | 901 | Catalog, extraction prompt, proposal ingestion/impact, review/commit domain |
| `frontend/components/curation_table.py` | 838 | Filter/sort/rows, edge batch operations và entity table |

Số dòng là tín hiệu về trách nhiệm, không phải tiêu chí chất lượng độc lập. Không đặt mục tiêu cắt một tỷ lệ LOC tùy ý.

### 2.2. Kiểm thử thực tế

- Interpreter: Python **3.13.2**, venv hiện có tại `KG_Studio_MVP/.venv-win/Scripts/python.exe`.
- Chạy `unittest discover` trên **bản sao tạm** của source/config và các tệp dự án cần cho test; `APP_ROOT`, project storage, DB, vector indices và output phát sinh nằm trong bản sao tạm.
- Kết quả: **56 tests, 0 failures, 0 errors, 0 skipped**. Lần xác nhận hoàn tất có exit code 0; thư mục thử đã được dọn.
- Thời gian runner khoảng **1,67 giây**, chỉ là thời gian bộ test trong môi trường này, không phải benchmark hiệu năng app.
- Không chỉnh cấu hình hoặc dữ liệu ứng dụng gốc; không dùng kết nối LLM/Neo4j thật để nghiệm thu refactor.

Test hiện tại đạt không đồng nghĩa mọi bề mặt bảo mật đã được kiểm tra. Phải bổ sung characterization/negative tests cho đường chuẩn bị thay đổi.

## 3. Hợp đồng phải giữ nguyên

1. Public import còn được dùng, entrypoint terminal, CLI flags, API routes, DTO field/default/coercion và mã trạng thái lỗi đã được xác định.
2. Cấu trúc JSON/catalog/prompt history/snapshot, ID node/edge/proposal, Unicode, span ký tự, dữ liệu mở rộng và khả năng nạp dự án cũ.
3. Mọi validator về schema, bằng chứng, ngoại lệ, chiều quan hệ, self-loop và trạng thái; không tự duyệt vì evidence có trong văn bản.
4. Phạm vi duyệt lô, all-or-nothing/valid-only, chọn theo ID, preview invalidation và hành vi giữ lựa chọn/draft.
5. Snapshot/audit/idempotency/revision, namespace request theo dự án và loại thao tác; không bỏ kiểm tra khi I/O gặp lỗi.
6. Sau JSON commit thành công nhưng SQL sync lỗi phải vẫn biểu diễn đúng committed/sync pending. Không dùng một wrapper chung biến mọi lỗi thành rollback hoặc mọi lỗi thành thành công.
7. Nội dung prompt/request thực tế, token clamp, provider fallback, reasoning flags và quan hệ provenance; giữ hash/ID cũ khi chưa có migration riêng.
8. Cache key, model/catalog fingerprint, invalidation và giới hạn bộ nhớ. Không trả mutable cache object cho caller rồi để caller sửa bản dùng chung.
9. Sanitization/HTML escaping, SQL/Cypher parameterization, secret scrubbing, upload/path rules, cấu hình bind local và timeout/đóng kết nối.
10. Ranh giới `shared` không phụ thuộc frontend/backend; Pro không import mã MVP. Dùng interpreter của venv cũ để chạy không phải phụ thuộc mã ứng dụng MVP.

Nếu characterization cho thấy một hành vi hiện tại là lỗi, ghi issue riêng và có test mô tả hành vi mong muốn. Không âm thầm sửa lỗi nghiệp vụ dưới tên “cleanup”. Riêng phát hiện bảo mật cần được ưu tiên xử lý, nhưng vẫn tách thay đổi và chỉ rõ ảnh hưởng hợp đồng.

## 4. Danh sách có thể dọn sớm sau khi kiểm tra references

### 4.1. Hàm private và khối không thể chạy

| Vị trí | Bằng chứng | Cách xử lý giữ nguyên hành vi |
| --- | --- | --- |
| `p04_edc_alignment.py::_render_batch_history_and_restore` | Chỉ thấy định nghĩa trong source hiện tại; Hub dùng shared history component trực tiếp | Kiểm tra reference string/dynamic/test một lần nữa; nếu không có, xóa hàm và import chỉ dùng cho hàm đó |
| `p05_curation_merge.py::_render_curation_batch_history` | Tương tự; wrapper render đã dẫn vào Hub | Xóa private helper không còn gọi, giữ wrapper công khai |
| `shared/config_loader.py::default_catalogs` | Có `return {'relations': [], 'entity_types': []}` rồi một `return` khác không thể tới | Xóa dòng chết và import chỉ phục vụ dòng chết. **Giữ kết quả trả catalog rỗng hiện tại**; không tự khôi phục default catalog theo ý định đoán từ dòng cũ |
| `facade._previews` | Tìm thấy khởi tạo và gán khi preview EDC, chưa thấy nơi đọc trong repo | Kiểm tra caller/introspection bên ngoài; nếu chỉ là trạng thái write-only nội bộ, bỏ lưu và field. Preview DTO/ID, validation và UI storage phải giữ nguyên |

Không lấy tên private làm bằng chứng duy nhất. Helper có thể được truyền callback, import test hoặc tra bằng chuỗi.

### 4.2. Import có dấu hiệu dư rõ trong module đã đổi trách nhiệm

Các ví dụ cần xử lý từng file, không áp dụng xóa hàng loạt tự động:

- `frontend/components/edc_alignment_panel.py`: `streamlit`, `get_facade`, `get_client`, `edc_prompt`, default prompt và settings DTO còn từ trước khi chuyển sang delegate prompt editor.
- `frontend/components/curation_table.py`, `edc_review_table.py`: `math` còn lại sau khi dùng `paginate_items` chung.
- `backend/domain/prompts/service.py`: `copy`, `Any`, `PromptVersionDTO` có dấu hiệu không dùng trực tiếp.
- `backend/facade.py`: một số prompt DTO và `ensure_project_prompt_history` chưa được dùng tại vị trí import.
- `frontend/state/session.py`: `json`, `sha`, `STATUS_REJECTED` cần xác minh sau thay đổi hiện tại.
- `run_app.py`: `Path` chưa thấy dùng.

Sau xóa, chạy import smoke và test liên quan. Với module public export, kiểm tra cả `module.Symbol`, `from module import Symbol` và `__all__`, không chỉ AST local reads.

## 5. Những phần không được xóa chỉ vì ít references

### 5.1. Wrapper và re-export đang có hợp đồng

- `backend/integrations/llm_gateway.py` là compatibility facade cho package LLM mới; nhiều source còn import đường dẫn này và `test_llm_package` kiểm tra alias identity. Giữ module, có thể chuyển caller nội bộ sang canonical import từng đợt; không xóa shim trong đợt không đổi hợp đồng.
- `p04_edc_alignment.py` có `compute_edc_overview_counts` được import lại nhưng **`test_edc_bulk_review.py` import từ chính wrapper này**. Đây là ví dụ thực tế AST báo dư nhưng tên vẫn là re-export được sử dụng. Giữ hoặc ghi re-export rõ ràng, không xóa bằng auto-fix.
- `p05_graph_export.py` là re-export sang trang canonical `p06_graph_export.py`. Dù app dùng trang canonical, đường dẫn cũ nằm trong tài liệu/public module; giữ shim nhỏ khi chưa xác nhận hết consumer.
- `render_edc_mode_settings` và wrapper curation còn là điểm nối component/page. Có thể bỏ logic cũ bên trong nhưng không tạo thêm vòng wrapper nối tiếp.
- `frontend/client.py` và các facade adapter ngắn có vai trò ranh giới UI/backend. Xóa client vì “chỉ gọi lại facade” sẽ làm UI phụ thuộc sâu hơn vào domain và mất điểm nối API.

### 5.2. Hạ tầng hoặc DTO chưa nối hoàn chỉnh

| Ứng viên | Hiện trạng | Quyết định đề xuất |
| --- | --- | --- |
| `backend/workers/job_manager.py` | Chưa thấy caller ngoài package tự export; thực tế có `start_sync_job`, không có worker bất đồng bộ bền vững | Ghi rõ trạng thái chưa tích hợp. Nếu là API public thì giữ/deprecate; chỉ xóa khi xác nhận không consumer và cập nhật tài liệu. Không mô tả nó như tính năng async đã có |
| `shared/schemas/queries.py` | DTO được khai báo nhưng chưa thấy được sử dụng ở đường đọc; query hiện trả dict | Giữ nếu đợt tối ưu read model đang tiếp tục. Không nối vào toàn app chỉ để “làm cho được dùng”; không xóa cả roadmap mà không quyết định phạm vi |
| `ProjectRepository` | `JsonProjectRepository(ProjectRepository)` dùng thật; repositories package export interface | Giữ interface; không đánh dấu chết do facade nhận concrete repo |
| `__init__.py`, engine registry | Dùng public exports và registration | Không xóa hay đổi lazy import tùy tiện; phải kiểm tra side effects/import order |

Sản phẩm của bước này là inventory: `keep`, `delete-private`, `compatibility`, `planned-but-inactive`. Không để tên gọi “dead code” bao trùm cả tính năng dự kiến và API công khai.

## 6. Các phần nên dùng chung

### 6.1. Loader JSONL cho ML Lab — rủi ro thấp

Hai `_load_jsonl()` trong `train_canonicalizer.py` và `train_schema_retriever.py` có body giống nhau. Đưa thành một helper trong `ml_lab` vì hiện chỉ trainer dùng; không đẩy vào `shared` nếu chưa có consumer xuyên tầng.

Giữ nguyên: tệp không tồn tại trả list rỗng; UTF-8 hiện tại; bỏ dòng trắng; thứ tự record; lỗi JSON lỗi gì vẫn báo như trước. Đợt đầu vẫn trả list, không đồng thời đổi thành generator vì caller/kiểu xử lý lỗi có thể khác.

Test: missing/empty/blank lines, tiếng Việt, JSON hỏng giữa tệp, thứ tự record và metric/model artifact trước/sau trên seed cố định.

Constructor của `SchemaRetriever` và `TargetAligner` cũng giống nhưng rất ngắn. **Không tạo base class chỉ để gom constructor này**; chúng có hai nghiệp vụ khác nhau.

### 6.2. Helper lựa chọn UI — dùng chung cơ chế, giữ riêng điều kiện

`session.py` có các cặp toggle/select-page/select-all/clear/reconcile cho proposal và edge. Có thể gom các thao tác list ID thuần: thêm duy nhất có giữ thứ tự, bỏ ID, lấy giao tập lọc và tính số bỏ chọn.

- Proposal chỉ chọn `pending` và đúng `kind`; edge chọn `Chờ duyệt`/`Cần kiểm tra`. Điều kiện này tiếp tục nằm ở wrapper nghiệp vụ.
- Giữ thứ tự ID và thông báo tương ứng; không đổi list sang set trả về làm mất thứ tự.
- Key dự án/kind/section và draft/preview vẫn tách. Không tạo một state dict dùng chung khiến lựa chọn hai bảng nhiễm nhau.
- Chỉ gom phần đủ giống; không xây SelectionManager nhiều lớp hoặc generic framework cho cả ứng dụng.

Test theo bảng dữ liệu cho từng wrapper: chọn trang, chọn mọi kết quả, đổi sort/page/filter, loại item không còn đủ điều kiện, đổi dự án, apply hợp lệ một phần.

### 6.3. Commit orchestration — rủi ro cao, làm sau

`facade.apply_proposal_decisions()` và `_commit_curation_operation()` lặp các bước: lock, idempotency lookup, check revision, snapshot, candidate save, publish memory, SQLite sync và update receipt. `save_project`/restore cũng lặp phần sync pending.

Gom trước helper nhỏ như kết quả sync và dựng receipt **chỉ khi cùng semantics**; sau đó mới xem xét một transaction coordinator nội bộ dùng policy/hook tối thiểu:

```text
normalize request và namespace
  → lock và replay/conflict
  → domain executor tạo candidate/result
  → snapshot và persist candidate
  → publish memory sau commit
  → post-commit catalog invalidation khi cần
  → sync SQLite / sync pending
  → result + receipt theo hợp đồng hiện tại
```

Các khác biệt bắt buộc giữ:

- Namespace request EDC/curation không được va chạm; cùng request ID khác payload vẫn bị từ chối.
- EDC có invalidation vector theo catalog kind/hash; curation có edit/merge history và ánh xạ node. Không áp một post-commit hook cho mọi operation mà thiếu kiểm tra.
- Bản all-or-nothing/valid-only và DTO result khác nhau, domain validation khác nhau; không gộp thành một “bulk generic” tự chọn nghiệp vụ bằng chuỗi.
- Một snapshot cho một batch theo quy tắc hiện tại, không phát sinh hai snapshot do wrapper gọi chồng nhau.
- Receipt bền vững phải được kiểm chứng sau restart. Nếu baseline bộc lộ lỗi receipt/sync đang có, ghi sửa lỗi riêng; không đổi trình tự ghi mà không test crash/replay.
- Không bỏ `deepcopy`/candidate isolation chỉ để bớt RAM. Chuyển sang patch/copy-on-write cần bằng chứng không mutate project gốc khi lỗi.

Không gọi helper thuộc UI từ coordinator, không để coordinator tự xây prompt hoặc quyết định cạnh hợp lệ.

### 6.4. Prompt composition và provenance — tránh nhân đôi phần đã có

`LLMGateway.prepare_extraction_request()` đã tồn tại và được dùng cho budget/user payload. Giữ nó là phần chuẩn bị chung; không dựng thêm gateway mới.

Hiện facade preview và engine còn có đoạn ghép base instructions/catalog/retrieval tương tự. Trích **composition thuần** có đầu vào rõ: mode, version, catalog/retrieval result, hints. Không gọi retrieval hai lần chỉ vì preview/execute dùng helper khác nhau.

Giữ system/user cuối, response format, input trimming, output cap, provider flags, hash và warnings giống baseline. Ba engine có khác nhau về vòng lặp, ingestion và Target Alignment; không ghép thành một engine nhiều `if` chỉ để giảm LOC.

Hash functions giữa EDC/curation/prompt có miền dữ liệu khác nhau. Có thể dùng chung hàm serialize nếu **đúng cùng tham số và thứ tự**, nhưng không đổi payload hash, separator, field set hoặc độ dài ID như một cleanup. Golden test phải bắt thay đổi này.

### 6.5. API và editor catalog

- API có nhiều block load project/scope/DTO/error mapping gần giống. Tách helper route nội bộ theo nhóm EDC/curation nếu có lợi, giữ nguyên route, status code, schema JSON, handling lỗi và dependency injection facade.
- Không gộp `_verify_project_scope()` thành helper có default bypass; đường nào đang kiểm tra phải tiếp tục kiểm tra trước mutation.
- Catalog editor loại thực thể/quan hệ có import/merge/replace/save/download gần giống. Chỉ gom thao tác thuần validate/merge và component parameterized theo kind; giữ widget key, label, trạng thái draft và tác động khác nhau.
- Không tạo REST client đầy đủ hoặc thay việc fallback local của FrontendClient trong đợt này; đó là thay đổi behavior/topology riêng.

## 7. Tách module lớn mà không thay đổi import công khai

### 7.1. Curation domain

Có thể tách theo các cụm đã có, tên là gợi ý:

```text
backend/domain/curation/
  service.py          # facade/re-export công khai tương thích
  evidence.py         # đối chiếu text/span, context
  validation.py       # điều kiện duyệt/xuất và schema status
  review.py           # preview/apply quyết định cạnh
  entities.py         # hồ sơ, bậc và duplicate suggestions
  merge.py            # preview/apply merge và redirect
```

Không tạo hết file nếu một cụm quá nhỏ. Chuyển nguyên hàm trước; các helper `find_node`, `find_edge`, `find_document` đặt ở module hẹp mà các cụm dùng được, tránh import vòng giữa graph/curation/catalogs. Không dùng wildcard re-export làm mất khả năng theo dõi tên.

Caches có thể đang ở module global và được test/monkeypatch truy cập: chuyển nguyên ownership/lifetime hoặc giữ alias tương thích có test. Không vô tình có hai cache sau tách module.

### 7.2. Frontend state và bảng

- `session.py` giữ API hiện tại, tách nhóm `navigation`, `edc_state`, `curation_state` nếu giảm phụ thuộc. Helper thao tác ID thuần nằm chung một chỗ.
- `curation_table.py` có thể tách edge/entity rendering và helper filter/row model; giữ module cũ export các tên đang được Hub/test import.
- Chuyển từng cụm và chạy test sau mỗi lần, không đổi toàn bộ import tree trong một commit.
- Không đổi widget keys, nhãn route ổn định, thứ tự thao tác hoặc cơ chế session persistence khi chỉ di chuyển file.

### 7.3. Facade và catalog

Sau khi helper commit và composition rõ ràng, facade còn điều phối các use case thay vì chứa toàn implementation. Các method đang dùng vẫn tồn tại để callers không phải đổi đồng loạt.

Catalog service có thể tách proposal impact và review domain nếu thực sự giảm coupling. Không chuyển mọi thứ có từ “prompt” ra khỏi catalog service mà làm mất public `extraction_prompt`/`prompt_signature` đang được engine/test sử dụng; giữ adapter rõ ràng.

## 8. Bảo mật: giữ hàng rào hiện có, xác minh các khoảng trống

### 8.1. Không được làm yếu khi dùng chung code

| Bề mặt | Quy tắc refactor | Test cần có |
| --- | --- | --- |
| SQL/Cypher | Giá trị vẫn truyền bằng parameters; sort/field động phải whitelist | Payload chứa nháy, ký tự SQL/Cypher vẫn là dữ liệu; không ảnh hưởng project khác |
| Project scope | Kiểm tra đúng dự án và ID trước mutation | Request URL/body khác project bị từ chối theo hợp đồng hiện tại |
| Evidence HTML | Giữ `html.escape` trong `format_highlighted_evidence_html` trước `unsafe_allow_html` | `<script>`, dấu nháy, HTML và reason không thành nội dung thực thi |
| JSON/snapshot/export | Giữ `scrubbed`, không thêm key/header/SDK object vào DTO public | Canary API key/password không xuất hiện ở snapshot/export/preview/log |
| Tệp/đường dẫn | Giữ sanitize và kiểm tra storage scope tại boundary | Tên `../`, backslash, tên tuyệt đối, ID ngoại dự án không vượt phạm vi cho phép |
| Vector/model artifacts | Giữ `allow_pickle=False`, fingerprint và invalidation | Chỉ mục hỏng/stale không trở thành payload pickle được thực thi |
| Kết nối ngoài | Giữ timeout, retry và đóng client tạo nội bộ; không đóng driver do caller truyền | Fake client kiểm tra options, cleanup sau thành công/lỗi |
| Request hash/preview | Không mất liên kết config/version/catalog/chunk đang dùng | Stale hoặc payload sửa bị chặn theo hợp đồng, retry không commit hai lần |

Không ghi secret thật vào test. Dùng chuỗi canary giả và kiểm tra output cụ thể. Secret scrubbing theo key không phải giải pháp đầy đủ nếu ngoại lệ chứa nguyên secret trong chuỗi.

### 8.2. Các điểm cần review riêng, chưa được chứng nhận an toàn

- `restore_snapshot(project, path)` hiện đọc path được truyền vào. UI lấy snapshot từ danh sách server không đồng nghĩa mọi caller facade/API đều có cùng boundary; cần kiểm tra chặn đường dẫn ngoài snapshot folder trước khi mở rộng API.
- API stdlib đọc body từ Content-Length và các route có thể trả `str(exc)` trực tiếp; trong phần đã đọc chưa thấy một lớp auth và giới hạn body thống nhất. Mặc định bind local phải được giữ; không kết luận đủ an toàn để public Internet chỉ vì test pass.
- SQLite `sync_from_project_dict` serialize full dict vào `raw_json`, trong khi đường JSON có `scrubbed`. Kiểm tra canary ở **cả DB**; nếu tồn tại rò rỉ, đây là lỗi bảo mật cần ticket/patch riêng, không che bằng test chỉ kiểm tra file JSON.
- Local embedding/generated QLoRA có `trust_remote_code=True`. Không tăng phạm vi tin cậy hoặc tự đổi chính sách model dưới tên cleanup; nếu cần allowlist/pinning/opt-in thì làm thay đổi bảo mật có tài liệu riêng.
- Catch-all ở recovery, revision check, marker hoặc client fallback phải phân loại. Xóa `except` hàng loạt có thể gây crash; nuốt lỗi rộng hơn có thể bỏ kiểm tra hoặc che sync failure. Khóa hành vi bằng fault-injection trước khi chỉnh.

Các điểm trên là phạm vi review từ code, chưa phải báo cáo khai thác hay kiểm toán bảo mật toàn diện. Negative test mới thất bại không được tự cập nhật expected để biến hành vi chưa an toàn thành đạt yêu cầu. Ghi rõ lỗi nền, sửa riêng và chỉ công bố đã khắc phục sau test thực tế.

## 9. Dependency và packaging

Không xóa thư viện chỉ từ import AST:

- `streamlit`, `openai`, `anthropic`, `neo4j`, `pypdf`, `python-docx`, `numpy` có đường sử dụng thật hoặc import trong hàm.
- `graphviz` cần kiểm tra cả runtime trực quan hóa và executable `dot`; binary không phải Python dependency có thể xóa thay thế cho nhau.
- Extras `api`, `embed`, `ml` phục vụ entrypoint/optional feature; QLoRA còn sinh mã có imports nằm trong chuỗi, AST bình thường không coi là import của app.
- File compatibility/package exports có thể phục vụ người dùng ngoài repo. Nếu không có chính sách public API, giữ shim nhỏ và ghi thời điểm/điều kiện deprecation.

Trước mọi thay đổi dependency: lập ma trận feature→package→entrypoint; smoke core và extras được hỗ trợ trong môi trường riêng. Không uninstall package từ venv đang dùng trong nhiệm vụ viết kế hoạch.

## 10. Chỉ dẫn thực hiện theo từng đợt

### Đợt 0 — Khóa baseline và phạm vi

1. Đọc lại source mới nhất và AGENTS nếu có; đối chiếu số liệu vì repo có thể được agent khác cập nhật.
2. Xác định interpreter, version/dependency và entrypoints: `run_app.py`, `frontend/app.py`, `backend.main`, engine registry, ML CLI, benchmark tool.
3. Lập inventory caller cho mỗi ứng viên, gồm references qua chuỗi, public exports, callback, CLI và test. Gắn mức tin cậy, không chỉ “0 lần grep”.
4. Chạy test trên bản sao tạm hoặc fixture injection; tránh bộ test dùng `get_facade()` mặc định chạm DB dự án thật. Có phép đo performance thì giữ seed/môi trường giống nhau.
5. Tạo characterization fixtures cho curation, prompt/request và persistence trước khi di chuyển code. Dùng ID/time được cố định trong test; không xóa các field nghiệp vụ khi normalize.

**Kết quả:** baseline test và inventory có bằng chứng; chưa xóa source.

### Đợt 1 — Dọn private code và import

1. Xử lý hai history helper private, return không thể tới và import dư đã xác minh.
2. Kiểm tra `_previews` write-only; bỏ nếu không có consumer cần bảo toàn, giữ preview behavior.
3. Giữ wrapper/re-export công khai, nhất là tên được test import. Có thể khai báo re-export rõ hơn để analyzer phân biệt.
4. Smoke import từng module đổi, chạy test tương ứng và full suite. Review diff để không lẫn thay return/default/validation.

**Kết quả:** không còn các phần dư đã xác nhận; không mất public symbol hoặc module. Ghi số import/hàm/dòng thực sự loại bỏ, không hứa xóa cả 62 ứng viên.

### Đợt 2 — Dùng chung helper rủi ro thấp

1. Gom loader JSONL; giữ behavior và test malformed input.
2. Gom helper thuần về danh sách ID và dùng lại qua wrapper nghiệp vụ.
3. Gom phần import/merge catalog giống nhau khi test editor giữ trạng thái đạt yêu cầu.
4. Không gom constructor ngắn, không thêm base class/mixin không cần thiết.

**Kết quả:** một implementation cho từng cơ chế thuần; nghiệp vụ và tên gọi công khai vẫn riêng rõ.

### Đợt 3 — Tách module lớn

1. Chuyển từng cụm curation sang module trách nhiệm hẹp; `service.py` giữ exports cũ.
2. Tách state navigation/EDC/curation và edge/entity rendering theo nhu cầu thực tế.
3. Giữ cache ownership, monkeypatch path, imports và widget keys.
4. Sau mỗi cụm chạy import-cycle smoke và test theo vùng; không thay output/performance policy trong cùng commit.

**Kết quả:** module chính ngắn và rõ trách nhiệm hơn, tổng số LOC có thể không giảm nhiều vì adapter tương thích được giữ.

### Đợt 4 — Chuẩn hóa composition và orchestration

1. Gom prompt composition, so sánh payload thực tế của ba engine/preview qua fake SDK.
2. Tách sync helper và receipt helpers nhỏ trước; kiểm tra lỗi/replay.
3. Chỉ khi đã có characterization đủ mới trích coordinator dùng chung cho EDC/curation với phần khác biệt rõ ràng.
4. Tách API helper nếu giảm lặp mà không đổi mapping route/error.

**Kết quả:** giảm implementation lặp ở các đường quan trọng, không tăng số lần gọi LLM/I/O/snapshot và không bỏ kiểm tra.

### Đợt 5 — Nghiệm thu và bàn giao

1. Chạy toàn bộ test, import/package/CLI smoke và UI flows liên quan trên dữ liệu tạm.
2. Chạy negative security tests và ghi rõ phát hiện nền nếu có; không đánh đồng với chứng nhận hệ thống an toàn.
3. So sánh golden outputs, counts/call order, artifact trước/sau và timings nếu thay execution path.
4. Cập nhật `structure.md`, inventory/deprecation và README theo code thực tế. Không sửa các plan lịch sử để giả như chức năng dự kiến đã tồn tại.
5. Bàn giao mỗi đợt bằng thay đổi độc lập có thể hoàn tác; nếu workspace không dùng Git, lưu diff/bản sao source trước đợt. Không reset code khác hoặc dữ liệu người dùng để rollback.

## 11. Chiến lược kiểm thử bảo toàn logic

### 11.1. Bộ hiện có phải giữ đạt

`test_standalone_architecture`, `test_edc_bulk_review`, `test_curation_merge`, `test_curation_hub`, `test_layout_pipeline`, `test_llm_package`, `test_performance_optimizations`, `test_prompt_versions`.

Không xóa test compatibility để được phép xóa wrapper; chỉ đổi test theo một thay đổi API được chấp thuận riêng. Không viết test dựa vào số dòng/tên helper private vừa tạo.

### 11.2. Kiểm thử so sánh trước/sau

| Nhóm | Fixture và assertion |
| --- | --- |
| Import/API compatibility | Các đường import cũ/canonical trả cùng callable/class khi hợp đồng yêu cầu; CLI flags/API response giữ đúng |
| Selection/state | IDs/thứ tự, notice, draft, focused item và preview state giống trước với cùng chuỗi thao tác |
| Curation/schema | Một/lô approve/merge/reject, all-or-nothing/valid-only, proposal impact trực tiếp/gián tiếp, self-loop và override |
| Entity merge | Giữ ID, redirects, aliases có dấu, các bằng chứng/edge ID, audit, cạnh bị đưa kiểm tra lại đúng phạm vi |
| Prompt/LLM | So sánh system/user/messages, schema, budget/clamp, reasoning flags, warnings, loop/hints và request/version refs bằng fake SDK |
| Persist/transaction | I/O lỗi từng bước, snapshot đúng một lần, memory publish sau commit, SQL sync failure, idempotent replay và restart |
| Catalog/defaults | Catalog empty hiện tại, validate v2, import/merge/replace, history/extra fields và project legacy |
| ML data | JSONL read semantics, record labels, metric/artifact định dạng và Unicode; không biến evidence_found thành nhãn con người |
| Security | Scope, parameterization, escape HTML, canary secrets trên JSON/SQLite/preview/export, path boundary và pickle flags |

Golden fixture chỉ normalize ID/time khi đó là yếu tố không xác định và được map nhất quán. Không loại bỏ audit, status, error, spans hoặc prompt hash vì test đang khác. Với LLM thật không kỳ vọng output deterministic; refactor parity kiểm bằng payload/fake response cố định.

### 11.3. Fault-injection tối thiểu cho coordinator

- Lỗi trước domain execute; snapshot lỗi; writer JSON lỗi từng tệp trong bundle; journal recovery.
- JSON đã commit nhưng SQL sync lỗi; vector invalidation lỗi sau commit.
- Replay cùng request ID/nội dung; cùng ID khác nội dung; ID giống giữa EDC/curation hoặc giữa hai dự án.
- Revision thay giữa preview/apply; disk load lỗi; hai session cùng thay đổi.
- Process mới đọc receipt/marker và trả đúng kết quả; không chỉ replay từ cache trong cùng instance.

Nếu behavior nền chưa đúng, ghi rõ test đỏ trước refactor và lỗi tương ứng. Không giảm mức kiểm tra để bảo vệ một helper chung mới.

## 12. Lệnh kiểm tra và cách cô lập

Trong terminal dùng đúng interpreter hiện có; ví dụ môi trường đã rà soát:

```powershell
Set-Location D:\DATN\CrawData\KG_Studio
$kgPython = 'D:\DATN\CrawData\KG_Studio_MVP\.venv-win\Scripts\python.exe'
& $kgPython -c "import sys; print(sys.executable); print(sys.version)"
```

Chạy các lệnh test sau **trong bản sao ứng dụng tạm**, hoặc sau khi fixture/repository injection bảo đảm toàn bộ đường ghi đã tách khỏi dự án thật:

```powershell
& $kgPython -m unittest tests.test_llm_package tests.test_prompt_versions -v
& $kgPython -m unittest tests.test_edc_bulk_review tests.test_curation_merge -v
& $kgPython -m unittest discover -s tests -t . -v
& $kgPython run_app.py --check-config
```

`KG_STUDIO_PROJECTS_DIR` một mình chưa cô lập toàn bộ runtime: SQLite/vector/export/model registry có đường default theo `APP_ROOT`. Cách đã dùng cho baseline là copy source/config/test cùng các project files cần thiết sang thư mục tạm, rồi chạy từ root bản sao. Khi cleanup trên Windows phải đổi working directory ra ngoài thư mục tạm trước, xác minh đường dẫn nằm đúng vùng tạm rồi mới xóa.

Đề xuất thêm script runner cô lập dùng lại nếu nhóm cần chạy thường xuyên; không tạo thêm framework test. Các test mới tận dụng fake clients/temporary repos hiện có, không gọi API tính phí, Neo4j production hoặc tải model lớn.

Phân tích AST/import là công cụ đề xuất, không cơ chế auto-delete. Nếu thêm linter development thì thống nhất cấu hình trước, chạy chế độ báo cáo trên scope thay đổi; không dùng broad auto-fix làm mất re-export hoặc import side effects.

## 13. Kết quả cần đạt và cách xác minh

| Kết quả mong muốn | Bằng chứng nghiệm thu |
| --- | --- |
| Xóa đúng mã không dùng | Inventory trước/sau có references, quyết định và test kèm từng mục; private dead helpers/return dư đã xử lý |
| Giảm import dư | Không còn ứng viên đã xác minh trong scope sửa; exemptions cho public exports rõ ràng |
| Dùng chung đúng chỗ | Hai JSONL loader còn một nguồn; helper selection/composition/commit chung chỉ cho cơ chế thật sự giống |
| Dễ bảo trì | Mỗi cụm domain/state có trách nhiệm rõ, không import vòng; facade/public API giữ ổn định |
| Logic không đổi | Baseline 56 test vẫn đạt, test mới đạt, golden outputs/payload/call order tương đương |
| Dữ liệu an toàn | Không đổi ID/format/span/audit/history; lỗi ghi và recovery đã kiểm tra; không chạm dữ liệu thật khi test |
| Bảo mật không suy giảm | Giữ kiểm tra/escaping/parameterization/scrubbing; negative tests đạt hoặc phát hiện nền được xử lý riêng rõ ràng |
| Hiệu năng không lùi | Không tăng số LLM calls/full scans/snapshot/save; nếu đường chạy đổi, benchmark cùng fixture và môi trường |
| Không phình abstraction | Không thêm dependency runtime; module/helper mới có caller thực; tổng LOC và số wrapper được giải thích |

Không cam kết giảm 30% code hay tăng tốc nhiều lần trước khi triển khai/đo. Phần tách module chủ yếu giảm chi phí bảo trì; phần bỏ trạng thái write-only/import nặng hoặc xử lý lặp mới có thể giảm RAM/độ trễ, phải chứng minh riêng.

## 14. Checklist bàn giao cho AI Agent

- [ ] Đã xác nhận caller/export/dynamic usage trước khi xóa.
- [ ] Đã giữ `default_catalogs()` trả đúng giá trị hiện tại, không tự sửa default.
- [ ] Đã giữ public compatibility imports, entrypoints và wrapper còn có consumer.
- [ ] Đã phân biệt `dead`, `compatibility`, `planned-but-inactive`, không xóa cả ba như nhau.
- [ ] Đã khóa selection/DTO/hash/prompt/persist behavior bằng test trước khi gom.
- [ ] Không đồng thời sửa thuật toán, migration storage, UI workflow hoặc policy bảo mật trong cleanup commit.
- [ ] Không làm yếu schema/evidence/project scope/revision/idempotency/HTML escaping/secret handling.
- [ ] Đã chạy baseline và sau thay đổi trên storage tạm; cung cấp kết quả thực, không dùng con số từ tài liệu cũ.
- [ ] Đã cập nhật kiến trúc theo source cuối, ghi phần chưa làm và rủi ro còn lại.
- [ ] Có diff/bản sao và cách rollback source theo từng đợt, không đụng dữ liệu người dùng.
