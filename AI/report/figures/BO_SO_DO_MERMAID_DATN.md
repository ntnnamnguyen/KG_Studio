# Bộ Sơ Đồ Luồng (Mermaid Markdown) & Hình Ảnh Thực Nghiệm ĐATN (Chuẩn Mẫu ĐHBK Hà Nội)

Tài liệu này tổng hợp toàn bộ **11 Hình vẽ (`Hình 1.1` đến `Hình 5.2`)** của quyển Báo cáo Đồ án Tốt nghiệp.
- **Cách sử dụng mã Mermaid:** Em chỉ cần copy khối code `mermaid` bên dưới và dán thẳng vào:
  1. **Mermaid Live Editor:** https://mermaid.live (xuất ra PNG/SVG độ phân giải cao chỉ với 1 cú nhấp chuột).
  2. **Draw.io (diagrams.net):** Vào menu `Arrange` -> `Insert` -> `Advanced` -> `Mermaid...` rồi dán mã vào để chỉnh sửa màu sắc, font chữ tùy ý.
  3. **Notion / Obsidian / VS Code Markdown Preview:** Hiển thị trực tiếp ngay khi dán.

---

## CHƯƠNG 1. GIỚI THIỆU ĐỀ TÀI

### Hình 1.1: Minh họa sự phân mảnh vị từ của trích xuất tự do (Free Triples) so với đồ thị chuẩn hóa EDC+R trên tư liệu lịch sử Hà Nội

- **File ảnh PNG 300 DPI đã vẽ sẵn:** `AI/report/figures/hinh_1_1_free_triples_vs_edc_r.png`
- **Mã Mermaid tương đương (nếu em muốn đưa lên công cụ vẽ sơ đồ luồng):**

```mermaid
flowchart TB
    Chunk["Đoạn tư liệu đầu vào c_i: Chùa Một Cột (Diên Hựu tự) tại Ba Đình, Hà Nội được Vua Lý Thái Tông cho xây dựng năm 1049 để thờ Phật Bà Quan Âm"]

    subgraph LeftPanel["(a) Trích xuất tự do (Free Triples - Baseline B: Phân mảnh thực thể và vị từ)"]
        direction LR
        FT_Vua1["Vua Lý Thái Tông (kind: Unknown)"] -->|cho xây dựng| FT_Chua1["Chùa Một Cột (kind: Unknown)"]
        FT_Chua2["Công trình này (Lỗi đồng tham chiếu)"] -->|được dựng bởi| FT_Vua2["Lý Thái Tông (kind: Unknown)"]
        FT_Chua3["Chùa (Nút mơ hồ)"] -->|xây vào năm| FT_Nam["mùa đông năm 1049"]
        FT_DienHuu["Diên Hựu tự (Nút cô lập)"]
        FT_Chua1 -.->|Cạnh tự nối lỗi: là ngôi chùa cổ| FT_Chua1
    end

    subgraph RightPanel["(b) Đồ thị chuẩn hóa EDC+R và Kiểm duyệt có con người (Đề xuất)"]
        direction TB
        EDCR_Chua["Chùa Một Cột | kind: Monument (E22) | aliases: Diên Hựu tự, Liên Hoa Đài"]
        EDCR_Vua["Lý Thái Tông | kind: Person (E21) | aliases: Vua Lý Thái Tông"]
        EDCR_Place["Quận Ba Đình, Hà Nội | kind: Place (E53)"]
        EDCR_Period["Thời Lý (Năm 1049) | kind: HistoricalPeriod (E4)"]
        EDCR_Deity["Phật Bà Quan Âm | kind: Deity / Person"]

        EDCR_Chua -->|"BUILT_BY (được xây dựng bởi) [Gộp 2 bằng chứng]"| EDCR_Vua
        EDCR_Chua -->|"LOCATED_IN (nằm tại) [Hợp lệ]"| EDCR_Place
        EDCR_Chua -->|"OCCURRED_DURING (diễn ra vào thời kỳ) [Hợp lệ]"| EDCR_Period
        EDCR_Chua -->|"DEDICATED_TO (thờ phụng) [Hợp lệ]"| EDCR_Deity
    end

    Chunk --> LeftPanel
    Chunk --> RightPanel
```

---

## CHƯƠNG 2. NỀN TẢNG LÝ THUYẾT

### Hình 2.1: Kiến trúc ba pha của khung trích xuất Extract–Define–Canonicalize (EDC) và cơ chế mở rộng truy xuất lược đồ

