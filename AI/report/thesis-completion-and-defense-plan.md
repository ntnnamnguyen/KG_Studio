# Khung hoàn thiện đồ án và chuẩn bị bảo vệ KG Studio

Ngày: **2026-11-15**. Trạng thái: kế hoạch đề xuất, chưa chạy thí nghiệm mới hoặc thay đổi source. Lịch mẫu: 4 tuần, cần điều chỉnh theo hạn nộp và rubric của khoa.

## 1. Kết luận và chiến lược ưu tiên

Source đã có nền tảng đủ rộng để làm một đồ án xây dựng và khai thác đồ thị tri thức tiếng Việt về địa danh lịch sử, kiến trúc và văn hóa: nhiều engine extraction, curation có bằng chứng, baseline KG, retrieval/benchmark, export và modules theo nghiệp vụ. **Việc có nhiều tính năng chưa chứng minh chất lượng khoa học hoặc điểm số.**

Ưu tiên tiếp theo là chuyển hệ thống thành một lập luận có thể kiểm chứng: vấn đề cụ thể → phương pháp → đóng góp của sinh viên → so sánh công bằng → kết quả có giới hạn → demo tái lập.

Chưa có tên đề tài chính thức, rubric, thời hạn và yêu cầu của giảng viên. Không gán trọng số chấm điểm, không dự đoán hoặc bảo đảm mức điểm. Trọng số thời gian ở mục 10 chỉ là đề xuất quản lý công việc.

Thứ tự ưu tiên:

1. Chốt bài toán và đóng góp có thể chứng minh.
2. Chuẩn hóa corpus, gold và protocol đánh giá.
3. Hoàn thành thí nghiệm chính, phân tích lỗi và chi phí.
4. Khắc phục lỗi làm sai kết quả/mất dữ liệu và đóng gói demo.
5. Viết báo cáo, slides và luyện phản biện.
6. Chỉ bổ sung tính năng khi trực tiếp giải quyết khoảng trống của câu hỏi nghiên cứu.

## 2. Cơ sở đánh giá hiện trạng

Đã xem working tree trên HEAD `4c2a403`, có thay đổi chưa commit ở curation, graph/export, state, config và tests. Không reset hay chỉnh những thay đổi đó.

Graphify query không chạy được trong PATH; đã dùng graph JSON có phạm vi rồi đối chiếu source. Đã đọc báo cáo retirement, báo cáo corpus, benchmark implementation và các điểm lock/save liên quan. **Không chạy lại full test suite trong lượt lập kế hoạch này**; số PASS trong báo cáo 13/11 là kết quả lịch sử.

| Tài sản hiện có | Giá trị cho đồ án | Việc phải xác minh trước đưa vào báo cáo |
| --- | --- | --- |
| 4 registrations: closed, edc, edc_plus_r, free_triples | Có nền để so sánh phương pháp xây dựng KG | Mô tả đúng các bước mỗi engine thực thi; tên EDC không tự chứng minh tái lập đầy đủ bài báo |
| Baseline B và GraphSnapshotDTO | Cùng interface cho graph thô và graph xử lý | Không semantic-normalize baseline; cùng corpus/input/attempt selection |
| Curation, evidence, aliases/merge | Giá trị ứng dụng trong miền tư liệu lịch sử | Đo công sức và tác động; tách kết quả tự động khỏi kết quả có người sửa |
| graph_benchmark.py | Gold-fact coverage và retrieval recall theo câu hỏi, fingerprints | Không gọi các chỉ số này là extraction precision/F1 hoặc answer accuracy |
| Modular Monolith, coordinator, tests | Bằng chứng kỹ thuật và khả năng bảo trì | Lock công khai đã có, nhưng source extraction vẫn có `_save_project_safe` gọi store trực tiếp; không nói mọi ghi đã qua `commit()` |
| Báo cáo corpus ngày 12/11 | Có tập dữ liệu ứng dụng và số liệu mô tả khởi đầu | Phải tái sinh số liệu từ snapshot xác định, sửa bất nhất bên dưới |

