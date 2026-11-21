# BẢN THẢO BÁO CÁO CÁ NHÂN ĐỒ ÁN TỐT NGHIỆP

**Sinh viên:** Nguyễn Thế Nam — **Mã số sinh viên:** 0217666.

**Đề tài nhóm theo bìa PDF cũ:** Ứng dụng G-Retriever vào xây dựng đồ thị tri thức để hỏi đáp cho địa danh du lịch Hà Nội.

**Nội dung cá nhân:** Xây dựng và đánh giá quy trình trích xuất, chuẩn hóa và kiểm duyệt đồ thị tri thức địa danh Hà Nội trên KG Studio.

**Trạng thái biên tập, 21/11/2026:** Bản thảo nội dung để chuyển sang mẫu Word của trường. Chương 1–4 đã được viết lại theo cơ chế source đã đối chiếu. Chương 5 phân biệt số liệu lịch sử và benchmark khảo sát, chưa được coi là chương số liệu đã chốt để nộp. Các việc cần xác nhận được đặt trong [sổ bằng chứng riêng](so-bang-chung-va-ke-hoach-chot-bao-cao-2026-11-21.md), không phải nội dung đưa nguyên vào bản nộp. Bản này không thay đổi tên đề tài đã được duyệt của nhóm.

## Tóm tắt

Đồ thị tri thức là một cách tổ chức thông tin về địa danh, nhân vật và sự kiện để hỗ trợ tra cứu có cấu trúc. Tuy nhiên, dữ liệu lịch sử và văn hóa Hà Nội phần lớn tồn tại dưới dạng văn bản tiếng Việt. Khi dùng mô hình ngôn ngữ lớn để chuyển văn bản thành bộ ba, kết quả có thể chứa nhiều cách diễn đạt cho cùng một quan hệ, tên thực thể nhập nhằng và trích dẫn chưa phù hợp.

Trong phạm vi công việc cá nhân, đồ án triển khai và điều chỉnh quy trình Extract–Define–Canonicalize có truy xuất lược đồ trên KG Studio. Trước khi gọi mô hình ngôn ngữ, hệ thống chọn các quan hệ và loại thực thể liên quan từ danh mục miền để bổ sung vào ngữ cảnh. Sau trích xuất, các nhãn mở được xếp hạng với danh mục chuẩn nhằm hỗ trợ căn chỉnh. Người sử dụng tiếp tục kiểm tra nhãn, hợp nhất thực thể và rà soát bằng chứng trước khi xuất đồ thị đã duyệt.

Hệ thống lưu thông tin nguồn của cạnh, văn bản đầu vào và dấu vết lần chạy, đồng thời tổ chức thao tác kiểm duyệt theo cơ chế xem trước và áp dụng có kiểm soát. Phần đánh giá sử dụng dữ liệu 50 tài liệu địa danh Hà Nội để khảo sát mức hội tụ lược đồ, đặc trưng cấu trúc đồ thị, lượng token và chất lượng truy xuất schema. Hai bộ mã hóa được đối chiếu là hybrid_vn và BGE-M3. Các kết quả được diễn giải trong phạm vi dữ liệu quan sát; độ chính xác nội dung của toàn bộ bộ ba chưa được xác lập bằng một tập nhãn độc lập hoàn chỉnh.

**Từ khóa:** đồ thị tri thức, trích xuất thông tin, EDC, Schema Retrieval, kiểm duyệt, nguồn gốc dữ liệu.

# CHƯƠNG 1. BÀI TOÁN VÀ MỤC TIÊU

## 1.1. Bối cảnh

Tư liệu về các địa danh Hà Nội chứa thông tin về vị trí, niên đại, công trình, nhân vật và các lần thay đổi qua lịch sử. Người đọc có thể tìm thấy những thông tin này trong một bài viết, nhưng việc đối chiếu giữa nhiều địa danh hoặc nhiều nguồn vẫn đòi hỏi đọc thủ công. Đồ thị tri thức biểu diễn thông tin dưới dạng các thực thể và quan hệ, từ đó hỗ trợ tìm kiếm, thống kê và cung cấp dữ liệu cho hệ thống hỏi đáp.

Mô hình ngôn ngữ lớn có thể nhận văn bản và sinh ra các bộ ba. Tuy nhiên, một kết quả có cấu trúc chưa đủ để trở thành dữ liệu sử dụng được. Hệ thống còn phải xác định cách đặt nhãn, phạm vi định danh của thực thể và nguồn bằng chứng cho từng phát biểu. Trong miền lịch sử, các yêu cầu này đặc biệt quan trọng vì tên gọi, thời gian và mức độ chắc chắn của thông tin có thể thay đổi theo ngữ cảnh.

## 1.2. Những vấn đề cần giải quyết

Thứ nhất, cùng một quan hệ có thể được diễn đạt bằng nhiều vị từ. Chẳng hạn “nằm tại” và “tọa lạc tại” có thể mang cùng ý nghĩa trong một ngữ cảnh vị trí. Nếu giữ mọi cách diễn đạt làm nhãn riêng, việc thống kê và truy vấn trở nên khó khăn. Ngược lại, gộp mọi nhãn gần nghĩa có thể làm mất những khác biệt cần thiết như xây dựng, trùng tu và phục dựng.

