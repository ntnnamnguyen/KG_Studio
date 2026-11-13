# Kết quả benchmark dữ liệu thật (tự sinh bởi bench_bilingual_edc_real.py)


## Dự án `kg_hanoi_edc_r_a` — tên ASCII snake_case, 1 token, KHÔNG khớp văn bản (giống 'name tiếng Anh' = nhiễu)

- Catalog: 642 quan hệ, 69 loại | Chunk có gold: 70 | gold quan hệ: 920, gold loại: 618


### Bài A1 — Schema Retriever (+R), catalog ĐẦY ĐỦ: Recall trung bình theo chunk (Δ so với V0, [CI95 bootstrap theo chunk])

| Biến thể | Rel R@15 | Rel R@30 | Type R@10 | Type R@25 |
|---|---|---|---|---|
| V0 hiện tại (name head 3x) |  14.0% |  21.7% |  11.7% |  35.9% |
| V1 ẩn name (D) |  14.9% (Δ +0.9 [-0.2; +2.0]) |  22.3% (Δ +0.6 [-0.8; +2.2]) |  15.2% (Δ +3.4 [+1.1; +5.7]) |  49.5% (Δ+13.6 [+9.8; +17.2]) |
| V2 name xuống cuối (C) |  13.8% (Δ -0.3 [-1.1; +0.6]) |  21.2% (Δ -0.5 [-1.8; +0.6]) |  16.2% (Δ +4.4 [+2.0; +7.0]) |  48.4% (Δ+12.5 [+8.6; +16.3]) |
| V3 ẩn name + head-split |  14.9% (Δ +0.9 [-0.2; +1.9]) |  22.3% (Δ +0.6 [-0.7; +2.2]) |  15.2% (Δ +3.4 [+1.2; +5.7]) |  49.5% (Δ+13.6 [+9.9; +17.6]) |
| V4 name cuối + head-split |  13.8% (Δ -0.3 [-1.2; +0.6]) |  21.2% (Δ -0.5 [-1.8; +0.7]) |  16.2% (Δ +4.4 [+1.9; +7.0]) |  48.4% (Δ+12.5 [+8.8; +16.1]) |

### Bài A2 — catalog thu nhỏ 76 quan hệ / 30 loại (cỡ schema của người dùng), 70 chunk

| Biến thể | Rel R@15 | Rel R@30 | Type R@10 | Type R@25 |
|---|---|---|---|---|
| V0 hiện tại (name head 3x) |  39.4% |  56.1% |  33.5% |  85.8% |
| V1 ẩn name (D) |  37.3% (Δ -2.0 [-4.3; +0.1]) |  58.6% (Δ +2.5 [-0.7; +5.7]) |  36.3% (Δ +2.8 [-0.5; +6.3]) |  90.4% (Δ +4.6 [+1.8; +7.7]) |
| V2 name xuống cuối (C) |  39.1% (Δ -0.3 [-1.6; +1.0]) |  57.8% (Δ +1.7 [-1.4; +4.9]) |  35.0% (Δ +1.5 [-1.6; +4.7]) |  89.9% (Δ +4.1 [+0.6; +8.4]) |
| V3 ẩn name + head-split |  37.3% (Δ -2.0 [-4.4; +0.1]) |  58.6% (Δ +2.5 [-0.5; +5.6]) |  36.3% (Δ +2.8 [-0.5; +6.2]) |  90.4% (Δ +4.6 [+2.0; +7.4]) |
| V4 name cuối + head-split |  39.1% (Δ -0.3 [-1.7; +1.1]) |  57.8% (Δ +1.7 [-1.4; +4.9]) |  35.0% (Δ +1.5 [-1.6; +4.5]) |  89.9% (Δ +4.1 [+0.5; +8.3]) |

### Bài B — Target Alignment: gold = canonical người dùng đã chọn khi gộp


**relations** — n = 51 đề xuất đã gộp | sanity (truy vấn bằng chính mục catalog → Top-1): 100%

| Biến thể passage | Top-1 | Top-3 | Auto≥0.86: phủ / đúng | Auto≥0.60: phủ / đúng |
|---|---|---|---|---|
| A0 hiện tại | 2.0% | 7.8% | 1 / 0 | 11 / 1 |
| A1 name cuối | 2.0% | 7.8% | 1 / 0 | 11 / 1 |
| A2 name cuối + head-split | 2.0% | 7.8% | 1 / 0 | 11 / 1 |