### Các số liệu cần đối soát ngay

Trong [thesis_empirical_metrics.md](thesis_empirical_metrics.md): 40 tài liệu, 94.542 “từ”, 3.177 nodes, 3.619 edges và 70 runs EDC là **số liệu báo cáo cũ, chưa được tái kiểm chứng**. Có các điểm sau:

- Số đoạn là 0 nhưng có runs: xác định field/định nghĩa count đang dùng, không kết luận dữ liệu thực sự không có đoạn.
- Summary ghi approved 3.616 nhưng bảng trạng thái ghi 3.619: phân biệt trạng thái duyệt, eligibility xuất và scope snapshot nếu đó là nguyên nhân; nếu không, sửa phép thống kê.
- “Tokens/Words” không phải một đơn vị: tách số từ theo tokenizer/quy tắc đếm và số token do provider báo.
- “Evidence grounded 96,46%” cần định nghĩa: có chuỗi trích dẫn, quote khớp source hay evidence thực sự hỗ trợ fact? Chỉ kiểm tra tồn tại chuỗi không chứng minh entailment.
- Average degree/density phải chỉ rõ graph có hướng/không hướng, đa cạnh/self-loop và phép chiếu dùng khi tính; không đặt số của hai loại graph cạnh nhau như cùng định nghĩa.
- Loại “mốc thời gian” và “moc_thoi_gian” cùng xuất hiện là dấu hiệu cần phân tích chuẩn hóa, không được tự xóa/gộp để làm đẹp số liệu.
- 70 runs đều được ghi là EDC: thống kê này chưa phải bằng chứng đối sánh A/B/C.

## 3. Khung đề tài và đóng góp

### Định vị đề xuất

Tên làm việc, cần khớp tên đã được khoa duyệt:

> Xây dựng và đánh giá hệ thống đồ thị tri thức từ tư liệu tiếng Việt về địa danh lịch sử và di sản kiến trúc–văn hóa.

Phạm vi nên giới hạn vào một địa bàn/corpus cụ thể, ví dụ Hà Nội nếu đúng dữ liệu đã chọn. Không khẳng định hệ thống bao phủ mọi di sản Việt Nam từ corpus nhỏ.

### Ba đóng góp có thể bảo vệ

1. **Dữ liệu và phương pháp đánh giá:** corpus có provenance, gold có hướng dẫn chấm cho miền di sản, so sánh extraction/normalization bằng cùng protocol.
2. **Thiết kế pipeline thích nghi theo miền:** kết hợp extraction, schema và human review có evidence; đo tác động từng bước. Gọi là đóng góp thiết kế/ứng dụng nếu không có thuật toán mới.
3. **Hệ thống tái lập:** nhiều nguồn graph dùng chung interface, kiểm soát phiên bản/chạy thử/export và minh bạch kết quả.

EDC, PPR, PCST và LLM là kỹ thuật kế thừa; phải trích dẫn và chỉ rõ phần em triển khai/điều chỉnh. Không gọi wrapper hoặc tên module mới là thuật toán mới. Nếu có phần sáng tạo riêng, mô tả input/output, pseudocode và phép ablation kiểm chứng nó.

### Câu hỏi nghiên cứu

| ID | Câu hỏi | Bằng chứng cần có |
| --- | --- | --- |
| RQ1, chính | Schema cố định, trích xuất tự do và xử lý mở–chuẩn hóa khác nhau thế nào về chất lượng facts và độ bao phủ? | A/B/C, gold từ source, đánh giá automated stage, sai số và chi phí |
| RQ2, chính | Thành phần chuẩn hóa/retrieval/curation nào đem lại lợi ích và đánh đổi gì? | Ablation một thành phần mỗi lần; trước/sau review và thời gian người chấm |
| RQ3, phụ | KG tạo ra hỗ trợ tìm bằng chứng cho câu hỏi miền di sản ra sao? | Gold QA độc lập, cùng retrieval budget; phân biệt coverage graph và retrieval recall |