Thứ hai, cùng tên chưa chắc cùng đối tượng. Một từ như “cổng” hoặc “chuông” có thể xuất hiện trong nhiều di tích. Nếu định danh chỉ bằng tên trên toàn dự án, những bộ phận khác nhau có thể bị nối nhầm. Hệ thống cần giữ ngữ cảnh tài liệu và cho phép người dùng kiểm tra trước khi hợp nhất.

Thứ ba, số lượng nhãn trong danh mục tạo ra đánh đổi giữa độ bao phủ và độ dài prompt. Danh sách quá ngắn có thể bỏ sót schema cần dùng, trong khi danh sách dài làm tăng token và đưa thêm mục không liên quan. Schema Retrieval được sử dụng để chọn một tập ứng viên theo nội dung từng đoạn.

Thứ tư, các quan hệ do LLM sinh ra cần được kiểm tra bằng nguồn văn bản. Trích dẫn tồn tại trong tài liệu là một điều kiện hữu ích, nhưng chưa chứng minh bộ ba diễn giải đúng câu đó. Vì vậy đồ án tổ chức thêm bước kiểm duyệt và lưu lịch sử quyết định.

## 1.3. Mục tiêu

Mục tiêu của phần công việc cá nhân là xây dựng một quy trình có thể sử dụng để tạo, chuẩn hóa và kiểm tra KG tiếng Việt phục vụ hỏi đáp địa danh. Các mục tiêu cụ thể gồm:

1. Tích hợp extraction có gợi ý lược đồ, đồng thời giữ khả năng đề xuất nhãn mới.
2. Cung cấp công cụ căn chỉnh nhãn, hợp nhất thực thể và xử lý cạnh nghi trùng.
3. Gắn dữ kiện với bằng chứng, tài liệu và lần chạy để hỗ trợ kiểm tra lại.
4. So sánh các lựa chọn embedding bằng phép đo chất lượng truy xuất và độ trễ.

## 1.4. Phạm vi và phân công

Trong hệ thống hỏi đáp của nhóm, KG Studio đảm nhiệm giai đoạn xây dựng dữ liệu KG. Báo cáo cá nhân tập trung vào giai đoạn này; không dùng kết quả truy xuất schema để thay thế đánh giá chất lượng trả lời của toàn bộ hệ thống G-Retriever.

Theo phân công được mô tả trong PDF cũ, văn bản và danh mục miền được Nguyễn Trường Giang cung cấp. Phần công việc của sinh viên là triển khai luồng trích xuất, chuẩn hóa, công cụ kiểm duyệt và thực hiện đánh giá. Danh mục có tham chiếu CIDOC CRM nhưng có các nhãn ứng dụng riêng; mức tương thích với bản thể gốc cần được diễn giải theo mapping thực tế.

Đồ án kế thừa EDC và Schema Retrieval từ công trình trước [1]. Việc tích hợp chúng vào KG Studio được xem là đóng góp xây dựng và điều chỉnh hệ thống, không phải đề xuất mới toàn bộ khung thuật toán.

## 1.5. Câu hỏi đánh giá

- RQ1: Các cấu hình extraction tạo ra kết quả khác nhau như thế nào về số nhãn, token và cấu trúc KG?
- RQ2: hybrid_vn và BGE-M3 khác nhau ra sao về khả năng đưa nhãn phù hợp vào Top-K và độ trễ?
- RQ3: Quy trình kiểm duyệt hỗ trợ xử lý nhãn, thực thể, cạnh và kiểm tra bằng chứng như thế nào?

Cơ chế tái sử dụng dữ liệu duyệt để điều chỉnh retriever được trình bày như một khả năng đã có implementation; kết luận về hiệu quả học cần phép đo độc lập với chính dữ liệu train.

# CHƯƠNG 2. CƠ SỞ KỸ THUẬT

## 2.1. Đồ thị tri thức và lược đồ

Một bộ ba có dạng t=(s,r,o), trong đó s và o là thực thể nguồn, đích, còn r là quan hệ. Trong KG Studio, thực thể có ID, tên, loại và thông tin bổ sung; cạnh có ID, hai đầu mút, nhãn quan hệ, trích dẫn và trạng thái duyệt. ID giúp lựa chọn ổn định ngay cả khi tên hiển thị thay đổi.

Danh mục schema quy định các loại thực thể và quan hệ được sử dụng trong phạm vi dự án. Mỗi mục có thể kèm định nghĩa, mô tả, aliases và domain/range. Các nhãn kỹ thuật như BUILT_IN là nhãn miền ứng dụng; cần mapping riêng trước khi nhận là một thuộc tính chính thức của CIDOC CRM [3].

## 2.2. EDC và thành phần truy xuất schema

Khung EDC gồm extraction mở, định nghĩa schema và canonicalization hậu xử lý. Công trình gốc còn sử dụng thành phần truy xuất các schema element liên quan để hỗ trợ extraction [1]. Ý tưởng được kế thừa trong đồ án là kết hợp khả năng đề xuất của LLM với một tập nhãn đích có định nghĩa.

Trong ứng dụng, extraction và sinh định nghĩa có thể được thực hiện trong cùng một lời gọi LLM. Vì vậy các giai đoạn khái niệm không nhất thiết tương ứng với ba lời gọi API riêng.

## 2.3. Embedding và cosine similarity

Embedding ánh xạ văn bản x thành vector v(x) trong không gian D chiều. Với vector khác zero, phép chuẩn hóa L2 là:

$$
\mathbf e(x)=\frac{\mathbf v(x)}{\|\mathbf v(x)\|_2}.
\tag{2.1}
$$