```mermaid
flowchart LR
    Doc["Đoạn văn bản lịch sử c_i"] --> SR["Bộ truy xuất lược đồ (+R: SchemaRetriever)"]
    Catalog[("Danh mục Lược đồ Song ngữ (CIDOC CRM)")] --> SR
    SR -->|"Top-K ứng viên loại và quan hệ"| P1

    subgraph EDC_Pipeline["Khung ba pha Extract - Define - Canonicalize (EDC)"]
        direction LR
        P1["Pha 1: Open Extraction (Trích xuất bộ ba mở giữ ngữ cảnh)"]
        P2["Pha 2: Schema Definition (Sinh định nghĩa ngữ nghĩa cho nhãn mới)"]
        P3["Pha 3: Schema Canonicalization (Ánh xạ về định danh chuẩn hoặc đề xuất mới)"]
        P1 -->|"Bộ ba mở (h, r_raw, t)"| P2
        P2 -->|"Định nghĩa d(r_raw)"| P3
    end

    Doc --> P1
    Catalog --> P3
    P3 -->|"Bộ ba chuẩn hóa (h, r_canon, t) + Bằng chứng"| OutKG["Đồ thị Tri thức Ứng viên"]
    P3 -.->|"Nhãn mới chưa có trong DM"| Proposal["Hàng đợi Đề xuất Lược đồ (Schema Proposals)"]
```

---

## CHƯƠNG 3. PHƯƠNG PHÁP ĐỀ XUẤT

### Hình 3.1: Sơ đồ luồng hoạt động tổng thể của giải pháp xây dựng và kiểm duyệt Đồ thị Tri thức di sản Hà Nội

```mermaid
flowchart TD
    subgraph Stage1["Giai đoạn 1: Tiền xử lý Tư liệu và Gợi ý Bí danh"]
        RawDoc["Tư liệu lịch sử - văn hóa Hà Nội"] --> Chunker["Phân đoạn văn bản có chồng lấp (Overlapping Chunking)"]
        Gaz[("Từ điển Bí danh Dự án (domain_gazetteer)")] -->|"Bơm gợi ý danh xưng lịch sử"| Chunker
    end

    subgraph Stage2["Giai đoạn 2: Trích xuất Thông tin Đa chế độ và Truy xuất Lược đồ"]
        Chunker --> ModeSelect{"4 Cơ chế Trích xuất (Đối sánh RQ1)"}
        ModeSelect --> M_Free["1. Free Triples (Baseline B: surface-nfc-casefold-v1)"]
        ModeSelect --> M_Closed["2. Closed IE (Ép lược đồ cố định)"]
        ModeSelect --> M_EDC["3. EDC nguyên bản (Extract - Define - Canonicalize)"]
        ModeSelect --> M_EDCR["4. EDC+R Đề xuất (SchemaRetriever V1/V2 + Target Alignment)"]
    end

    subgraph Stage3["Giai đoạn 3: Hậu kiểm Toàn vẹn và Nạp Đồ thị"]
        M_Closed & M_EDC & M_EDCR --> Validator["Hậu kiểm ingest_extraction (Kiểm tra Domain-Range, Bằng chứng và Provenance)"]
    end

    subgraph Stage4["Giai đoạn 4: Kiểm duyệt có Con người trong Vòng lặp (RQ2)"]
        Validator --> Curation["Trung tâm Kiểm duyệt (Duyệt lô All-or-Nothing / Valid-Only, Chặn cạnh tự nối)"]
        Curation --> Merge["Hợp nhất Thực thể và Quan hệ Không mất mát (Lossless Merge)"]
        Merge -->|"Tự động thu hoạch bí danh theo khóa (canonical_norm, kind)"| Gaz
        Merge --> ApprovedKG[("Đồ thị Tri thức Đã Duyệt (Approved Graph)")]
    end

    subgraph Stage5["Giai đoạn 5: Truy xuất Đồ thị con Hạ nguồn và Đóng gói G-Retriever (RQ3)"]
        ApprovedKG --> SubgraphRet["Truy xuất Đồ thị con: Naive Top-K vs HippoRAG (PPR) vs G-Retriever (Hub-Penalized PCST)"]
        ApprovedKG --> BundleExp["Phân hoạch Union-Find Disjoint Split và Xuất Gói 5 Tệp Chuẩn G-Retriever"]
    end
```

---

### Hình 3.2: So sánh cấu trúc biểu diễn văn bản mục tiêu V0 (nhiễu định danh tiếng Anh) với V1 và V2 trong SchemaRetriever song ngữ