Nếu thời gian ngắn, hoàn thiện RQ1 và một phần RQ2. RQ3 chỉ là minh họa có giới hạn nếu chưa có gold độc lập. Không biến extraction, entity resolution, training, RAG và UI thành năm đề tài đồng thời.

## 4. Protocol dữ liệu và chấm thủ công

### Corpus manifest

Mỗi tài liệu cần ID, nguồn/URL hoặc thư mục lưu trữ, đơn vị/tác giả nếu có, ngày truy cập, chủ đề/địa bàn, version/hash, cách bóc tách và quyền sử dụng/chia sẻ phù hợp. Phân biệt nguồn chính thức, khảo cứu, du lịch, truyền thuyết; không gán độ tin cậy chỉ theo cảm tính của LLM.

Trong miền lịch sử, “nguồn nói X” khác “X là sự thật đã được xác minh”. Giữ qualifier về thời gian, truyền thuyết, phủ định và nguồn mâu thuẫn trong annotation/analysis theo khả năng biểu diễn hiện tại. Nếu schema không biểu diễn được, ghi limitation, không nâng cấp mô hình dữ liệu sát ngày bảo vệ.

### Phân chia và chống leakage

- Chia development/test theo tài liệu hoặc cụm di tích/nguồn trùng, không random các đoạn overlap sang hai tập.
- Dùng development để chỉnh prompt, schema, ngưỡng, từ điển và hướng dẫn chấm. Khóa tất cả trước test.
- Nếu đã xem/dùng cả 40 tài liệu để chỉnh hệ thống, không gọi một phần đó là test hoàn toàn chưa thấy. Tạo holdout mới nếu khả thi hoặc công bố đánh giá retrospective cùng giới hạn leakage.
- Không lấy dữ liệu đã curation toàn corpus rồi dùng làm gazetteer hỗ trợ test mà không công bố. Không train trên test/gold QA.

### Gold hai loại, không dùng lẫn

1. **Gold extraction:** annotator đọc source trước, ghi facts thuộc scope, entity mentions, predicate, evidence span và qualifiers cần thiết. Cố gắng liệt kê đầy đủ facts trong các đoạn đã chọn. Gold chỉ gồm output pooled từ các hệ thống sẽ dễ bỏ sót facts mà tất cả đều không trích xuất.
2. **Gold QA:** câu hỏi, answer tham chiếu nếu đánh giá câu trả lời, tập supporting facts và evidence. Được xây từ nguồn độc lập với graph của một phương pháp cụ thể, có câu hỏi không đủ bằng chứng.

Khởi điểm ước lượng công sức, không phải ngưỡng thống kê: pilot 10–20 đoạn để sửa guideline; bộ đánh giá chính khoảng 80–150 đoạn từ tối thiểu 10–15 tài liệu/cụm, số facts phát sinh theo dữ liệu. QA phụ khoảng 40–60 câu cân đối 1-hop/2-hop/tổng hợp/không đủ thông tin. Nếu không đủ nguồn lực, giảm scope và chấm đầy đủ tập nhỏ hơn; không giả lập quy mô hoặc độ tin cậy.

Ít nhất 20–30% mẫu nên được hai người chấm độc lập, che tên phương pháp khi chấm outputs; giải quyết bất đồng và giữ nhãn ban đầu. Đo agreement phù hợp loại nhãn: categorical agreement/kappa chỉ dùng trên tập đơn vị quyết định cố định; facts tự do cần matching và báo bất đồng coverage/mapping, không tính kappa tùy tiện trên hai danh sách facts khác nhau. Một người chấm thì công bố giới hạn, nhờ người thứ hai kiểm tra một phần nếu có thể.

## 5. Thí nghiệm công bằng và chỉ số

### So sánh xây dựng KG