Điểm giữa truy vấn q và passage schema p:

$$
s(q,p)=\mathbf e(q)^\top\mathbf e(p).
\tag{2.2}
$$

Đây là cosine similarity khi hai vector có độ dài bằng một. Đơn vị đo này phản ánh độ gần trong không gian biểu diễn, có miền lý thuyết [-1,1], chưa phải xác suất đúng.

Danh sách Top-K là K mục có điểm cao nhất. Tăng K có thể tăng độ bao phủ nhưng thường đưa thêm mục không liên quan và làm dài prompt.

## 2.4. Hai bộ mã hóa được sử dụng

hybrid_vn sử dụng token, bigram, bảng từ đồng nghĩa và character n-gram để xây dựng signed feature hashing vector. Các thành phần từ vựng và ký tự được chuẩn hóa riêng rồi kết hợp với hệ số 0,88 và 0,12. Encoder này có thể chạy trong Python mà không cần dịch vụ neural embedding.

BGE-M3 là mô hình embedding đa ngôn ngữ. Model gốc hỗ trợ nhiều kiểu biểu diễn [2]; trong KG Studio, gateway dùng dense vector qua Ollama. Hai encoder có thể cùng trả vector 1.024 chiều nhưng các chiều không có chung ý nghĩa. Catalog và query phải được mã hóa bằng cùng encoder/artifact.

## 2.5. Kiểm duyệt và provenance

Human-in-the-loop là việc giữ người sử dụng trong quá trình kiểm tra và quyết định dữ liệu. Hệ thống có thể đề xuất đối tượng nghi trùng hoặc nhãn gần nhất; reviewer vẫn cần xét nội dung và phạm vi định danh.

Provenance là thông tin cho phép tìm lại nguồn và quá trình hình thành dữ kiện. Trong phạm vi đồ án, nó gồm tài liệu, chunk, bằng chứng, lần chạy, prompt và lịch sử duyệt. Provenance giúp phát hiện và sửa lỗi, nhưng không tự xác lập tính đúng lịch sử.

# CHƯƠNG 3. QUY TRÌNH TRÍCH XUẤT VÀ CHUẨN HÓA

## 3.1. Luồng tổng thể

~~~mermaid
flowchart TD
    DOC["Văn bản"] --> CHUNK["Chunk và định danh nguồn"]
    CHUNK --> RET["Truy xuất quan hệ và loại thực thể"]
    RET --> PROMPT["Ghép schema với prompt đã chọn"]
    CHUNK --> PROMPT
    PROMPT --> LLM["LLM: trích xuất và định nghĩa nhãn mới"]
    LLM --> INGEST["Kiểm tra cấu trúc và ingest"]
    INGEST --> ALIGN["Căn chỉnh proposals với catalog"]
    ALIGN --> REVIEW["Kiểm duyệt schema, thực thể và cạnh"]
    REVIEW --> EXPORT["Xuất KG theo nguồn và trạng thái"]
~~~

*Hình 3.1. Luồng chính của chế độ EDC+R trong KG Studio.*

Tài liệu được chia thành các đoạn kèm định danh và vị trí trong văn bản đã xử lý. Trước LLM, bộ truy xuất chọn schema từ danh mục. Sau LLM, hệ thống kiểm tra đầu ra, nạp các đối tượng và tạo proposal tương ứng. Target Alignment xử lý các proposal được chạm tới trong lần extraction. Người dùng tiếp tục rà soát trước khi xuất dữ liệu.

Trong implementation hiện tại, ingest và alignment được thực hiện trong vùng xử lý an toàn của engine, theo thứ tự ingest trước, alignment sau. Sơ đồ mô tả thứ tự xử lý nghiệp vụ, không biểu diễn mọi bước ghi đĩa hoặc mọi loại ngoại lệ.

## 3.2. Truy xuất schema trước LLM

Gọi C_r là catalog quan hệ, C_t là catalog loại thực thể. Mỗi mục schema được chuyển thành passage:

$$
p_i=\operatorname{format}(name_i,definition_i,description_i,aliases_i,domain_i,range_i).
\tag{3.1}
$$

Với nội dung chunk q, bộ truy xuất tính điểm theo (2.2), sau đó chọn:

$$
R(q)=\operatorname{TopK}_{p\in C_r}s(q,p),\qquad
T(q)=\operatorname{TopK}_{p\in C_t}s(q,p).
\tag{3.2}
$$

Hai giá trị K có thể khác nhau. Cấu hình lịch sử được ghi trong PDF cho EDC_R_50_place là 20 quan hệ và 30 loại thực thể. Đây là kích thước danh sách gợi ý, không phải giới hạn số thực thể hay số bộ ba được LLM sinh ra.

Nếu nhiều refinement loop được bật, kết quả trước đó có thể cung cấp hints cho vòng sau. Một cấu hình một vòng không tự có lợi ích từ lặp refinement.

Danh sách truy xuất được định dạng cùng định nghĩa và aliases để đưa vào prompt. LLM được hướng dẫn ưu tiên nhãn phù hợp trong danh sách nhưng vẫn có thể đề xuất nhãn mới. Do đó, nhãn không nằm trong Top-K không đồng nghĩa nhãn đó sẽ không bao giờ được trích xuất.

## 3.3. Cách tính embedding hybrid_vn

