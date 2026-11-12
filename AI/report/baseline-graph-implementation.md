# Triển khai KG baseline B và đầu vào graph dùng chung

Ngày: 12/11/2026. Phạm vi: bổ sung bước dựng KG cho baseline LLM-only hiện có, tái sử dụng thuật toán/giao diện và kiểm tra logic. Không thêm entity resolution ngữ nghĩa, từ điển ngữ nghĩa, framework hoặc dependency mới.

## 1. Kết quả và luồng dữ liệu

```text
Extraction: LLM → raw baseline runs (giữ nguyên)
                         ↓ public read API qua port
Graph QA: chọn run_ids → pure graph builder → GraphSnapshotDTO
                         ↓
Trang 5 dùng chung: Graphviz / PCST / PPR / Naive Top-K / Benchmark / JSON / CSV
```

KG baseline là bản biểu diễn dẫn xuất chỉ đọc. Không ghi nó vào `project["nodes"]` hoặc `project["edges"]`, không tự duyệt fact hoặc schema, không tạo đường save/snapshot thứ hai. Raw JSON project bundle vẫn authoritative; snapshot graph có thể dựng lại từ runs đã lưu. Bước dựng graph không gọi LLM. Lượt gọi LLM trả lời câu hỏi chỉ chạy khi người dùng chủ động bấm chức năng QA hiện có.

Mục tiêu của B: so toàn bộ phương pháp cải tiến với trích xuất trực tiếp bằng cùng LLM. Muốn kết luận riêng lợi ích của một thành phần như retrieval, vẫn cần ablation giữ các thành phần còn lại giống nhau.

## 2. Quy tắc dựng graph

- Policy duy nhất phiên bản này: `surface-nfc-casefold-v1`. Khóa node dùng lại `shared.text_utils.normal`: Unicode NFC, strip/gộp khoảng trắng và casefold. Không bỏ dấu tiếng Việt, không tra catalog/aliases/redirects, không gộp bằng embedding/LLM. Node biểu diễn **surface form**, chưa bảo đảm một-một với thực thể ngoài đời.
- Cùng khóa trong corpus được chọn dùng chung node. ID là SHA-256 xác định theo project/policy/khóa. Nhãn gốc và các cách viết đã gặp được giữ trong `surface_forms`; không sinh loại/mô tả miền. Thứ tự runs được cố định theo ID để việc dựng lại không phụ thuộc thứ tự lựa chọn UI.
- Mỗi triple dựng được tạo một cạnh có ID theo project/run/ordinal. Predicate và chiều giữ nguyên; cạnh lặp và self-loop không bị xóa. Không gọi `ensure_node`, `ingest_extraction`, `clean_relation_name` hoặc schema preparation cho B.
- Triple thiếu subject/predicate/object dạng chuỗi không rỗng không thể tạo cạnh: giữ nguyên item và lý do trong diagnostics. Các lỗi khác, như evidence hỏng hoặc trường thừa, không tự làm mất cạnh có đủ S/P/O. Raw payload gốc vẫn còn trong runs.
- Evidence đối chiếu với `fitted_chunk_text` thực gửi; không khớp ghi false, không có đủ input/quote ghi null. Đây không phải đánh giá đúng/sai lịch sử. `chunk_start_char/end_char` là phạm vi chunk, không giả làm offsets chính xác của quote.
- Run lỗi vẫn có trong manifest/diagnostics nếu được chọn. Mỗi `(doc_id, chunk_number)` chỉ chọn một attempt; không tự chọn latest/best hoặc gom reruns làm tăng coverage. Hai chunk khác số nhưng cùng text/hash vẫn được giữ.
- Manifest lưu policy, run IDs, source hash, model/provider, prompt/request hashes, token counts, warnings, hash input thực gửi và tham số request. Toàn bộ request/raw response xem ở raw-run export hiện có.

## 3. Tổ chức và tái sử dụng