| Nhánh | Nội dung | Điều kiện |
| --- | --- | --- |
| B | LLM extraction tự do → KG thô bằng chuẩn hóa kỹ thuật tối thiểu | Không EDC definitions/schema alignment/semantic ER; giữ artifacts và errors |
| A | Extraction với schema cố định | Schema được chốt từ development; không bổ sung theo test |
| C | Pipeline mở rồi chuẩn hóa theo implementation thực tế | Ghi đủ bước, prompt, model, thresholds và policy mapping |
| C+R, tùy chọn | C thêm schema retrieval hoặc một thành phần đã có | Chỉ đưa vào nếu có thể cô lập và đo chi phí/lợi ích |

Cùng corpus, chunks thực sự gửi, model/version và ngân sách theo chính sách đã công bố; lưu prompt/hash/tokens/latency/error attempts. Prompt khác theo phương pháp là hợp lý, phải lưu; không nói mọi prompt giống nhau. Nếu input bị cắt khác nhau vì schema chiếm context, ghi mức coverage thực tế. So cùng điều kiện nguồn lực và báo tổng chi phí, không che việc C dùng nhiều lượt gọi.

Đánh giá tự động **trước human curation** cho mọi nhánh. Kết quả sau curation là thí nghiệm riêng có số phút/decisions; không so B thô với C đã được người sửa rồi quy toàn bộ cải thiện cho thuật toán.

Nếu C có thể nhận lại cùng output extraction ban đầu, dùng nó để ablate chuẩn hóa. Nếu engine C thay cả prompt/extraction, A/B/C là so sánh pipeline, không đủ để quy nhân quả cho riêng bước canonicalization.

### Chỉ số chính

- Precision facts = TP / (TP + FP), recall facts = TP / (TP + FN), F1 từ P/R. Định nghĩa scope và TP trước khi chạy test; matching một-một để một gold fact không bị nhiều predictions đếm thành nhiều TP. Quy định các trường hợp tập rỗng.
- Báo cả độ đúng theo nội dung nguồn và schema conformance riêng. Facts đúng nhưng ngoài schema được đánh giá theo scope khai báo; không mặc định là hallucination.
- Dedupe theo policy chấm độc lập, không sửa artifacts baseline. Báo duplicates riêng; có thể thêm observation-level precision để thấy đầu ra lặp.
- Surface exact match và semantic/accepted-variant matching là hai phép đo khác nhau. Bảng mapping chấm dùng chung cho mọi hệ thống, không dựa riêng vào từ điển của C. Khóa guideline; trường hợp mới được adjudicate mù và áp dụng nhất quán, lưu phiên bản.
- Grounding: tỷ lệ facts có evidence hợp lệ và evidence hỗ trợ phát biểu; tách quote tồn tại, span khớp và nội dung được hỗ trợ.
- Chi phí: tokens, số calls/retries/failures, latency và chi phí tiền nếu có giá xác định tại ngày chạy; thống kê cả runs thất bại.
- QA: graph fact coverage, supporting-fact recall@budget; nếu đánh giá answer thì có rubric correctness/faithfulness/abstention riêng. Source graph_benchmark hiện tại chưa đo answer accuracy hoặc extraction F1.

Số nodes/edges, density, tỷ lệ approved là thống kê mô tả; không chứng minh chất lượng cao hơn. Ít node hơn có thể do gộp đúng hoặc gộp nhầm; nhiều edge hơn có thể do coverage tốt hoặc hallucination/duplicates.

### Sai số và ablation

Chọn một metric chính và phép so sánh chính trước khi xem test. Báo chênh lệch, counts, phân bố theo tài liệu và khoảng tin cậy khi đủ dữ liệu. Paired bootstrap theo tài liệu/cụm giúp tránh coi các facts cùng đoạn là quan sát độc lập; ghi đơn vị resampling và giới hạn mẫu nhỏ. Nếu lặp LLM nhiều lần, phân biệt biến thiên theo run với biến thiên theo corpus; 3 runs có thể là mô tả độ dao động, không bảo đảm ý nghĩa thống kê.

Ưu tiên một ablation có giá trị: C bỏ bước chuẩn hóa hoặc C bỏ retrieval; nếu không hỗ trợ clean ablation, không vội thêm engine mới. Human review trước/sau cùng output là ablation ứng dụng riêng với thời gian người dùng.