Sau chuẩn hóa văn bản, tokenizer lấy các token bằng biểu thức chính quy và tạo bigram từ hai token kề nhau. Phần head ngắn trước dấu hai chấm và các cụm synonym được tăng ảnh hưởng bằng cách lặp trong chuỗi mở rộng.

Với D=1.024, mỗi token được ánh xạ đến chiều h(t) bằng bốn byte đầu của MD5, đồng thời dùng một bit khác để chọn dấu. Vector từ vựng:

$$
w_j=\sum_{t:h(t)=j}\sigma(t)\alpha(t)\lambda_t.
\tag{3.3}
$$

Trong đó sigma(t) thuộc {-1,+1}; alpha bằng 2,8 với token chứa dấu gạch dưới và 1,4 trong trường hợp còn lại; lambda là trọng số học được, mặc định bằng một khi chưa có artifact.

Thành phần ký tự c được tạo từ character 3-gram và 4-gram. Embedding cuối:

$$
\mathbf e(x)=\operatorname{norm}
\left(0.88\operatorname{norm}(\mathbf w)
+0.12\operatorname{norm}(\mathbf c)\right).
\tag{3.4}
$$

Việc kết hợp giúp giữ thông tin từ vựng và một phần tương đồng hình thái. Tuy nhiên, phương pháp có thể va chạm hash và phụ thuộc vào bảng synonym. Nó không bảo đảm xử lý đúng các trường hợp phủ định hoặc tương đương ngữ nghĩa ít từ chung.

## 3.4. Cách dùng BGE-M3

BGE-M3 mã hóa văn bản bằng encoder neural; biểu diễn dense của model gốc lấy trạng thái tổng hợp của chuỗi và chuẩn hóa. Ứng dụng nhận vector qua endpoint embedding của Ollama rồi dùng công thức (2.2) [2].

Đường chạy này không kết hợp điểm sparse hoặc multi-vector của BGE-M3. Vì vậy khác biệt chính trong phép so sánh là hàm mã hóa, trong khi formatter passage và công thức xếp hạng có thể được giữ thống nhất.

Ưu thế ngữ nghĩa phải được kiểm tra bằng dữ liệu, thay vì suy ra chỉ từ kích thước model. Thời gian đo còn chịu ảnh hưởng bởi phần cứng, chiều dài chunk, batch size và overhead giao tiếp dịch vụ.

## 3.5. Extraction và kiểm tra đầu ra

Prompt yêu cầu LLM trả các thực thể, quan hệ và định nghĩa cho nhãn mở. Những thực thể làm đầu mút quan hệ cần được khai báo tương ứng trong đầu ra. Bộ kiểm tra xử lý cấu trúc dữ liệu, liên kết đối tượng và ghi nhận vấn đề bằng chứng.

Đối với thực thể yếu như “cổng” hoặc “chuông”, tên không đủ định danh độc lập trong toàn bộ dữ liệu. Hệ thống dùng ngữ cảnh tài liệu theo policy khi nạp, đồng thời hỗ trợ tên có thông tin chủ thể trong prompt. Các biện pháp này giảm nguy cơ nối nhầm nhưng không thay cho entity resolution có đánh giá độc lập.

Một cấu trúc JSON hợp lệ không bảo đảm triple đúng nghĩa. Ví dụ mô hình vẫn có thể nối một giá trị tiền tệ vào quan hệ chiều rộng. Những trường hợp này được phân tích như lỗi ngữ nghĩa, dù JSON có thể đọc được.

## 3.6. Target Alignment sau LLM

Với một proposal có tên n và định nghĩa d, hệ thống tạo query q_canon bằng cách ghép hai trường rồi xếp hạng catalog tương ứng. Quy tắc điểm:

$$
s'(n,p_i)=
\begin{cases}
1,&\operatorname{normal}(n)=\operatorname{normal}(name_i),\\
s(q_{canon},p_i),&\text{trường hợp còn lại}.
\end{cases}
\tag{3.5}
$$

Top-5 được lọc bằng candidate_threshold. Trong cấu hình đang được mô tả, ngưỡng gợi ý là 0,45, ngưỡng tự căn chỉnh là 0,86. Khi verifier tắt, ứng viên đầu có thể được tự căn chỉnh nếu đạt ngưỡng; khi verifier được gọi, kết quả lỗi hoặc “không tương đương” ngăn tự căn chỉnh.

Ngưỡng thấp không chứng minh khái niệm mới; nó chỉ cho biết chưa có ứng viên đủ điểm theo encoder và catalog hiện dùng. Tương tự, 0,86 chưa được diễn giải như xác suất hay ngưỡng tối ưu F1. Cấu hình phải ghi trạng thái verifier theo lần chạy, vì cấu hình project có thể thay đổi sau đó.

## 3.7. Quy trình kiểm duyệt

Kiểm duyệt được tổ chức theo ba nhóm nhiệm vụ: chuẩn hóa schema; xác định và hợp nhất thực thể; kiểm tra cạnh cùng bằng chứng. Thứ tự này thuận tiện cho thao tác, nhưng người dùng có thể cần quay lại bước trước khi phát hiện xung đột mới.

### 3.7.1. Gợi ý và hợp nhất thực thể

Hệ thống sinh ứng viên qua tên chuẩn hóa, aliases, token và prefix. Với ứng viên cần so khớp hình thái, SequenceMatcher cho điểm:

$$
S(A,B)=\frac{2M}{|A|+|B|}.
\tag{3.6}
$$

