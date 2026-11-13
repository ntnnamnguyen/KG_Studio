# Báo cáo kiểm thử thực tế — kế hoạch song ngữ CIDOC `EDC + R`

**Ngày chạy:** 2026-11-14 · **Python:** 3.13.2 (`.venv-win`) · **Lệnh:** `& .\.venv-win\Scripts\python.exe AI\report_ver2\evidence\bench_bilingual_edc_real.py`
**Phạm vi:** chỉ đọc `data/projects/*/project.json`; không sửa dữ liệu, không sửa mã ứng dụng, không gọi LLM/mạng. Số liệu thô: [evidence/bench_results.md](evidence/bench_results.md).

## 1. Dữ liệu và phương pháp

| Dự án | Catalog (quan hệ / loại) | Chunk có gold | Gold (quan hệ / loại) | Kiểu tên nhãn |
|---|---|---|---|---|
| `kg_hanoi_edc_r_a` | 642 / 69 | 70 | 920 / 618 | ASCII snake_case, không khớp văn bản (tương đương "name tiếng Anh" = nhiễu) |
| `hanoiqa6` | 726 / 300 | 29 | 873 / 599 | snake_case có dấu tiếng Việt |
| `test1` | 173 / 63 | 6 | 194 / 105 | tiếng Việt có khoảng trắng (name mang tín hiệu) |

- **Bài A (Schema Retriever):** query = chunk thật; gold = quan hệ và kind của các cạnh `Đã duyệt` trong chunk đó. Chỉ số: recall trung bình theo chunk; Δ so với hiện tại kèm CI95 bootstrap theo chunk (2000 mẫu, seed cố định). A1 = catalog đầy đủ; A2 = thu nhỏ còn 76 quan hệ / 30 loại dùng nhiều nhất (mô phỏng cỡ schema của bạn).
- **Bài B (Target Alignment):** gold = `canonical_name` người dùng đã chọn khi gộp (`status=merged`). Có kiểm tra sanity: truy vấn bằng chính mục catalog → Top-1 = **100%** (pipeline đo không hỏng).
- Biến thể: V0 hiện tại · V1 ẩn `name` · V2 `name` xuống cuối · V3/V4 = V1/V2 + tách `head_text`.

## 2. Kết quả Bài A — Schema Retriever (Δ điểm % so với V0; [CI95])

| Dự án / catalog | Rel R@15 (V0 → V2) | Rel R@30 | Type R@10 | Type R@25 |
|---|---|---|---|---|
| `kg_hanoi` A1 (642/69) | 14,0% → V1 +0,9 [−0,2; 2,0] | +0,6 [−0,8; 2,2] | +3,4 [1,1; 5,7] | **+13,6 [9,8; 17,2]** |
| `kg_hanoi` A2 (76/30) | 39,4% → V1 −2,0 [−4,3; 0,1] | +2,5 [−0,7; 5,7] | +2,8 [−0,5; 6,3] | **+4,6 [1,8; 7,7]** |
| `hanoiqa6` A1 (726/300) | 8,0% → V1 **−0,7 [−1,6; −0,0]** | −0,4 [−1,4; 0,5] | **−1,1 [−2,2; −0,1]** | +0,3 [−1,5; 2,0] |
| `hanoiqa6` A2 (76/30) | 33,8% → V1 +6,0 [−2,2; 16,0] | +0,2 [−9,9; 8,0] | −1,1 [−5,0; 2,9] | +4,4 [0,0; 9,1] |
| `test1` A1 (173/63) | 25,1% → V1 **−2,2 [−4,4; −0,5]** | −0,5 [−3,6; 2,7] | +2,5 [0,0; 5,5] | −0,2 [−2,9; 2,3] |

(Bảng rút gọn theo V1 "ẩn name"; V2 "name xuống cuối" cho xu hướng tương tự, riêng loại thực thể `test1` Type R@10 V2 = **+3,7 [1,0; 6,7]**.)

