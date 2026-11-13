# Kế hoạch Tối ưu `EDC + R` & `Target Alignment` Song ngữ Anh–Việt (CIDOC CRM) — Bản 2 (đã hiệu chỉnh theo dữ liệu thật)

**Cập nhật:** 2026-11-14 · **Thay thế bản đầu cùng tên.** Bằng chứng chi tiết: [real-data-test-report.md](real-data-test-report.md) · mã tái lập: [evidence/bench_bilingual_edc_real.py](evidence/bench_bilingual_edc_real.py) · số liệu thô: [evidence/bench_results.md](evidence/bench_results.md).

> **Trạng thái:** kế hoạch, **chưa sửa mã ứng dụng**. Mọi tính năng mới mặc định TẮT/giữ hành vi cũ cho tới khi qua cổng đo O0 trên dữ liệu của chính dự án CIDOC.

---

## 1. Vì sao phải sửa bản đầu

Bản đầu dựa trên một benchmark tổng hợp (catalog tự soạn, 5 đoạn văn, cụm từ khóa chép từ `description`). Chạy lại trên **3 dự án thật** (gold do người dùng đã duyệt) cho thấy:

| Giả thuyết bản đầu | Kết quả trên dữ liệu thật | Quyết định |
|---|---|---|
| Ẩn/đẩy `name` ra khỏi vector `+R` tăng mạnh recall (41%→76%) | **Không tái lập.** Chỉ **loại thực thể** tăng (R@25: +13,6 / +4,6 / +4,4 điểm; cận dưới CI95 ≥ 0, riêng dự án thứ ba chạm 0,0) khi tên không mang tín hiệu. **Quan hệ: không cải thiện có ý nghĩa**; giảm −0,7 đến −2,2 điểm ở cả 3 dự án (2/3 có CI95 hoàn toàn dưới 0) | Giữ mặc định hiện tại; chỉ bật tùy chọn cho `entity_types` |
| Tách `head_text` theo `\| , ;` (O2) | **Không tác dụng**: chênh lệch ≤ 0,1 điểm ở mọi chỉ số | **Bỏ khỏi kế hoạch** |
| Cộng điểm từ khóa → tự gộp ≥ 0,86 (73,3%) | Số 73,3% là **tautology** (từ khóa chép từ mô tả). Trên dữ liệu thật, alias khớp chính xác kiểu leave-one-out kích hoạt **0/337** đề xuất; kết quả 51/51 và 286/286 ban đầu là **rò rỉ gold** (khi gộp, hệ thống tự thêm tên đề xuất vào `aliases`) | Chỉ làm **gợi ý xếp hạng**, không tự gộp; cần xác nhận bằng O0 |
| Alignment bằng embedding đủ tin cậy | Top-1 chỉ **2,0% (quan hệ, n=51)** và **3,8–5,2% (loại, n=286)**; ngưỡng 0,86 phủ 1/51 và đúng 0 | Không tự gộp bằng embedding; dựa vào LLM Verifier / duyệt tay |
| `top_k` 15/10 là đủ | Catalog cỡ 76/30: Rel R@15 chỉ **34–42%**, R@30 **56–72%**; Type R@10 **34–43%**, R@25 **84–90%** | Khuyến nghị `top_k_relations≥30`, `top_k_entity_types≈25` |

Điều kiện đã biết trong dữ liệu thật: `kg_hanoi_edc_r_a` đang chạy `auto_align_threshold=0.99`, `candidate_threshold=0.75`, `enable_llm_verifier=True` — tức nhóm đã vô hiệu hóa tự gộp bằng embedding, khớp với kết quả đo.

## 2. Rà soát xung đột với phiên bản hiện tại (đã sửa)