M là tổng độ dài các matching blocks được thuật toán tìm thấy. Các chặn trên nhanh có thể loại phép so khớp chi tiết. Blocking giúp giảm số cặp thực tế, nhưng không bảo đảm cận O(N log N) cho mọi phân bố tên.

Reviewer chọn ID giữ lại và các ID bị hấp thụ. Preview cho biết ảnh hưởng đến loại, mô tả, đầu mút và self-loop. Khi áp dụng, thông tin aliases, tài liệu, observations và lịch sử được tích lũy theo policy, đồng thời redirect lưu ánh xạ ID cũ. Những cạnh đổi đầu mút cần được kiểm tra lại.

### 3.7.2. Cạnh nghi trùng và bằng chứng

Ứng viên có thể là cạnh trùng bộ ba, vị từ gần giống trên cùng cặp nút hoặc cặp đảo chiều có dấu hiệu chủ động/bị động. Đây là heuristic để giảm công rà soát, không phải chứng minh hai phát biểu tương đương.

Khi hợp nhất, các record bằng chứng được gom về cạnh đại diện. Cạnh đại diện ưu tiên trạng thái duyệt rồi độ dài evidence; tiêu chí này phục vụ lựa chọn record, không đánh giá độ đúng lịch sử.

Reviewer cần phân biệt cùng bộ ba bề mặt với cùng sự kiện, nhất là các phát biểu có thời gian hoặc phạm vi khác nhau. Nhiều trích dẫn có thể đến từ các nguồn sao chép nhau, nên số trích dẫn không tự trở thành xác suất tin cậy.

## 3.8. Tái sử dụng kết quả duyệt

Gazetteer ghi nhớ ánh xạ bí danh và tên chuẩn để sử dụng lại khi ingest. Việc tra cứu còn phụ thuộc tương thích loại và phạm vi, vì vậy cần cơ chế sửa/xóa ánh xạ khi phát hiện gộp sai.

ML Lab có exporter tạo mẫu quan hệ từ cạnh đã duyệt hợp lệ schema và tạo cặp canonicalization từ các proposal phù hợp. Trainer Schema Retriever hiện điều chỉnh trọng số token bằng hệ số tăng 1,35, giảm 0,78 và chặn trong khoảng [0,25;5], đồng thời mở rộng synonym map.

Artifact registry:* tạo ra vẫn dùng backend hybrid_vn. Cơ chế này không fine-tune BGE-M3, chưa có trainer SR riêng cho loại thực thể và chưa thực hiện chọn mẫu chủ động theo độ không chắc chắn. Do đó báo cáo gọi là tái sử dụng phản hồi kiểm duyệt để điều chỉnh retriever.

# CHƯƠNG 4. THIẾT KẾ VÀ HIỆN THỰC KG STUDIO

## 4.1. Tổ chức ứng dụng

Ứng dụng tổ chức theo modular monolith, phân chia các use case thành sáu module:

| Module | Vai trò trong phạm vi hệ thống |
| --- | --- |
| projects | Vòng đời project, revision, commit, snapshot và projection |
| schema_intelligence | Catalog, proposal, retrieval và alignment |
| extraction | Tài liệu, chunk, engine và các lần chạy |
| curation | Duyệt, sửa, hợp nhất và quản lý bằng chứng |
| graph_qa | Snapshot đồ thị, baseline dẫn xuất, truy xuất và export |
| training | Boundary xuất dữ liệu phục vụ huấn luyện |

UI gọi các application boundary qua composition. Lựa chọn in-process giảm yêu cầu triển khai các dịch vụ nghiệp vụ riêng, phù hợp công cụ thao tác trên máy cá nhân. Ollama, LLM provider hoặc Neo4j vẫn có thể là dịch vụ ngoài process.

Kiến trúc có hướng áp dụng Ports & Adapters có chọn lọc và còn các phần legacy. Sơ đồ module thể hiện trách nhiệm, không phải bằng chứng rằng mọi cạnh import đã tuân thủ kiến trúc.

## 4.2. Nguồn dữ liệu và dữ liệu dẫn xuất

Project JSON bundle là nguồn dữ liệu authoritative. SQLite cung cấp bản chiếu đọc cho truy vấn; vector index chứa biểu diễn schema dẫn xuất. Khi catalog hoặc model thay đổi, tính hợp lệ của chỉ mục phải được xác định bằng fingerprint thay vì chỉ dựa vào số lượng phần tử.

Việc tách nguồn sự thật khỏi dữ liệu dẫn xuất giúp định nghĩa rõ cách khôi phục khi đồng bộ lỗi. SQLite không được xem là một nguồn sự thật nghiệp vụ thứ hai.

## 4.3. Xem trước và commit

Những mutation được migrate sử dụng ProjectCommitCoordinator để điều phối khóa theo project, kiểm tra request/revision, tạo snapshot và lưu authoritative candidate. Candidate cần tách khỏi project đang hiển thị. Coordinator gọi executor với project, nên sự tách biệt là nghĩa vụ của executor/caller.

Sau khi ghi bundle thành công, memory được cập nhật và projection được đồng bộ. Nếu SQLite lỗi, authoritative commit có thể vẫn đã thành công; hệ thống phải thể hiện trạng thái đồng bộ đang chờ và cho phép resync.

RLock bảo vệ trong process. Không diễn giải cơ chế này như một giao dịch phân tán ACID bao trùm JSON, SQLite và vector store hoặc như khóa giữa nhiều worker.