## 6. Các bảng/hình tối thiểu phải có

1. Bảng corpus và split: nguồn, tài liệu/cụm, đoạn, facts, QA và scope.
2. Bảng cấu hình A/B/C: model, prompt/version, input policy, số calls, normalize policy và người can thiệp.
3. Bảng kết quả extraction: P/R/F1, grounding, invalid/duplicate rate, counts và uncertainty.
4. Bảng chi phí/latency và ablation; không chỉ highlight metric có lợi.
5. Bảng QA nếu làm RQ3; ghi rõ graph/input/budget cố định ở phép so nào.
6. Phân tích 15–20 ca lỗi đại diện: thiếu fact, hallucination, predicate quá chung, alias fragmentation, homonym overmerge, thời gian/nguồn mâu thuẫn; có cả ca phương pháp đề xuất thua.
7. Hình pipeline, diagram modules/dependency, sơ đồ dữ liệu authoritative/derived, một graph con dễ đọc và evidence panel.

Mọi số liệu truy ngược được tới experiment manifest/run IDs/snapshot hash. Không sửa tay bảng để khớp nhận định; script sinh bảng và báo cáo số liệu phải dùng cùng snapshot.

## 7. Khung báo cáo tốt nghiệp

Tuân thủ template của khoa nếu khác cấu trúc này.

| Chương | Câu hỏi phải trả lời | Nội dung cần có |
| --- | --- | --- |
| 1. Bài toán và mục tiêu | Vì sao cần hệ thống, ai dùng, phạm vi gì? | Nhu cầu miền di sản, bài toán, RQs, scope, đóng góp và tiêu chí thành công |
| 2. Cơ sở và liên quan | Đã có gì, đề tài kế thừa và khác ở đâu? | KG/schema/open extraction, EDC, canonicalization, evidence, retrieval; bảng so sánh với nguồn gốc |
| 3. Phương pháp và dữ liệu | Em làm gì và vì sao? | Corpus/split/gold protocol, A/B/C, pipeline thực tế, baseline và fairness |
| 4. Thiết kế và triển khai | Hệ thống thực hiện và bảo toàn dữ liệu thế nào? | Modular Monolith, public APIs/ports, JSON/projection, commit, provenance, UI workflow, tests |
| 5. Thực nghiệm và thảo luận | Có hiệu quả không, giá phải trả là gì? | Config, metrics, tables/CI, ablation, error analysis, limitations và threats to validity |
| 6. Kết luận | RQs được trả lời tới đâu? | Đóng góp đã chứng minh, hạn chế chưa giải quyết và hướng tiếp theo |

Phụ lục: annotation guideline, schema/prompt versions, APIs/export formats cần thiết, test/run instructions, manifests và ví dụ lỗi. Không đưa hàng chục trang source vào phần chính thay cho giải thích thiết kế.

Phân biệt đóng góp cá nhân với thư viện/paper/công cụ hỗ trợ. Nếu dùng AI hỗ trợ lập trình/viết, khai báo theo quy định của trường và chịu trách nhiệm giải thích code, thí nghiệm và trích dẫn.

## 8. Mốc công việc và đầu ra nghiệm thu