```mermaid
flowchart LR
    Query["Câu văn truy vấn tiếng Việt c_i: Chùa Một Cột nằm ở quận Ba Đình, được Lý Thái Tông xây năm 1049"] --> EmbQ["Vector nhúng câu văn E(c_i)"]

    subgraph SchemaItem["Mục Lược đồ trong Danh mục Song ngữ (s)"]
        S_Info["name: P53_has_former_or_current_location | label_vi: tọa lạc tại | desc_vi: Vị trí địa lý hiện tại hoặc trước đây của di tích"]
    end

    S_Info --> V0["Cấu hình V0 (Baseline): Lặp 3 lần khóa tiếng Anh ở đầu câu T_V0(s) = name + name + name + desc_vi"]
    S_Info --> V1["Cấu hình V1 (Đề xuất 1): Ẩn khóa kỹ thuật, chỉ nhúng tiếng Việt T_V1(s) = label_vi + desc_vi + aliases_vi"]
    S_Info --> V2["Cấu hình V2 (Đề xuất 2): Ưu tiên tiếng Việt ở đầu, khóa ở cuối T_V2(s) = label_vi + desc_vi + aliases_vi + [name]"]

    V0 -->|"Nhiễu định danh tiếng Anh (Identifier Dominance)"| ScoreV0["Type R@25 = 35,9% (Bài A1) / 85,8% (Bài A2)"]
    V1 -->|"Đồng nhất không gian ngữ nghĩa tiếng Việt"| ScoreV1["Type R@25 = 49,5% (+13,6% ở Bài A1) / 90,4% (Bài A2)"]
    V2 -->|"Giữ thông tin khóa kỹ thuật không gây nhiễu đầu câu"| ScoreV2["Type R@10 = 16,2% (+4,4% ở Bài A1) / R@30 = 63,0% (Bài A2)"]

    EmbQ -.->|"So khớp Cosine + Lexical Overlap"| ScoreV0
    EmbQ -->|"So khớp Cosine + Lexical Overlap"| ScoreV1
    EmbQ -->|"So khớp Cosine + Lexical Overlap"| ScoreV2
```

---

### Hình 3.3: Cơ chế hợp nhất thực thể không mất mát (Lossless Merge) và vòng lặp thu hoạch từ điển bí danh bảo toàn ranh giới đồng âm theo loại (kind)

```mermaid
flowchart TD
    subgraph PartA["Phần A: Hợp nhất Thực thể Không mất mát (Lossless Entity Merge)"]
        N_Dup1["Đỉnh trùng #1: Lý Công Uẩn (kind: Person) | Cạnh: sáng lập -> Thăng Long (Ev1)"]
        N_Dup2["Đỉnh trùng #2: Vua Lý Thái Tổ (kind: Person) | Cạnh: sáng lập -> Thăng Long (Ev2)"]
        N_Target["Đỉnh đích chuẩn: Lý Thái Tổ (kind: Person)"]

        N_Dup1 & N_Dup2 -->|"Hợp nhất thực thể (merge_entities)"| MergeOp["Bảo toàn 100% thông tin: 1. Gộp aliases: Lý Công Uẩn, Vua Lý Thái Tổ | 2. Cộng dồn bằng chứng cạnh trùng: Ev1 U Ev2 | 3. Lưu bảng chuyển hướng redirects và audit_log"]
        MergeOp --> N_Target
    end

    subgraph PartB["Phần B: Vòng lặp Thu hoạch Từ điển Bí danh Bảo toàn Ranh giới Đồng âm theo Loại (kind)"]
        N_Target -->|"enrich_gazetteer_from_merge"| KeyGen["Sinh khóa phân biệt đồng âm: K_gaz(v) = (NFC_casefold(label), kind)"]
        KeyGen --> EntryPerson["Khóa 1: ('le loi', 'Person') -> Thực thể: Vua Lê Lợi | Bí danh: Lê Thái Tổ, Bình Định Vương"]
        KeyGen --> EntryPlace["Khóa 2: ('le loi', 'Place') -> Thực thể: Phố Lê Lợi | Bí danh: Đường Lê Lợi (Quận Hà Đông)"]
        EntryPerson -.->|"Chặn gộp chéo khác loại bản thể (Person != Place)"| EntryPlace
    end
```

---

### Hình 3.4: Quy trình truy xuất đồ thị con PCST có phạt bậc siêu nút và phân hoạch thành phần liên thông Union-Find xuất gói 5 tệp G-Retriever