| # | Rủi ro | Cách xử lý trong bản 2 |
|---|---|---|
| 1 | Train/serve parity: `exporter.py` dùng `format_catalog_passage` (dòng 50, 124, 128, 165, 169) | `purpose="canon"` phải **giống từng byte** chuỗi hiện tại `name: definition \| description` (bản đầu định nghĩa sai thành `name \| description: definition`). Chỉ khi bật chế độ mới, `build_sr_triplets` mới dùng cùng chuỗi với serving; thêm test parity |
| 2 | Cache `vector_repo` dùng chung `sr`/`canon` | Khóa cache thêm `passage_mode` (`current`\|`name_tail`); mặc định `current` giữ nguyên tên file `{kind}_index.npz`; chế độ mới dùng `{kind}_nametail_index.npz`. `invalidate_project_indices`/`get_index_status` quét cả hai |
| 3 | Embedder khác `hybrid_vn` / fake embedder thiếu thuộc tính | Dùng `getattr(embedder, "backend", "")`; chế độ `name_tail` chỉ áp dụng cho `hybrid_vn`; mục thiếu mô tả → giữ `name` |
| 4 | Đổi `fingerprint` làm stale toàn bộ gợi ý cũ, đổi `prompt_id` (`edc_plus_r.py:149`) | **Không đổi `fingerprint`** (bỏ việc bump version). Vì mặc định không đổi hành vi nên không cần |
| 5 | Prompt dùng chung cho `MODE_EDC`; dự án cũ đã đóng băng prompt | Quy tắc đặt trong `SchemaRetriever.format_retrieved_schema_block` (cả engine lẫn 2 điểm gọi của extraction service nhận cùng nội dung → preview/execution parity); thêm câu ghi đè tường minh các quy tắc "tiếng Việt, chữ thường, không gạch dưới" của `DEFAULT_EDC_PROMPT` đối với nhãn có trong gợi ý |
| 6 | `propose_term` chỉ chuẩn hóa `-`/`_` cho `relations` | Bổ sung cho `entity_types` (phòng ngừa cho catalog CIDOC). **Không có bằng chứng thực**: 0 trường hợp trong 3 dự án hiện có |
| 7 | Đảo chiều chủ động/bị động, khớp một phần, khớp mơ hồ | Chỉ khớp **chính xác sau chuẩn hóa hai phía** (`clean_relation_name` cho quan hệ — nếu không, 21 cụm trong mẫu 76 quan hệ như "ghi chép về", "gọi là" không bao giờ khớp); **quét toàn catalog**; chỉ xét khi **duy nhất** một mục khớp (ví dụ "sụp đổ" thuộc cả `E6` và `E64` → mơ hồ); **không bao giờ tự gộp chỉ nhờ gợi ý từ khóa** |
| 8 | Chiều quan hệ chưa được bảo vệ khi `enable_llm_verifier=False` | Quan hệ có chiều chỉ tự gộp khi LLM Verifier xác nhận **có** kèm `[Domain]→[Range]` từ `definition` và kind của nguồn/đích; nếu không, giữ `pending` kèm ứng viên |

## 3. Lộ trình

### O0 — Cổng đo (làm trước, không đổi mã ứng dụng)
- Chạy `bench_bilingual_edc_real.py <tên_dự_án>` trên dự án CIDOC của người dùng **sau khi có ≥ 200 cạnh đã duyệt và ≥ 50 đề xuất đã gộp** (gold độc lập với `description` đã soạn).
- Với Verifier: đo opt-in trên ≥ 50 mẫu bằng khóa API thật (chưa đo trong đợt này).
- **Tiêu chí bật tính năng:** cận dưới CI95 của Δ recall > 0 trên chính dự án đó và không có chỉ số nào giảm có ý nghĩa.

### O1 — Cấu hình & chuẩn hóa định danh
- `EDCPlusRSettingsDTO` thêm: `sr_catalog_text_mode: Literal["current","name_tail"]="current"` (chỉ tác dụng với `entity_types`), `keyword_hint_score: float∈[0,0.95]=0.0` (0 = tắt). `SchemaModel` có `extra="ignore"` nên dự án cũ nạp bình thường; `update_edc_plus_r_settings` đi qua DTO nên trường mới được lưu không cần sửa facade.
- `propose_term`: chuẩn hóa `-`/`_` cho `entity_types` (không cắt từ nối cuối).