| Mốc | Công việc | Đầu ra | Điều kiện đạt |
| --- | --- | --- | --- |
| T0 | Chốt rubric, tên đề tài, scope, RQs và feature freeze | thesis-brief + bảng criterion→evidence | Giảng viên thống nhất scope; không còn mâu thuẫn mục tiêu |
| T1 | Audit dữ liệu/metrics, chốt split và guideline | corpus manifest, metric dictionary, pilot gold | Số liệu nhất quán; định nghĩa rõ; phát hiện leakage được xử lý/công bố |
| T2 | Hoàn thiện gold và protocol | Gold extraction/QA có version, annotator logs, experiment manifest | Chấm trước khi xem kết quả test; protocol/metric chính đóng băng |
| T3 | Chạy A/B/C và ablation trong ngân sách | Raw outputs, snapshots, metrics, cost/error logs | Cùng điều kiện được công bố; không bỏ runs xấu/chọn best test run |
| T4 | Phân tích và viết kết quả | Tables/figures tái sinh, error analysis, limitations | Kết luận trả lời RQs, không vượt evidence; kết quả âm vẫn được báo |
| T5 | Release và demo | Test log mới, environment/setup guide, frozen demo project, video dự phòng | Cài/chạy trên môi trường thử; demo thành công không phụ thuộc dịch vụ live |
| T6 | Chốt báo cáo/slides và diễn tập | Bản nộp, slides, câu trả lời phản biện | Mỗi claim có evidence; đúng thời lượng; giải thích được đoạn code trọng yếu |

Các artifacts là đầu ra dự kiến, chưa được tạo trong lượt này ngoài bản kế hoạch. Không đợi source hoàn hảo mới bắt đầu T1/T2; lỗi ảnh hưởng correctness của experiments phải sửa trước T3. T5 không yêu cầu xóa mọi shim legacy còn chức năng.

## 9. Demo và bảo vệ

Demo chính 5–7 phút, điều chỉnh theo thời lượng khoa:

1. Một tài liệu và một câu hỏi nghiệp vụ dễ hiểu.
2. Một kết quả extraction có evidence; chỉ ra vì sao máy có thể sai.
3. Review một lỗi cụ thể và cho thấy provenance còn nguyên sau sửa.
4. Khám phá graph con/hỏi đáp với nguồn hỗ trợ.
5. Mở bảng đối sánh trên tập test đã khóa và giải thích một tradeoff.

Chuẩn bị bản dữ liệu demo riêng, chạy trên bản sao; không thao tác nguy hiểm trên corpus dùng chấm. Có video và outputs lưu trước được ghi rõ là kết quả chạy đã lưu, không giả làm live. Có một ca thiếu bằng chứng/lỗi xử lý tốt. Không phụ thuộc Wi-Fi, quota LLM hoặc Neo4j live để hoàn thành demo chính.

Slides khoảng 10–12 trang nếu thời lượng cho phép: bài toán → RQs/đóng góp → related work/gap → corpus/gold → pipeline → thiết kế → thực nghiệm → ablation/chi phí → lỗi/giới hạn → demo → kết luận.

### Các câu phản biện phải chuẩn bị

- Nếu chỉ gọi LLM thì đóng góp của em là gì? Trả lời bằng thiết kế miền, gold/protocol, pipeline và tác động đo được; không dùng LOC làm bằng chứng.
- Vì sao chọn schema hoặc mở? Dùng tradeoff P/R/coverage/normalization/cost từ A/B/C, không khẳng định một cách luôn tốt nhất.
- Baseline có công bằng không? Nêu minimal graph assembly, cùng input/model và không thêm semantic alignment.
- C tốt hơn vì người duyệt hay thuật toán? Cho bảng pre/post human review và chi phí riêng.
- “Đã duyệt” có chắc đúng lịch sử không? Nêu phạm vi fact theo nguồn, chất lượng nguồn, người chấm và giới hạn.
- Có phải tái lập đầy đủ EDC/HippoRAG/G-Retriever không? Đối chiếu từng thành phần thực thi; nếu chỉ dùng PPR/PCST hoặc ý tưởng, gọi đúng tên và giới hạn.
- Vì sao Modular Monolith? Tính nhất quán workflow, triển khai local và ownership; không cần network/microservices cho quy mô chưa chứng minh cần.
- Khi dữ liệu/multiuser tăng thì sao? Nêu giới hạn bộ nhớ/JSON/projection/RLock; chỉ hứa điều có test.
- Chênh lệch nhỏ có đáng tin không? Nêu counts, uncertainty, sample dependence và kết quả không đủ kết luận nếu cần.

## 10. Lịch mẫu và cách cắt scope