| Owner | Thay đổi |
| --- | --- |
| `shared/schemas/graph_input.py` | Contracts Pydantic v2 cục bộ, không đổi global extra policy; nodes/edges giữ unknown nested fields. Kiểm tra unique IDs/endpoints/relation và fingerprint. |
| Extraction application | `read_free_triples_runs` trả bản sao theo scope/run IDs dưới lock hiện có; không parse ngược file download, không chọn attempt thay người làm thí nghiệm. |
| Graph QA domain | `domain/baseline_graph.py` chứa thuật toán thuần, không I/O/gateway/UI. |
| Graph QA application | Dựng graph, chọn nguồn approved/all, import/export snapshot và điều phối independent benchmark. |
| Graph QA port + bootstrap | Inject public extraction service vào `BaselineRunSourcePort`; không cross-module internal import, không thêm facade business. |
| Graph core hiện có | Giữ PCST/PPR/Naive Top-K. Index dùng input snapshot tường minh; deepcopy input để cache không bị caller sửa qua tham chiếu. |
| Frontend | Một trang, một renderer node-ID và các tabs thuật toán chung. Bổ sung selector nguồn/runs, không tạo hệ thống UI song song. |

`normal`, `sha`, extraction lifecycle, prompt history, JSON repository/commit coordinator, CSV writer, Graphviz, QA/retrieval và các thuật toán đều được tái sử dụng. Bộ dựng graph không tái sử dụng nguyên `ensure_node` vì semantics khác. Không tạo mediator, event bus, generic repository hay module nghiệp vụ thứ bảy.

`g_retriever.py` vốn trên 500 dòng và chứa index/retrieval/compatibility helpers. Đợt này chỉ sửa đoạn chọn/cache input và nhận diện snapshot import; giữ các thuật toán và public registrations. Việc tách toàn bộ module lớn là refactor riêng để không trộn thay thuật toán với bổ sung baseline.

## 4. Đầu vào dùng chung và tương thích

- Format graph: `kg-studio.graph.v1`; gồm project/name/source, nodes, edges, manifest, diagnostics, fingerprint. JSON graph B có thể nạp lại bằng nguồn **Graph từ file**, rồi chạy cùng bộ thuật toán. Không giả status approved cho observations.
- Đường snapshot `source=approved` không fallback sang all khi graph rỗng. Baseline/all là lựa chọn tường minh. **Legacy API nhận project dict chưa gắn snapshot vẫn giữ fallback cũ** để không phá standalone consumers; không dùng đường đó cho nguồn thí nghiệm mới.
- Cache dựa vào project/source và nội dung nodes/edges thực tế, không dựa riêng số lượng/saved_at. UI QA/benchmark state gắn fingerprint graph. Kết quả benchmark bị invalidated khi gold hoặc budget đổi.
- Export raw runs `kg-studio.free-triples.v1` giữ nguyên hợp đồng. Nếu nạp nhầm raw runs vào graph loader, trả lỗi rõ ràng.
- Nguồn file ngoài không được kích hoạt ZIP/training/Neo4j của project đang mở, kể cả file tự mang source approved. Nguồn approved của project hiện tại vẫn giữ các chức năng legacy đó. Session graph ngoài `_p06_external_graph_*` cũ vẫn có đường đọc tương thích.
- Graph builder/source API là in-process read-only. Không thêm endpoint HTTP hoặc tự fallback từ remote mutation sang local.

## 5. Benchmark độc lập giữa các KG

Tab Benchmark có hai chế độ:

1. Không nạp gold: sinh câu hỏi từ graph để demo/so PCST–PPR–Naive trên **cùng graph**. Không dùng điểm này để tuyên bố chất lượng KG nào tốt hơn vì câu hỏi thay theo graph.
2. Nạp cùng JSON gold: dùng câu hỏi/facts do người chấm xác định từ nguồn, không dùng edge IDs của KG khác. Từng subject/predicate/object là một danh sách cách diễn đạt được người chấm chấp nhận cho **cùng một đối tượng/quan hệ**. Đây là variants, không phải danh sách nhiều facts khác nhau.

Ví dụ giả định tại [baseline-graph-gold-example.json](baseline-graph-gold-example.json). Không có khẳng định lịch sử thật trong fixture này. Bộ chấm chỉ so chuỗi qua `normal()` và variants đã cung cấp; không dùng LLM để tự quyết định tương đương ngữ nghĩa. Facts chồng lấn variants trong cùng câu hỏi bị từ chối để tránh đếm đôi. Hai cạnh trùng cho cùng fact chỉ được tính một hit; chiều S/P/O được giữ khi đối chiếu.