### O2 — Passage & cache (chỉ khi `sr_catalog_text_mode="name_tail"`)
- `format_catalog_passage(..., purpose="canon")`: byte-identical với hiện tại. `purpose="sr_name_tail"`: `"{description}: {definition} | {name}"`, mục trống mô tả → chỉ `name`.
- `VectorIndexRepository`: thêm `passage_mode` vào khóa cache/tên file như mục 2.2. Không đổi `EmbedderGateway`.
- `ActiveLearningExporter.build_sr_triplets` dùng cùng passage với serving theo cài đặt dự án.

### O3 — Target Alignment an toàn
- `rank_candidates`: tính **gợi ý khớp từ khóa/alias** (quét toàn catalog, chuẩn hóa hai phía, duy nhất). Điểm gợi ý = `min(keyword_hint_score, auto_align_threshold − 0.01)` ⇒ **không thể tự gộp một mình**; ghi `reason` rõ.
- Tự gộp quan hệ yêu cầu Verifier xác nhận + kiểm tra chiều (mục 2.8). `build_verification_prompt` nhận thêm `[kind nguồn → kind đích]` tùy chọn.
- UI `prompt_editor.py`: slider `keyword_hint_score` (0 = tắt) và hộp chọn `sr_catalog_text_mode`, kèm chú thích "chưa kiểm chứng trên dự án của bạn".

### O4 — Prompt lai 2 tầng (trong `format_retrieved_schema_block`)
1. Nhãn gợi ý khớp **cả nghĩa lẫn chiều** → giữ nguyên văn `name` chuẩn (ghi đè quy tắc chữ thường/tiếng Việt cho trường hợp này).
2. Không khớp tuyệt đối → **không gán ép** (chống anchoring), tự đề xuất tên và định nghĩa tiếng Việt.
3. Hướng dẫn sự kiện trung gian (`E7/E12/E11`) chỉ chèn khi catalog thực sự chứa các lớp đó.
4. `ten` thực thể giữ nguyên văn tiếng Việt. Khuyến nghị `refinement_loops=1` (engine chỉ ingest vòng cuối).

## 4. Kiểm thử bắt buộc khi triển khai
- Unit: `canon` passage byte-identical (so với chuỗi hiện tại); cache `current` vs `name_tail` không ghi đè nhau và bị `invalidate_*` dọn sạch; DTO nạp dự án cũ ra mặc định; `propose_term` `E22 Human Made Object`→`E22 Human-Made Object`; gợi ý từ khóa: duy nhất / mơ hồ / leave-one-out / không tự gộp; fake embedder thiếu `backend`; golden-string cho prompt block và parity preview–execution.
- Hồi quy: toàn bộ `tools/run_isolated_tests.py` (kể cả `test_architecture_boundaries`, `test_prompt_versions`, `test_edc_bulk_review`, `test_performance_optimizations`).
- Thực nghiệm: chạy lại benchmark thật trước/sau trên cùng dữ liệu, kèm CI95.
- Sau khi đổi mã: cập nhật `AI/structure.md` (nếu đổi contract) và `graphify update .`.

## 5. Điều CHƯA được đo (không được tuyên bố)
- Hiệu quả **LLM Verifier** và chất lượng gán nhãn của DeepSeek với catalog CIDOC thật.
- Hiệu quả cơ chế từ khóa trên catalog CIDOC có `description` dạng danh sách cụm từ (chưa có dữ liệu thật; các số liệu tổng hợp trước đây chỉ mang tính minh họa).
- Chất lượng đảo chiều quan hệ trên dữ liệu thật.
- Bias của phép đo: catalog thật được dựng hậu kiểm từ đề xuất LLM nên có thể dễ hơn schema CIDOC dựng sẵn; gold của `kg_hanoi_edc_r_a` có thể thiên về nhãn mà bộ truy xuất cũ từng gợi ý.