**4 tuần:** tuần 1 T0–T1 + pilot/gold; tuần 2 T2–T3, viết chương 1–4 song song; tuần 3 T3–T4 và đóng lỗi correctness; tuần 4 T5–T6, freeze source và rehearsal. Tránh dành cả tuần cuối refactor.

**Nếu chỉ còn 2 tuần:** giữ A/B/C nhỏ nhưng gold độc lập và phân tích đầy đủ; QA chỉ minh họa hoặc một test nhỏ được công bố; bỏ training mới, mở rộng schema và component graph mới. Chốt bản chạy ổn định sớm, vẫn dành ít nhất vài ngày cho báo cáo/demo.

**Nếu còn dưới 1 tuần:** ưu tiên sửa số liệu, scope/claims trung thực, test/release/demo và luyện bảo vệ. Không ngụy tạo thí nghiệm quy mô lớn; báo đúng pilot, không thay architecture rộng.

Phân bổ công sức gợi ý khi đã có source hiện tại: 40% dữ liệu/gold/thực nghiệm, 25% báo cáo và lập luận, 20% ổn định/tái lập/demo, 15% slides và phản biện. **Đây không phải trọng số chấm điểm của khoa.** Điều chỉnh ngay khi có rubric.

### Không làm thêm chỉ để tăng số tính năng

- Không fine-tune nếu thiếu train/dev/test và giả thuyết cụ thể.
- Không viết thêm engine chỉ để tăng số dòng trong bảng so sánh.
- Không rewrite frontend/microservices hoặc dọn hết legacy sát hạn.
- Không đánh đổi reproducibility để có một demo live ấn tượng nhưng dễ lỗi.

## 11. Checklist bản nộp cuối

- [ ] Tên đề tài, mục tiêu, contributions và kết luận thống nhất.
- [ ] Corpus/gold có scope, provenance, split và annotation guideline.
- [ ] Thống kê approved/chunks/tokens/density không mâu thuẫn; nêu định nghĩa.
- [ ] A/B/C trước human review, cùng điều kiện công bố; không leakage không khai báo.
- [ ] Metric không bị gọi sai: extraction khác retrieval khác QA; counts/chi phí/errors đầy đủ.
- [ ] Mỗi bảng/hình tái sinh được từ snapshot/run manifest.
- [ ] Có ablation hoặc giải thích rõ vì sao chỉ so pipeline; có failure cases.
- [ ] Test hiện tại và environment được ghi, không dùng PASS lịch sử.
- [ ] README chạy bằng venv của KG Studio; sửa hướng dẫn còn trỏ KG_Studio_MVP nếu không đúng triển khai độc lập.
- [ ] Demo offline/recorded fallback được đánh dấu trung thực; không chứa secrets.
- [ ] Báo cáo/slides trích dẫn nguồn, phân biệt phần kế thừa và phần sinh viên làm.
- [ ] Các claim “100% hoàn thành”, “production-ready”, “an toàn đa tiến trình” được bỏ hoặc có evidence đúng phạm vi.

## 12. Cơ sở tham khảo

- [Zhang & Soh, EDC, EMNLP 2024](https://aclanthology.org/2024.emnlp-main.548/): cơ sở cho extraction mở, definition và canonicalization; không suy từ tên engine rằng dự án đã tái lập toàn bộ framework.
- [Dror et al., ACL 2018 — Testing Statistical Significance in NLP](https://aclanthology.org/P18-1128/): chọn kiểm định theo task, metric và thiết kế thực nghiệm, không dùng một phép kiểm định cho mọi bảng.
- [Bestgen, LREC 2022 — Difference and Confidence Interval](https://aclanthology.org/2022.lrec-1.640/): báo chênh lệch và khoảng tin cậy khi so hệ thống; không kết luận vượt trội chỉ từ điểm trung bình.

Đây là tham khảo phương pháp nghiên cứu, không phải quy chế chấm điểm của trường. Rubric chính thức và hướng dẫn của giảng viên cần được ghép vào T0 trước khi chốt lịch.