| Luật khớp chính xác (duy nhất) | Kích hoạt | Đúng | Mơ hồ (>1 mục) |
|---|---|---|---|
| R-raw alias, KHÔNG loại rò rỉ (sai phương pháp — chỉ để minh họa) | 51 | 51 | 0 |
| R-norm alias (LOO, chuẩn hóa 2 phía) | 0 | 0 | 0 |
| R-norm alias + cụm mô tả (LOO) | 0 | 0 | 0 |

**entity_types** — n = 286 đề xuất đã gộp | sanity (truy vấn bằng chính mục catalog → Top-1): 100%

| Biến thể passage | Top-1 | Top-3 | Auto≥0.86: phủ / đúng | Auto≥0.60: phủ / đúng |
|---|---|---|---|---|
| A0 hiện tại | 3.8% | 9.8% | 0 / 0 | 18 / 0 |
| A1 name cuối | 5.2% | 9.4% | 0 / 0 | 16 / 0 |
| A2 name cuối + head-split | 5.2% | 9.4% | 0 / 0 | 16 / 0 |

| Luật khớp chính xác (duy nhất) | Kích hoạt | Đúng | Mơ hồ (>1 mục) |
|---|---|---|---|
| R-raw alias, KHÔNG loại rò rỉ (sai phương pháp — chỉ để minh họa) | 286 | 286 | 0 |
| R-norm alias (LOO, chuẩn hóa 2 phía) | 0 | 0 | 0 |
| R-norm alias + cụm mô tả (LOO) | 0 | 0 | 0 |

## Dự án `hanoiqa6` — tên snake_case có dấu tiếng Việt (1 token)

- Catalog: 726 quan hệ, 300 loại | Chunk có gold: 29 | gold quan hệ: 873, gold loại: 599


### Bài A1 — Schema Retriever (+R), catalog ĐẦY ĐỦ: Recall trung bình theo chunk (Δ so với V0, [CI95 bootstrap theo chunk])

| Biến thể | Rel R@15 | Rel R@30 | Type R@10 | Type R@25 |
|---|---|---|---|---|
| V0 hiện tại (name head 3x) |   8.0% |  13.1% |   6.6% |  15.8% |
| V1 ẩn name (D) |   7.2% (Δ -0.7 [-1.6; -0.0]) |  12.7% (Δ -0.4 [-1.4; +0.5]) |   5.4% (Δ -1.1 [-2.2; -0.1]) |  16.1% (Δ +0.3 [-1.4; +2.0]) |
| V2 name xuống cuối (C) |   7.0% (Δ -1.0 [-1.8; -0.2]) |  12.5% (Δ -0.6 [-1.8; +0.4]) |   5.1% (Δ -1.5 [-2.5; -0.5]) |  15.5% (Δ -0.3 [-2.1; +1.5]) |
| V3 ẩn name + head-split |   7.2% (Δ -0.7 [-1.5; -0.0]) |  12.7% (Δ -0.4 [-1.3; +0.5]) |   5.4% (Δ -1.1 [-2.3; -0.1]) |  16.1% (Δ +0.3 [-1.4; +2.0]) |
| V4 name cuối + head-split |   7.0% (Δ -1.0 [-1.9; -0.2]) |  12.5% (Δ -0.6 [-1.8; +0.5]) |   5.1% (Δ -1.5 [-2.5; -0.5]) |  15.5% (Δ -0.3 [-2.1; +1.5]) |

### Bài A2 — catalog thu nhỏ 76 quan hệ / 30 loại (cỡ schema của người dùng), 29 chunk

| Biến thể | Rel R@15 | Rel R@30 | Type R@10 | Type R@25 |
|---|---|---|---|---|
| V0 hiện tại (name head 3x) |  33.8% |  61.1% |  40.4% |  84.2% |
| V1 ẩn name (D) |  39.8% (Δ +6.0 [-2.2; +16.0]) |  61.3% (Δ +0.2 [-9.9; +8.0]) |  39.4% (Δ -1.1 [-5.0; +2.9]) |  88.6% (Δ +4.4 [+0.0; +9.1]) |
| V2 name xuống cuối (C) |  40.2% (Δ +6.4 [-1.5; +15.6]) |  63.0% (Δ +1.8 [-7.4; +9.0]) |  41.7% (Δ +1.3 [-2.3; +4.9]) |  88.4% (Δ +4.2 [+0.7; +7.7]) |
| V3 ẩn name + head-split |  39.8% (Δ +6.0 [-2.0; +14.9]) |  61.3% (Δ +0.2 [-9.9; +8.5]) |  39.4% (Δ -1.1 [-4.9; +2.8]) |  88.6% (Δ +4.4 [+0.1; +9.1]) |
| V4 name cuối + head-split |  40.2% (Δ +6.4 [-1.7; +16.1]) |  63.0% (Δ +1.8 [-7.3; +9.1]) |  41.7% (Δ +1.3 [-2.5; +5.1]) |  88.4% (Δ +4.2 [+0.7; +7.9]) |