## 4.4. Provenance, prompt và request

Đối với một cạnh, người dùng có thể đi từ evidence đến tài liệu/chunk và từ run_id đến cấu hình lần chạy. Prompt version và content hash giúp xác định nội dung chỉ dẫn. Prepared request giúp xem input được dùng thực tế, bao gồm nội dung sau fitting khi trường tương ứng có lưu.

Cần phân biệt prompt_id với prompt_version_id và văn bản raw với fitted. Khôi phục prompt cũ không đồng nghĩa có thể tái sinh cùng output từ một provider đã thay đổi model.

Offsets biểu thị vị trí trong văn bản đã xử lý. Khi kiểm tra nguồn PDF/DOCX gốc cần thông tin trang và quá trình chuyển đổi. Trường hợp không tìm thấy evidence chính xác phải thể hiện diagnostics, không suy ra sự chính xác từ việc các trường offset đã có giá trị.

## 4.5. Baseline và xuất dữ liệu

Nhánh free_triples giữ artifact thô và không dùng EDC ingestion để bổ sung schema vào KG chính. Baseline KG được dựng dẫn xuất với policy chuẩn hóa bề mặt riêng, nhằm giữ phương pháp đối chứng tách khỏi tác động kiểm duyệt của EDC.

Khi xuất KG, nguồn đồ thị và trạng thái phải được chọn tường minh. Một đồ thị chỉ chứa cạnh đã duyệt có ý nghĩa khác với mọi cạnh được sinh ra; không thay thế hai scope khi thống kê.

# CHƯƠNG 5. THỰC NGHIỆM VÀ THẢO LUẬN

> Ghi chú biên tập: các bảng lịch sử dưới đây được chép và tính lại từ PDF ngày 16/11. Chúng chưa được tái trích xuất từ một snapshot đã khóa trong đợt biên tập này. Phải hoàn tất các mục E01–E06 trong sổ bằng chứng trước khi đưa thành số liệu kết luận của bản nộp.

## 5.1. Thiết lập và phạm vi phép so sánh

PDF cũ ghi nhận 50 tài liệu, 90.841 từ, 402.747 ký tự và 230 chunk, dùng DeepSeek với model ID deepseek-flash. Các nhánh là Baseline_50_place, EDC_50_place và EDC_R_50_place.

Tên model phải ghi theo model ID/provenance thực tế. Không suy ra một phiên bản model cố định chỉ từ model ID mà nhà cung cấp có thể thay đổi.

Các nhánh khác nhau đồng thời về schema, prompt, retrieval, verifier và kiểm duyệt. Phép so sánh này mô tả các cấu hình hệ thống hoàn chỉnh; chưa tách được ảnh hưởng nhân quả của riêng thành phần +R. Muốn tách riêng cần ablation giữ các điều kiện còn lại giống nhau.

Đồ thị thô, đồ thị đã duyệt và baseline dẫn xuất được thống kê riêng. Các đặc trưng như số loại nhãn và LCC không thay cho precision/recall nội dung bộ ba.

## 5.2. Định nghĩa metric

Gọi G_i là tập nhãn đúng quan sát được của chunk i, C_i^K là tập Top-K, chỉ xét các chunk có gold không rỗng cho nhiệm vụ tương ứng.

Recall trung bình theo chunk:

$$
R_{macro}@K=\frac{1}{N}\sum_i\frac{|G_i\cap C_i^K|}{|G_i|}.
\tag{5.1}
$$

Recall gộp theo nhãn:

$$
R_{micro}@K=\frac{\sum_i|G_i\cap C_i^K|}{\sum_i|G_i|}.
\tag{5.2}
$$

Macro cho mỗi chunk trọng số bằng nhau; micro cho chunk nhiều nhãn trọng số lớn hơn. Các bảng phải ghi rõ loại nào đang sử dụng.

Với một target đúng cho mỗi proposal alignment:

$$
Accuracy@K=\frac{1}{N}\sum_i\mathbb 1[rank_i\le K],\qquad
MRR=\frac{1}{N}\sum_i\frac{1}{rank_i}.
\tag{5.3}
$$

Ngoài thứ hạng, cần phân biệt ứng viên được xếp trong Top-5 với ứng viên còn lại sau ngưỡng score. Alignment benchmark phải ghi có áp dụng exact-name override, candidate threshold và verifier hay không.

Về tốc độ, p50 và p95 là phân vị độ trễ, cần kèm số mẫu và trạng thái warm/cold. Thời gian mã hóa một query không đồng nghĩa thời gian đầy đủ truy xuất cả hai catalog. Production hiện có hai lần query embedding cho quan hệ và loại.

## 5.3. Quy mô đồ thị theo số liệu lịch sử

| Chỉ tiêu | Free Triples | EDC mở | EDC+R |
| --- | ---: | ---: | ---: |
| Số đỉnh toàn bộ | 6.153 | 5.637 | 5.000 |
| Số cạnh toàn bộ | 4.676 | 5.534 | 4.533 |
| Số nhãn quan hệ/vị từ toàn bộ | 3.124 | 2.900 | 134 |
| Số cạnh trong scope đã duyệt | Không áp dụng | 4.663 | 4.289 |
| Số nhãn quan hệ trong scope đã duyệt | Không áp dụng | 2.396 | 66 |

*Bảng 5.1. Thống kê lịch sử từ PDF cũ; chưa đại diện trạng thái project ngày 21/11.*