```mermaid
flowchart TD
    AppGraph[("Đồ thị Đã Duyệt (Approved Graph: V_app, E_app)")]

    subgraph OnlineBranch["Nhánh 1: Truy xuất Đồ thị con Trực tuyến (GraphRAG / G-Retriever)"]
        Q["Câu hỏi người dùng q"] --> HybridIdx["Chỉ mục Đồ thị Lai (Lexical IDF + N-Gram + Phrase Matcher)"]
        AppGraph --> HybridIdx
        HybridIdx --> PrizeCalc["Tính thưởng đỉnh có phạt bậc siêu nút: p(v) = p_raw(v, q) / (1 + beta * ln(1 + deg(v)))"]
        PrizeCalc --> PCST["Giải cây khung Steiner PCST + Mở rộng thuộc tính lá 1-Hop và cầu nối 2-Hop Bridge"]
        PCST --> SubG["Đồ thị con liên thông + Trích dẫn bằng chứng nguyên văn"]
    end

    subgraph OfflineBranch["Nhánh 2: Đóng gói 5 Tệp Chuẩn Huấn luyện G-Retriever Chống Rò rỉ"]
        AppGraph --> QAGen["Sinh câu hỏi đa bước (1-Hop, 2-Hop Bridge, Intersection, Multi-Attribute)"]
        QAGen --> Guard["Bộ lọc hậu nghiệm thuần Việt: Giữ nguyên thực thể neo và loại bỏ 100% câu lẫn khóa tiếng Anh"]
        Guard --> UF["Thuật toán Union-Find: Gom các câu hỏi dùng chung đỉnh/cạnh vào cùng thành phần liên thông C_j"]
        UF --> Split["Phân hoạch nguyên khối C_j vào Train / Val / Test (Đảm bảo E_gold(Train) giao E_gold(Test) = Rỗng)"]
        Split --> Bundle5["Xuất gói 5 tệp: nodes.csv, edges.csv, evidence.csv, questions.csv, schema_contract.json"]
    end
```

---

## CHƯƠNG 4. PHÂN TÍCH LÝ THUYẾT VÀ THIẾT KẾ HỆ THỐNG THỰC NGHIỆM

### Hình 4.1: Kiến trúc Modular Monolith sáu phân hệ nghiệp vụ và cơ chế kiểm soát ranh giới qua giao diện .public của hệ thống KG Studio

```mermaid
flowchart TD
    subgraph UI_Layer["Tầng Giao diện Hướng Nhiệm vụ (Streamlit 5 Trang)"]
        P01["Trang 1 (p01): Quản lý Dự án & Cấu hình"]
        P02["Trang 2 (p02): Danh mục Lược đồ, Gazetteer & Prompt"]
        P03["Trang 3 (p03): Tài liệu & Trích xuất 4 Chế độ"]
        P04["Trang 4 (p04): Trung tâm Kiểm duyệt & Gộp Thực thể"]
        P05["Trang 5 (p05): Khám phá Đồ thị, Hỏi đáp & Xuất 5 Tệp G-Retriever"]
    end

    subgraph Comp_Layer["Tầng Lắp ghép Phụ thuộc (Composition Root & AST Boundary Guard)"]
        FrontComp["frontend/composition.py"] --> Bootstrap["backend/bootstrap.py (Lắp ghép Ports & Adapters, kiểm soát bởi 8 quy tắc AST)"]
    end

    subgraph Modules_Layer["Tầng Sáu Phân hệ Nghiệp vụ Độc lập (Chỉ giao tiếp qua cổng .public)"]
        M1["1. projects (.public)"]
        M2["2. schema_intelligence (.public)"]
        M3["3. extraction (.public)"]
        M4["4. curation (.public)"]
        M5["5. graph_qa (.public)"]
        M6["6. training (.public)"]
    end

    subgraph Storage_Layer["Tầng Lưu trữ Ba Lớp được Điều phối bởi ProjectCommitCoordinator"]
        SSOT[("1. Authoritative SSOT: Gói JSON dự án (Ghi nguyên tử .tmp + os.replace)")]
        SQLite[("2. Read Projection: SQLite (Phân trang siêu tốc + Cờ sync_pending / resync)")]
        VecIdx[("3. Derived Index: Chỉ mục Vector phân vùng .npz (nodes, chunks, schema)")]
    end

    P01 & P02 & P03 & P04 & P05 --> FrontComp
    Bootstrap --> M1 & M2 & M3 & M4 & M5 & M6
    M2 & M3 & M4 & M5 & M6 -->|"Mọi thao tác ghi đi qua CommitCoordinatorPort"| M1
    M1 --> SSOT
    M1 --> SQLite
    M1 --> VecIdx
```

---

