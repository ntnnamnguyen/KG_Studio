# Bộ Sơ Đồ Tinh Gọn Quy Trình Kiểm Duyệt Tri Thức 3 Bước (KG Studio)

> Tệp này chứa **4 sơ đồ Mermaid tinh gọn** theo đúng **Quy trình Kiểm duyệt 3 Bước Tuyến tính** (khớp 1–1 với 4 khung chừa sẵn trong [Bao_Cao_Cong_Cu_Kiem_Duyet_KG_Studio.docx](Bao_Cao_Cong_Cu_Kiem_Duyet_KG_Studio.docx)).  
> **Cách sử dụng:** Mở từng khối ```mermaid``` bằng [Mermaid Live Editor](https://mermaid.live/) hoặc tiện ích Mermaid trong VS Code, xuất ảnh PNG/SVG rồi dán vào đúng khung `[KHUNG CHỪA SẴN ĐỂ CHÈN SƠ ĐỒ X.1]` trong tệp Word.

---

## Sơ đồ 1.1 — Kiến trúc Quy trình Kiểm duyệt 3 Bước Tuyến tính (Luồng chính EDC+R)

- **Vị trí trong Word:** `Mục 1 — Tổng quan Quy trình Kiểm duyệt 3 Bước trên KG Studio` (Chèn vào `Hình 1.1`).
- **Nội dung thể hiện:** Đường đi thẳng, không chồng chéo từ kết quả trích xuất LLM qua 3 bước nối tiếp nhau để cho ra Đồ thị Tri thức sạch chuẩn `CIDOC CRM`, cùng vòng phản hồi từ điển bí danh về lần trích xuất sau.

```mermaid
flowchart LR
    RAW["Kết quả trích xuất thô từ LLM<br/>(Đỉnh, Cạnh, Trích dẫn, Đề xuất nhãn mở)"] --> B1

    subgraph B1["BƯỚC 1: Chuẩn hóa Nhãn Lược đồ"]
        B1A["TargetAligner + LLM Verifier<br/>• Điểm >= 0,86 & Verifier đồng ý: Tự động gộp<br/>• Điểm 0,45..0,86: Gợi ý Top-5 cho người duyệt<br/>• Mở rộng riêng cho EDC mở: Gộp bề mặt / AI Clustering"]
    end

    subgraph B2["BƯỚC 2: Gộp Thực thể & Bí danh"]
        B2A["Entity Merge + domain_gazetteer<br/>• Quét trùng tên / bí danh (SequenceMatcher >= 0,82)<br/>• Preview kiểm tra khác loại -> Apply giữ đủ cạnh<br/>• Lưu bí danh vào từ điển chung cho vòng sau"]
    end

    subgraph B3["BƯỚC 3: Làm sạch Cạnh & Chốt duyệt"]
        B3A["Triple Dedup + Cổng Bằng chứng<br/>• Gom cạnh trùng bộ ba (giữ đủ mọi evidences)<br/>• Cô lập cạnh tự nối (source == target -> Loại bỏ)<br/>• Chỉ 'Đã duyệt' khi trích dẫn khớp văn bản gốc"]
    end

    B1 --> B2 --> B3 --> CLEAN["Đồ thị Tri thức Sạch chuẩn CIDOC CRM<br/>(Lưu SSOT qua ProjectCommitCoordinator)"]
    B2 -. "Vòng lặp phản hồi O(1)<br/>(domain_gazetteer & aliases)" .-> RAW

    style B1 fill:#EFF6FF,stroke:#2563EB,stroke-width:1.5px
    style B2 fill:#FFFBEB,stroke:#D97706,stroke-width:1.5px
    style B3 fill:#ECFDF5,stroke:#059669,stroke-width:1.5px
    style CLEAN fill:#F0FDF4,stroke:#15803D,stroke-width:1.8px
```

---

## Sơ đồ 2.1 — Bước 1: Cơ chế Chấm điểm & Gợi ý Mục đích gần nhất (`TargetAligner`)

- **Vị trí trong Word:** `Mục 2 — Bước 1: Chuẩn hóa Nhãn Lược đồ (Target Alignment & LLM Verifier)` (Chèn vào `Hình 2.1`).
- **Nội dung thể hiện:** Cách `TargetAligner` tính điểm giữa nhãn mở LLM trả ra với danh mục chuẩn `CIDOC CRM`, lý do chạy `entity_types` trước `relations`, phân vùng 3 ngưỡng (`0,45` và `0,86`) và cơ chế an toàn `Fail-Closed` của `LLM Verifier`.

```mermaid
flowchart TD
    INP["Nhãn mở mới do LLM đề xuất<br/>(open_name + open_definition)"] --> ORDER["Thứ tự xử lý:<br/>1. Chuẩn hóa Loại Thực thể (entity_types) trước<br/>2. Chuẩn hóa Quan hệ (relations) sau để thấy rõ cặp Domain->Range"]
    ORDER --> VEC["So khớp Vector với Danh mục chuẩn CIDOC CRM<br/>• Truy vấn: open_name + open_definition<br/>• Đích: name + definition + description + Scope + Aliases"]

    VEC --> COS["Tính điểm tương đồng Cosine (0,00 .. 1,00)<br/>(Nếu trùng tên chuẩn hóa -> Ép score = 1,00)"]
    COS --> ZONES{"Phân loại theo 2 ngưỡng<br/>0,45 và 0,86"}

    ZONES -- "Dưới 0,45<br/>(Khái niệm mới)" --> NOVEL["Giữ 'pending' (không có gợi ý)<br/>Người duyệt tự tạo mục mới hoặc Từ chối"]
    ZONES -- "Từ 0,45 đến dưới 0,86<br/>(Vùng gợi ý chính)" --> SUG["Giữ 'pending' + Điền sẵn Top-5 gợi ý<br/>Chờ người kiểm duyệt bấm Hợp nhất nhanh ở Trang 4"]
    ZONES -- "Từ 0,86 trở lên<br/>(Ngưỡng tự động)" --> VER{"Có bật LLM Verifier?"}

    VER -- "Tắt" --> AUTO["Tự động hợp nhất -> status = 'merged'<br/>Cập nhật thẳng nhãn chuẩn vào nút/cạnh chưa duyệt"]
    VER -- "Bật" --> ASK["LLM chọn Top-5 phương án A..E (kèm ví dụ & Domain->Range)<br/>hoặc chọn 'Không tương đương'"]
    ASK --> FC{"Fail-Closed Check:<br/>LLM có chọn đúng A..E và score >= 0,86?"}
    FC -- "Có" --> AUTO2["Tự động gộp (llm_verified_auto)<br/>VD: 'connects with' -> CONNECTS (0,864)"]
    FC -- "Không (Lỗi / Mơ hồ / Không khớp / < 0,86)" --> SUG2["KHÔNG tự gộp -> Giữ 'pending' + Gắn ghi chú gợi ý<br/>VD: 'created' -> PRODUCED (0,851), 'nằm tại' -> LOCATED_IN (0,812)"]

    style NOVEL fill:#FEF2F2,stroke:#DC2626
    style SUG fill:#FFFBEB,stroke:#D97706
    style SUG2 fill:#FFFBEB,stroke:#D97706
    style AUTO fill:#ECFDF5,stroke:#059669
    style AUTO2 fill:#ECFDF5,stroke:#059669
```

---

## Sơ đồ 3.1 — Bước 2: Gộp Thực thể trùng & Vòng lặp Từ điển Bí danh (`domain_gazetteer`)

- **Vị trí trong Word:** `Mục 3 — Bước 2: Gộp Thực thể trùng lặp & Cơ chế Bí danh` (Chèn vào `Hình 3.1`).
- **Nội dung thể hiện:** Cơ chế gom nhóm ứng viên nhanh (Blocking), chấm điểm tương đồng (`SequenceMatcher >= 0,82`), quy trình an toàn `Preview -> Apply`, lưu vết `node_redirects` và phản hồi trực tiếp sang từ điển `domain_gazetteer` cho lần trích xuất tiếp theo.

```mermaid
flowchart TD
    NODES["Các đỉnh thực thể trong đồ thị"] --> CAND["Tìm cặp nghi trùng (duplicate_suggestions)<br/>• Đồ thị >= 80 đỉnh: Blocking theo tên, bí danh, token >= 3 ký tự<br/>• Chấm điểm: Trùng tên / Chéo bí danh / SequenceMatcher >= 0,82"]

    CAND --> PREV["Xem trước Gộp (preview_entity_merge)<br/>• Kiểm tra khác loại: Bắt buộc chọn loại chuẩn + lý do<br/>• Tính trước cạnh đổi đầu mút & cạnh có nguy cơ tự nối"]

    PREV --> APPLY["Thực thi Gộp không mất mát (apply_entity_merge)<br/>1. Dồn toàn bộ cạnh về nút chính keep_id (chuyển về 'Cần kiểm tra')<br/>2. Gộp aliases, danh sách tài liệu, lưu vết merged_from & node_redirects"]

    APPLY --> GAZ["Tự động nạp vào Từ điển Bí danh (domain_gazetteer)<br/>• Ánh xạ O(1): normal(biệt danh) -> {canonical_name, kind}<br/>• Sửa bảng thủ công ngăn cách bằng ';' hoặc '|', chặn gộp chéo xung đột"]

    GAZ -. "Vòng chạy trích xuất tiếp theo<br/>(ensure_node)" .-> NEXT["LLM rút ra tên cũ (VD: 'Lý Công Uẩn')<br/>-> Tự tra domain_gazetteer khớp 'Lý Thái Tổ' ngay lập tức<br/>(Riêng Thực thể yếu 'cổng, chuông, giếng' chỉ gộp trong cùng tài liệu)"]

    style CAND fill:#EFF6FF,stroke:#2563EB
    style PREV fill:#FFFBEB,stroke:#D97706
    style APPLY fill:#ECFDF5,stroke:#059669
    style GAZ fill:#F5F3FF,stroke:#7C3AED
```

---

## Sơ đồ 4.1 — Bước 3: Khử Cạnh Lặp, Cô lập Tự nối & Chốt duyệt Bằng chứng

- **Vị trí trong Word:** `Mục 4 — Bước 3: Làm sạch Cạnh & Chốt duyệt Bằng chứng` (Chèn vào `Hình 4.1`).
- **Nội dung thể hiện:** Ba bước lọc sạch cạnh tuyến tính sau khi nhãn và thực thể đã chuẩn: (1) Gom nhóm cạnh trùng bộ ba bảo toàn mọi trích dẫn, (2) Cô lập cạnh tự nối (`source == target`), và (3) Chỉ chuyển sang `Đã duyệt` khi đủ điều kiện lược đồ và bằng chứng khớp văn bản gốc.

```mermaid
flowchart TD
    EDGES["Tập cạnh sau khi chuẩn hóa Nhãn & Thực thể"] --> DEDUP

    subgraph DEDUP["3.1 Khử trùng Cạnh Lặp (Triple Deduplication)"]
        D1["Gom nhóm theo bộ ba (Nguồn, Quan hệ, Đích)<br/>(Mở rộng tùy chọn: vị từ mờ / đảo chiều Chủ-Bị động cho EDC mở)"]
        D2["Chọn cạnh đại diện giữ lại:<br/>Đã duyệt (3) > Cần kiểm tra (2) > Chờ duyệt (1), cùng hạng lấy trích dẫn dài hơn"]
        D3["Dồn đủ mọi câu trích dẫn (evidences) vào cạnh giữ lại + ghi edge_redirects"]
        D1 --> D2 --> D3
    end

    DEDUP --> SL{"3.2 Kiểm tra Tự nối<br/>(source == target)?"}
    SL -- "Đúng (Self-loop)" --> REJ["Chặn khỏi duyệt hàng loạt<br/>Tách sang trạng thái 'Loại bỏ' (25/25 ca ở EDC_R_50_place)"]

    SL -- "Không" --> GATE["3.3 Cổng Duyệt Cạnh (validate_edge_for_approval)<br/>• Kiểm tra Quan hệ R, Loại nguồn S, Loại đích T đều thuộc CIDOC CRM<br/>• Đối chiếu trích dẫn trên văn bản gốc (khớp 4 tầng)"]

    GATE -- "Khớp văn bản gốc" --> APP["Cạnh đạt chuẩn 'Đã duyệt'<br/>(4.289 cạnh sạch trên EDC_R_50_place)"]
    GATE -- "Lệch ký tự (ev_mismatch)" --> FIX["Giữ 'Cần kiểm tra'<br/>Gợi ý 1-2 đoạn gần nhất (Lexical Cosine >= 0,40) để người duyệt sửa"]

    style DEDUP fill:#EFF6FF,stroke:#2563EB
    style REJ fill:#FEF2F2,stroke:#DC2626
    style APP fill:#ECFDF5,stroke:#059669
    style FIX fill:#FFFBEB,stroke:#D97706
```