### Bài B — Target Alignment: gold = canonical người dùng đã chọn khi gộp

_Không có đề xuất `merged` hợp lệ để làm gold._


## Dự án `test1` — tên tiếng Việt có khoảng trắng (name mang tín hiệu thật)

- Catalog: 173 quan hệ, 63 loại | Chunk có gold: 6 | gold quan hệ: 194, gold loại: 105


### Bài A1 — Schema Retriever (+R), catalog ĐẦY ĐỦ: Recall trung bình theo chunk (Δ so với V0, [CI95 bootstrap theo chunk])

| Biến thể | Rel R@15 | Rel R@30 | Type R@10 | Type R@25 |
|---|---|---|---|---|
| V0 hiện tại (name head 3x) |  25.1% |  44.1% |  23.9% |  61.8% |
| V1 ẩn name (D) |  23.0% (Δ -2.2 [-4.4; -0.5]) |  43.6% (Δ -0.5 [-3.6; +2.7]) |  26.4% (Δ +2.5 [+0.0; +5.5]) |  61.5% (Δ -0.2 [-2.9; +2.3]) |
| V2 name xuống cuối (C) |  23.9% (Δ -1.2 [-3.9; +1.0]) |  43.0% (Δ -1.1 [-4.1; +1.9]) |  27.6% (Δ +3.7 [+1.0; +6.7]) |  62.4% (Δ +0.6 [-4.7; +4.8]) |
| V3 ẩn name + head-split |  23.0% (Δ -2.2 [-4.4; -0.5]) |  43.6% (Δ -0.5 [-3.6; +3.1]) |  26.4% (Δ +2.5 [+0.0; +5.5]) |  61.5% (Δ -0.2 [-2.9; +2.3]) |
| V4 name cuối + head-split |  23.9% (Δ -1.2 [-3.9; +1.0]) |  43.0% (Δ -1.1 [-4.1; +1.9]) |  27.6% (Δ +3.7 [+1.0; +6.7]) |  62.4% (Δ +0.6 [-5.1; +4.6]) |

### Bài A2 — catalog thu nhỏ 76 quan hệ / 30 loại (cỡ schema của người dùng), 6 chunk

| Biến thể | Rel R@15 | Rel R@30 | Type R@10 | Type R@25 |
|---|---|---|---|---|
| V0 hiện tại (name head 3x) |  42.3% |  71.8% |  43.0% |  89.5% |
| V1 ẩn name (D) |  43.0% (Δ +0.7 [-6.8; +9.5]) |  68.5% (Δ -3.3 [-10.0; +1.1]) |  44.3% (Δ +1.3 [+0.0; +3.8]) |  89.8% (Δ +0.3 [-4.9; +5.6]) |
| V2 name xuống cuối (C) |  41.7% (Δ -0.6 [-1.7; +0.0]) |  64.6% (Δ -7.2 [-13.3; -1.1]) |  43.1% (Δ +0.1 [-3.6; +3.8]) |  91.0% (Δ +1.5 [+0.0; +4.5]) |
| V3 ẩn name + head-split |  43.0% (Δ +0.7 [-6.2; +9.4]) |  68.5% (Δ -3.3 [-10.0; +1.2]) |  44.3% (Δ +1.3 [+0.0; +3.8]) |  89.8% (Δ +0.3 [-4.9; +5.6]) |
| V4 name cuối + head-split |  41.7% (Δ -0.6 [-1.7; +0.0]) |  64.6% (Δ -7.2 [-13.9; -1.1]) |  43.1% (Δ +0.1 [-3.6; +3.8]) |  91.0% (Δ +1.5 [+0.0; +4.5]) |

### Bài B — Target Alignment: gold = canonical người dùng đã chọn khi gộp

_Không có đề xuất `merged` hợp lệ để làm gold._