So trong cùng scope toàn bộ, số nhãn giảm từ 3.124 xuống 134, tương đương khoảng 95,7%; từ EDC mở 2.900 xuống 134, giảm khoảng 95,4%. Đây là mức giảm số nhãn, không phải mức tăng precision.

Phép tính 3.124 xuống 66 cho mức giảm khoảng 97,9%, nhưng hai đầu thuộc scope khác nhau: baseline thô và EDC+R sau kiểm duyệt. Nếu sử dụng, phải gọi là thay đổi của toàn quy trình có con người tham gia.

Việc Free Triples không xuất loại thực thể được ghi là “không áp dụng”. Không diễn giải thành mọi đỉnh baseline đều bị phân loại sai.

## 5.4. Token và đánh đổi chi phí

| Nhánh | Input token | Output token | Tổng token |
| --- | ---: | ---: | ---: |
| Free Triples | 310.817 | 542.224 | 853.041 |
| EDC mở | 448.817 | 1.281.467 | 1.730.284 |
| EDC+R, các lượt thành công | 2.127.589 | 882.119 | 3.009.708 |

*Bảng 5.2. Token lịch sử được ghi trong PDF cũ; phạm vi là các lượt thành công theo báo cáo đó.*

Output token của EDC+R giảm khoảng 31,2% so với EDC mở, trong khi tổng token tăng khoảng 73,9%. Kết quả phản ánh việc thêm schema và các bước xác minh vào input để giảm lượng nhãn/định nghĩa tự sinh ở output.

Không suy ra chi phí tiền chỉ từ tổng token. Nếu cần tính chi phí, sử dụng đơn giá input/output, cache và thời điểm áp dụng của nhà cung cấp. Chi phí retry/lượt lỗi cần thống kê thêm ngoài bảng thành công.

## 5.5. Đối chiếu các benchmark truy xuất

PDF cũ trình bày benchmark 109 chunk, 76 quan hệ, 33 loại và các biến thể passage. Trong phiên khảo sát 20/11, benchmark khác dùng raw_chunk_text của 230 run lịch sử với catalog hiện có 81 quan hệ, 33 loại. Hai thiết lập khác nhau cả mẫu, catalog và cách tổng hợp Recall.

| Thiết lập khảo sát 20/11 | hybrid_vn:default | ollama:bge-m3 |
| --- | ---: | ---: |
| Relation micro Recall@5 | 20,48% | 32,20% |
| Entity-type micro Recall@5 | 20,71% | 25,79% |
| p95 hai lượt query embedding và scoring, warm, 20 mẫu | 11,26 ms | 4.362,34 ms |

*Bảng 5.3. Kết quả đã quan sát trong phiên công cụ ngày 20/11; cần lưu script/raw/config đầy đủ và kiểm tra parity trước khi dùng làm bảng kết quả chính thức.*

Các con số cho thấy xu hướng BGE-M3 tốt hơn về thứ hạng trên mẫu quan sát và có độ trễ lớn hơn trong cách gọi đơn lẻ hiện tại. Không diễn giải tỷ số độ trễ này thành thuộc tính cố hữu trên mọi máy, mọi batch hoặc mọi triển khai BGE-M3.

Benchmark đã tận dụng formatter/catalog production nhưng tính rank trực tiếp bằng ma trận, không gọi toàn bộ retrieve_for_chunk/rank_candidates. Vì vậy cần ghi đây là phép đo encoder và xếp hạng dưới điều kiện replay. p95 cũng chưa gồm toàn bộ chi phí application/cache. 230 run lịch sử đều có trace dùng BGE-M3; gold hậu kiểm có thể chịu ảnh hưởng của gợi ý đầu vào.

Phép đo alignment sơ bộ có 31 cặp quan hệ và hai cặp loại. Exporter có thể nhận cả proposal approve hoặc nhãn giống chính tên chuẩn. Chưa loại hết exact-match, aliases hậu kiểm hoặc nhãn mới được thêm vào catalog, nên không dùng kết quả Top-5 hoàn hảo để kết luận khả năng tổng quát hóa.

## 5.6. Kiểm duyệt, cấu trúc và lỗi còn lại

PDF lịch sử ghi nhận sự giảm cạnh trùng, self-loop bị loại và LCC của scope đã duyệt tăng. Các thống kê này có ích để mô tả tác động thao tác. Tuy nhiên, khi thay scope, số đỉnh, số cạnh và mẫu số LCC cũng đổi. Cần ghi rõ cách xử lý đỉnh cô lập và có chiếu graph có hướng sang vô hướng hay không.

Các lỗi được ghi trong PDF gồm giá trị tiền tệ bị gán vào quan hệ kích thước, tổ chức bị gán loại người và evidence có sai khác dấu câu. Các ví dụ cho thấy có bằng chứng và đúng catalog vẫn chưa bảo đảm đúng ngữ nghĩa.

Không phải mọi self-loop đều sai trong mọi ontology. Trong tập dữ liệu cần nêu policy cụ thể: phát hiện để reviewer kiểm tra, hoặc loại trong scope đã xác định. Tương tự, tên giống nhau chỉ tạo ứng viên, chưa chứng minh đồng nhất.

## 5.7. Phản hồi kiểm duyệt và giới hạn của phép đo học