**Kết luận Bài A**
1. Chỉ **loại thực thể** hưởng lợi khá nhất quán và có ý nghĩa (nhất là R@25) khi tên nhãn không mang tín hiệu; quan hệ **không** cải thiện có ý nghĩa, một số dự án giảm nhẹ.
2. Giả thuyết cũ "ẩn name đưa recall 41%→76%" **không tái lập** — số đó đến từ catalog tự soạn.
3. **Tách `head_text` (V3 vs V1, V4 vs V2): chênh lệch ≤ 0,1 điểm ở mọi chỉ số → vô hiệu**, bỏ khỏi kế hoạch.
4. Cỡ 76/30: Rel R@15 chỉ 34–42%, R@30 56–72%; Type R@25 84–90%. Cấu hình thật của `kg_hanoi_edc_r_a` đã dùng `top_k` 30/25 — hợp lý.

## 3. Kết quả Bài B — Target Alignment

| Loại | n | Top-1 | Top-3 | Auto ≥ 0,86 (phủ / đúng) | Auto ≥ 0,60 (phủ / đúng) |
|---|---|---|---|---|---|
| Quan hệ (hiện tại) | 51 | **2,0%** | 7,8% | 1 / 0 | 11 / 1 |
| Loại thực thể (hiện tại) | 286 | **3,8%** | 9,8% | 0 / 0 | 18 / 0 |
| Loại thực thể (name xuống cuối) | 286 | 5,2% | 9,4% | 0 / 0 | 16 / 0 |

Luật khớp chính xác theo alias/mô tả (duy nhất, chuẩn hóa hai phía):

| Cách đo | Kích hoạt | Đúng |
|---|---|---|
| Không loại rò rỉ (sai phương pháp) | 51/51 quan hệ, 286/286 loại | 100% — **giả**, vì khi gộp hệ thống tự thêm tên đề xuất vào `aliases` |
| **Leave-one-out (đúng phương pháp)** | **0 / 337** | — |

**Kết luận Bài B**
1. Embedding `hybrid_vn` **không đủ tin cậy để tự gộp** trên dữ liệu thật (Top-1 2–5%; ngưỡng 0,86 gần như không kích hoạt; hạ xuống 0,60 thì đúng ≤ 1 ca). Điều này khớp với việc dự án thật đặt `auto_align_threshold=0.99` và bật Verifier.
2. Khớp alias chính xác **không cứu được tên đề xuất mới** (0/337 sau khi loại rò rỉ). Cơ chế "từ khóa tiếng Việt trong `description`" chưa thể kết luận vì chưa có dữ liệu thật có `description` dạng danh sách cụm từ.
3. Con số 73,3% ở lượt trước **không được dùng làm bằng chứng**.

## 4. Kiểm tra nhanh các giả thuyết khác
- Chuẩn hóa `-`/`_` cho `entity_types` ở `propose_term`: **0** đề xuất tránh được trong 3 dự án (355+300+63 đề xuất loại) → chỉ là phòng ngừa cho catalog CIDOC, chưa có bằng chứng thực.
- Mã ứng dụng **không đổi** nên chưa chạy lại toàn bộ `tools/run_isolated_tests.py`; chỉ thêm tệp dưới `AI/report_ver2/`.

## 5. Giới hạn của phép đo (cần nói rõ khi viết ĐATN)
- Số chunk ít (70/29/6) → khoảng tin cậy rộng, nhất là `test1`.
- Catalog thật được dựng hậu kiểm từ đề xuất LLM nên **dễ hơn** schema CIDOC dựng sẵn; gold là nhãn LLM tạo rồi người duyệt (có thể thiên về nhãn bộ truy xuất cũ từng gợi ý ở `kg_hanoi_edc_r_a`).
- Chưa đo: LLM Verifier, chất lượng DeepSeek với nhãn CIDOC tiếng Anh, đảo chiều quan hệ.
- Cách đo đúng cho đề tài của bạn: chạy lại script trên dự án CIDOC sau khi có ≥ 200 cạnh đã duyệt và ≥ 50 đề xuất đã gộp: `& .\.venv-win\Scripts\python.exe AI\report_ver2\evidence\bench_bilingual_edc_real.py <tên_dự_án>`.