### Hình 4.2: Biểu đồ tuần tự giao thức cam kết 8 bước của ProjectCommitCoordinator đồng bộ JSON SSOT, SQLite và chỉ mục Vector .npz

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Dịch vụ Phân hệ (curation / extraction / schema)
    participant Coord as ProjectCommitCoordinator
    participant Snap as SnapshotStore
    participant JSON as JSONBundleStore (SSOT)
    participant Proj as SQLite & Vector Index (Derived)

    Caller->>Coord: commit(project_id, expected_revision, idempotency_key, mutator_fn)
    activate Coord
    Note over Coord: Bước 1: Chiếm khóa đồng bộ RLock theo project_id
    Coord->>JSON: Đọc trạng thái hiện hành và kiểm tra expected_revision (Bước 2)
    Note over Coord: Bước 3: Kiểm tra mã băm idempotency_key chống thực thi lặp
    Coord->>Snap: Bước 4: Tạo bản sao lưu an toàn (create_snapshot)
    Snap-->>Coord: Trả về đường dẫn snapshot_path
    Note over Coord: Bước 5: Thực thi mutator_fn(candidate_copy) trên bản sao độc lập
    alt Ghi nguyên tử JSON SSOT thành công
        Coord->>JSON: Bước 6: Ghi tệp tạm .tmp + fsync + os.replace và tăng revision
        JSON-->>Coord: Xác nhận cam kết SSOT thành công
        Coord->>Proj: Bước 7: Đồng bộ bản chiếu SQLite và chỉ mục Vector .npz
        alt Đồng bộ SQLite gặp lỗi phụ
            Proj-->>Coord: Báo lỗi đồng bộ bản chiếu
            Note over Coord: Bật cờ sync_pending = True và ghi sync_error (Không làm hỏng SSOT)
        else Đồng bộ thành công
            Proj-->>Coord: Bản chiếu đọc khớp revision mới
        end
        Coord-->>Caller: Bước 8: Cập nhật bộ nhớ và trả về CommitResult thành công
    else Xảy ra lỗi trong quá trình biến đổi hoặc ghi SSOT
        Coord->>Snap: Tự động khôi phục dữ liệu từ snapshot_path (Rollback)
        Snap-->>Coord: Khôi phục hoàn tất
        Coord-->>Caller: Ném ngoại lệ chẩn đoán rõ ràng (Bảo toàn 100% trạng thái cũ)
    end
    deactivate Coord
```

---

## CHƯƠNG 5. ĐÁNH GIÁ THỰC NGHIỆM

### Hình 5.1: Biểu đồ so sánh Recall@K của SchemaRetriever giữa các biến thể V0, V1, V2 trên danh mục đầy đủ (Bài A1) và danh mục tinh gọn (Bài A2)

- **File ảnh PNG 300 DPI đã vẽ sẵn (khuyên dùng chèn trực tiếp vào Word):** `AI/report/figures/hinh_5_1_schema_retriever_recall.png`
- **Mã Mermaid `xychart-beta` tương đương:**

```mermaid
xychart-beta
    title "So sánh Recall@K (%) của SchemaRetriever giữa V0 (Đỏ), V1 (Xanh dương) và V2 (Xanh lá)"
    x-axis ["A1: Rel R@15", "A1: Rel R@30", "A1: Type R@10", "A1: Type R@25", "A2: Rel R@30", "A2: Type R@25"]
    y-axis "Tỷ lệ thu hồi Recall (%)" 0 --> 100
    bar [14.0, 21.7, 11.7, 35.9, 56.1, 85.8]
    bar [14.5, 22.8, 14.3, 49.5, 58.6, 90.4]
    bar [14.1, 22.0, 16.2, 46.8, 63.0, 88.4]
```

---

### Hình 5.2: Biểu đồ đối sánh tỷ lệ thu hồi đáp án đích, thu hồi cạnh chuẩn và nối mạch 2-Hop Bridge giữa Naive Top-K, PPR và PCST

- **File ảnh PNG 300 DPI đã vẽ sẵn (khuyên dùng chèn trực tiếp vào Word):** `AI/report/figures/hinh_5_2_subgraph_retrieval_benchmark.png`
- **Mã Mermaid `xychart-beta` tương đương:**

```mermaid
xychart-beta
    title "Đối sánh Naive Top-K, HippoRAG (PPR) và G-Retriever (PCST) trên test_edr_v4 và hanoiqafinal1"
    x-axis ["v4: Đích", "v4: Cạnh", "v4: 2-Hop", "v4: LCC", "final1: Đích", "final1: Cạnh", "final1: 2-Hop"]
    y-axis "Tỷ lệ phần trăm (%)" 0 --> 100
    bar [61.7, 80.0, 27.3, 47.8, 91.7, 92.5, 75.8]
    bar [83.3, 90.8, 66.7, 66.9, 100.0, 96.7, 97.0]
    bar [68.3, 84.2, 42.4, 56.1, 98.3, 97.5, 93.9]
```