Trong phiên 20/11 có phép đo grouped 5-fold theo doc_id trên 1.528 mẫu quan hệ xuất từ evidence. Recall@5 quan sát tăng từ 16,10% lên 24,28%, MRR từ 0,1232 lên 0,1676. Đây là đầu mối thực nghiệm bổ sung, chưa thay thế đánh giá retrieval trên raw chunk.

Để dùng kết quả này trong bản nộp, phải giữ script, artifact/config từng fold, kiểm soát hash seed và xác nhận catalog/aliases không rò rỉ phản hồi của tài liệu test. Chỉ tách doc_id cho records chưa đủ chứng minh mọi thông tin giám sát đã được tách.

Metadata trainer hiện đánh giá trên tập train nên không dùng làm bằng chứng hiệu quả trên dữ liệu chưa thấy. Trainer này cũng không chứng minh cải thiện entity-type retrieval hoặc fine-tune BGE-M3.

## 5.8. Các nguy cơ ảnh hưởng tính hợp lệ

1. Gold từ dữ liệu đã duyệt chưa độc lập với extractor/retriever đã sinh ra dữ liệu đó và có thể chưa bao phủ mọi quan hệ trong văn bản.
2. Catalog/aliases hậu kiểm có thể chứa thông tin từ các quyết định dùng làm test.
3. Tái chia chunk rồi ghép bằng chunk_number có thể làm lệch văn bản lịch sử; ưu tiên run_id, raw input và hash.
4. Các pipeline khác nhau nhiều yếu tố, chưa phải ablation chỉ thay thành phần +R.
5. Có thể đo lặp những đoạn cùng tài liệu; không coi mọi query là mẫu độc lập khi tính khoảng tin cậy.
6. Độ trễ phụ thuộc phần cứng, trạng thái model, cách tạo client, batch và số lần gọi; chưa có đo peak memory trong đợt này.
7. Rút gọn catalog theo nhãn xuất hiện trong gold làm bài toán dễ hơn; phải ghi rõ thay vì so ngang catalog đầy đủ.

# CHƯƠNG 6. KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN

## 6.1. Kết quả thực hiện

Phần công việc cá nhân đã triển khai một công cụ hỗ trợ tạo KG từ văn bản tiếng Việt, kết hợp gợi ý lược đồ, căn chỉnh nhãn và kiểm duyệt. Hệ thống tổ chức dữ kiện cùng nguồn văn bản và dấu vết lần chạy để hỗ trợ đối chiếu, đồng thời cung cấp thao tác hợp nhất có preview và lưu trữ có kiểm soát.

Các thống kê lịch sử cho thấy cấu hình EDC+R và kiểm duyệt tạo ra tập nhãn tập trung hơn so với extraction tự do trên dữ liệu khảo sát. Benchmark embedding cho thấy đánh đổi giữa chất lượng truy xuất và độ trễ. Các kết quả này được giới hạn ở điều kiện thực nghiệm đã mô tả; chưa xác lập precision/recall nội dung cho toàn bộ KG.

## 6.2. Hạn chế

Tập gold độc lập cấp bộ ba chưa hoàn chỉnh. Tính tương thích CIDOC cần được thể hiện bằng mapping cụ thể. Ngưỡng similarity chưa được calibration thành xác suất và chưa có đủ bằng chứng tối ưu. Dữ liệu alignment loại thực thể còn ít. Training hiện là điều chỉnh heuristic cho hybrid_vn và chưa có kết quả fine-tune BGE-M3.

Về hệ thống, khóa hiện bảo vệ trong process; đồng bộ dữ liệu dẫn xuất có thể thất bại và cần resync. Chưa có đánh giá usability với người dùng đủ lớn để kết luận công cụ giảm bao nhiêu công kiểm duyệt.

## 6.3. Hướng phát triển

Ưu tiên là xây một tập gold nhỏ nhưng độc lập, ghi quy tắc annotation và kiểm tra chéo; khóa snapshot/config để benchmark có thể tái lập. Tiếp theo là đo Recall tại đúng K=20/30 và khảo sát ngưỡng alignment theo từng encoder.

Về hiệu năng, có thể thử tái sử dụng embedding query cho hai catalog và batch embedding, nhưng mức tăng tốc phải được đo sau triển khai. Về phản hồi, cần tách dữ liệu và catalog giữa train/test, bổ sung huấn luyện truy xuất loại thực thể nếu có đủ nhãn, rồi mới cân nhắc fine-tune model neural.

# TÀI LIỆU THAM KHẢO CỐT LÕI

[1] Bowen Zhang và Harold Soh. 2024. Extract, Define, Canonicalize: An LLM-based Framework for Knowledge Graph Construction. Proceedings of EMNLP, 9820–9836. https://aclanthology.org/2024.emnlp-main.548/

[2] Jianlv Chen và cộng sự. 2024. BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation. https://arxiv.org/abs/2402.03216

[3] CIDOC CRM Special Interest Group. Definition of CIDOC CRM, version 7.1.3. https://cidoc-crm.org/html/cidoc_crm_v7.1.3.html

Nguồn implementation để đối chiếu cơ chế được liệt kê trong [tài liệu hiệu đính](tai-lieu-co-che-kg-studio-hieu-dinh-2026-11-21.md). Trước bản nộp cần bổ sung danh mục URL/tên bài của 50 tài liệu, thời điểm lấy dữ liệu, nguồn model/provider đúng lần chạy và chuẩn hóa các tài liệu tham khảo còn lại trong PDF.