Metrics: macro trung bình theo câu hỏi của **gold-fact coverage trong graph** và **gold-fact retrieval recall** sau truy xuất. Fact không có trong graph là miss, không bị rút khỏi mẫu số. Mỗi method dùng cùng dataset và ngân sách; report JSON ghi dataset fingerprint, graph fingerprint/source, matching policy, budget và per-question results. Đây **không phải** extraction precision/F1, semantic truth evaluator hoặc chứng nhận chất lượng model.

Khi so A/B/C: đóng băng corpus/chunks/model/prompt/settings, công bố review/postprocessing policy, dùng cùng gold độc lập, giữ failures. Cùng raw chunk chưa bảo đảm fitted input giống nhau; đối chiếu hash/text thực gửi trong runs. Không dùng số node/cạnh làm proxy duy nhất cho coverage.

## 6. Cách sử dụng

1. Bước 2 chọn **B. Bộ ba tự do — baseline (không chuẩn hóa ngữ nghĩa)**; Bước 3 trích xuất như trước. Nút **Xem KG baseline ở Bước 5** đưa sang trang dùng chung; AppTest kiểm tra điều hướng này.
2. Bước 5 chọn **Baseline B — KG thô**, chọn run IDs tường minh, mỗi chunk một attempt. Lựa chọn mâu thuẫn báo lỗi, không hiển thị graph cũ hoặc đổi sang approved.
3. Xem graph trong tab bản đồ, tải JSON graph/manifest và CSV observations. Giới hạn hiển thị không cắt dữ liệu export. Raw runs vẫn tải ở Bước 3.
4. Tab hỏi đáp dùng chung PCST/PPR/Naive, gồm đối sánh ba phương pháp. Tab Benchmark nạp gold chung khi so nhiều KG; tải kết quả JSON đầy đủ để lưu điều kiện thí nghiệm.
5. Để chạy offline từ file, chọn **Graph từ file** và nạp JSON graph đã xuất. Trạng thái của project đang mở không bị thay đổi.

API chính qua `get_container().graph_qa_service`: `build_baseline_graph(project, {project_id, run_ids})`, `graph_snapshot(project, source="approved")`, `export_graph_json(snapshot)`, `import_graph_json(bytes)`, `retrieve_subgraph(snapshot.as_project(), query, ...)`, `evaluate_graph_benchmark(snapshot, items, max_edges=...)`.

## 7. Kiểm chứng và kết quả

Trước đợt: full offline suite **190 tests PASS, 4.855 giây**. Sau phần nối ban đầu: 212 tests PASS; đây là mốc trung gian, không thay kết quả nghiệm thu cuối.

```powershell
& '.\.venv-win\Scripts\python.exe' tools/run_isolated_tests.py tests.test_baseline_graph tests.test_baseline_graph_ui
& '.\.venv-win\Scripts\python.exe' tools/run_isolated_tests.py
```

24 tests mới đã PASS ở lần kiểm tra targeted gần nhất: normalization/Unicode, không dùng aliases/catalog, raw preservation/duplicates/self-loop, invalid items/evidence, scope/attempt selection, deterministic IDs/fingerprint, lossless JSON round-trip, dangling IDs, cache isolation, shared algorithms và independent benchmark không lệ thuộc IDs.

Bốn Streamlit AppTest flows chạy actual page: fake extraction → graph → compare three methods → benchmark/source switch; duplicate attempts báo lỗi; uploaded approved graph không xuất/train nhầm project; gold upload chạy cả ba thuật toán và invalidation khi gold thay đổi. Test xác nhận dựng graph/benchmark không gọi LLM bổ sung. Suite chạy trong bản sao tạm, chặn mạng ngoài, không dùng dữ liệu/secrets thật. Chưa gọi LLM/Neo4j thật hoặc đo chất lượng trích xuất trên corpus lịch sử.

**Nghiệm thu full source cuối:** Python 3.13.2, **214 tests PASS, 5.843 giây, exit code 0, không skip**, gồm architecture checks, toàn bộ tests cũ và 24 tests mới. Đã sửa/kiểm tra riêng trường hợp thiếu input thực gửi: ghi evidence unknown, không báo nhầm mismatch. Scoped diff-check các file sửa đạt; ghi chú whitespace ngoài phạm vi ở mục 9.

**Graphify:** đã chạy `C:\Users\thena\AppData\Local\Programs\Python\Python313\Scripts\graphify.exe update .`, exit code 0, AST-only không gọi LLM. Lần cuối sau chỉnh điều hướng: **2.463 nodes / 7.621 edges / 121 communities**; query sau build dùng để kiểm tra các contracts/builder mới có trong graph. CLI báo nhãn community cũ chưa đồng bộ và `pyproject.toml` không có symbols; không chạy relabel có gọi LLM hoặc sửa generated graph bằng tay.

## 8. Hiệu năng và tradeoff đã điều tra

Tool: `tools/benchmark_graph_input.py`, Python 3.13.2, cùng fixture tổng hợp 400 nodes / 800 edges, 41 warm samples. Hai phép đo trước/sau bật tracemalloc; after được chạy lại riêng, không chạy suite song song.

| Chỉ số | Trước | Sau |
| --- | ---: | ---: |
| Cold index, ms | 76.603 | 89.629 |
| Warm median, ms | 0.0029 | 7.0091 |
| Warm p95, ms | 0.0032 | 7.2698 |
| Peak memory, bytes | 2,458,854 | 2,679,795 |

Cold/warm latency tăng trên 10%; peak tăng khoảng 9%. Nguyên nhân đã xác định: khóa cũ chỉ đếm phần tử nên gần O(1) nhưng có thể trả nhầm index sau sửa nội dung/đổi KG; khóa mới serialize/hash nội dung O(V+E), đồng thời deepcopy lúc tạo index để tránh mutation qua tham chiếu. Chấp nhận tradeoff đúng đắn dữ liệu, không tuyên bố đây là tối ưu tốc độ. Bounded cache 8 entries được giữ. Snapshot route tránh chạy lại approved filtering.

Phép đo bổ sung **không bật tracemalloc**, chỉ áp dụng code sau thay đổi: cold 15.844 ms, warm p95 0.761 ms. Không so trực tiếp số không instrument với baseline có instrument và không ngoại suy sang corpus lớn. Muốn giảm thêm chi phí sau này cần boundary immutable/versioned đáng tin cậy; không dùng lại count-only key.

Raw measurements: [before](baseline-graph-perf-before.json), [after](baseline-graph-perf-after.json), [untraced](baseline-graph-perf-untraced.json).

## 9. Ledger phần thay thế và giới hạn còn lại

| Phần thay thế | Consumers đã kiểm tra / thay thế / kiểm chứng |
| --- | --- |
| Inline DOT dùng label làm ID tại `p05_graph_export.py` | Chuyển sang `components/graph_view.py`, node IDs tường minh; test labels giống nhau/escape, slider và full-page parity. Public `_build_subgraph_dot` alias giữ nguyên. |
| Nhánh upload graph cũ gắn vào phần approved | Source selector/file loader dùng chung; public loader và session external cũ vẫn hỗ trợ. AppTest ngăn dùng file ngoài để export/train project hiện tại. |
| Count/saved_at-only index cache key | Thay fingerprint nội dung và detached index input; test same-sized edit/source switch và immutable old cache. |
| Câu nhận xét benchmark mặc định khẳng định PCST vượt trội | Thay mô tả trung tính theo số đo; phân biệt demo graph-local và gold độc lập. |

Không xóa file source, data, snapshots, models, catalogs hoặc graphify-out; không nâng dependency, không nới architecture allowlist. Thay đổi sẵn có trong working tree được giữ. Global diff-check còn whitespace đã tồn tại tại `backend/domain/curation/merge_core.py:404`, không sửa phần ngoài phạm vi.

Giới hạn có chủ đích: exact surface identity vẫn có thể nhập nhầm hai thực thể trùng tên hoặc tách bí danh; nhiều cạnh/connected hơn chưa chứng minh nhiều fact đúng hơn. Gold phải do người chấm xây đúng phạm vi; matching tự động không suy luận tương đương ngữ nghĩa. Baseline graph không trở thành dữ liệu human-approved hoặc training gold chỉ vì dựng được.

Thiết kế đối chiếu việc tách Open KG/canonicalization trong [EDC, §4.1.1](https://aclanthology.org/2024.emnlp-main.548.pdf) và aggregation/resolution trong [KGGen, §4.2–4.3](https://proceedings.neurips.cc/paper_files/paper/2025/file/2b368455e832d2b1a60bcad8c4c6481f-Paper-Conference.pdf). Đây là implementation baseline của dự án, không tuyên bố tái lập đầy đủ các paper.
