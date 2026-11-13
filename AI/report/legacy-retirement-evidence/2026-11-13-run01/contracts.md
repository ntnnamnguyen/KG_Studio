# Hợp đồng Kiến trúc & Giao diện Công khai (Contracts)

- **Run ID:** `2026-11-13-run01`
- **Mục tiêu:** Định nghĩa hợp đồng công khai giữa 6 module nghiệp vụ, coordinator commit lifecycle, và ranh giới frontend/backend.

---

## 1. Sáu Module Nghiệp vụ & Public APIs

1. **`backend.modules.projects.public`**
   - `ProjectsApplicationService`: Quản lý vòng đời dự án (create, load, save, restore snapshot), điều phối SQLite projection sync, truy vấn phân trang read projection.
   - `ProjectCommitCoordinator`: Điều phối transaction commit duy nhất của hệ thống (authoritative JSON commit, optimistic locking theo `project_revision`, idempotency cache, rollback và snapshot an toàn).
   - `CommitCoordinatorPort`: Giao diện trừu tượng cho coordinator, bao gồm `get_project_lock(project_id: str) -> threading.RLock` và `commit(...)`.
   - `ProjectStorePort`, `ReadProjectionPort`: Ports lưu trữ và đọc projection.
2. **`backend.modules.schema_intelligence.public`**
   - `SchemaIntelligenceApplicationService`: Khởi tạo EDC, đề xuất khái niệm mở, gợi ý ứng viên Target Alignment (+R), và áp dụng quyết định duyệt lược đồ qua `ProjectCommitCoordinator`.
   - `SchemaVectorIndexPort`, `SchemaEmbedderPort`: Ports truy vấn và mã hóa embedding cho lược đồ.
3. **`backend.modules.extraction.public`**
   - `ExtractionApplicationService`: Điều phối phân tích tài liệu, quản lý phiên bản prompt, chuẩn bị request preview, đăng ký engine (`FreeTriplesEngine`, `EDCOnePassEngine`, `EDCPlusREngine`, `FixedCatalogEngine`), thực thi trích xuất đơn đoạn và hàng loạt.
   - `FreeTriplesEngine`: Baseline B trích xuất bộ ba mở thuần túy, lưu artifact thô độc lập, không xâm nhập đồ thị đã duyệt.
4. **`backend.modules.curation.public`**
   - `CurationApplicationService`: Quản lý duyệt/từ chối/chỉnh sửa cạnh và thực thể, gộp thực thể (Entity Merge), gộp quan hệ (Relation Merge), chuẩn hóa loại thực thể, thu gọn cạnh lặp, đối soát bằng chứng gốc, và đồng bộ bí danh vào Từ điển Địa danh Dự án (`domain_gazetteer`).
5. **`backend.modules.graph_qa.public`**
   - `GraphQAApplicationService`: Trích xuất đồ thị con phục vụ Graph RAG (G-Retriever PCST, HippoRAG PPR, Naive Top-K), sinh câu hỏi benchmark tự động, đối sánh trực quan 3 phương pháp song song, và đồng bộ Neo4j qua `Neo4jPort`.
6. **`backend.modules.training.public`**
   - `TrainingApplicationService`: Xuất tập dữ liệu huấn luyện Active Learning (`sr_triplets.jsonl`, `canonicalization_pairs.jsonl`, `sft_extractions.jsonl`) cho `ml_lab`.

---

## 2. Bất biến Dữ liệu & Transaction (Coordinator Commit Contract)

- **Authoritative SSOT:** Tệp `data/projects/<name>/project.json` là nguồn sự thật duy nhất có thẩm quyền.
- **SQLite Projection:** Là bản sao đọc nhanh (Read-Only Projection); mọi mutation đều phải ghi thành công vào `project.json` trước khi đồng bộ sang SQLite. Nếu SQLite đồng bộ lỗi, cờ `sync_pending = True` được bật để cho phép khôi phục qua `resync_sqlite`.
- **Commit Lifecycle:**
  1. Acquire lock: Lấy `threading.RLock` của project từ `coordinator.get_project_lock(project_id)`.
  2. Idempotency Check: Kiểm tra `request_id` và `request_hash`. Nếu đã xử lý, trả về kết quả đã cache.
  3. Optimistic Revision Guard: So sánh `expected_revision` với `compute_project_revision(project)`. Nếu không khớp, từ chối giao dịch (`ValueError`).
  4. Candidate Transformation: `executor(project)` thực thi trên bản sao ứng viên, sinh kết quả DTO và snapshot.
  5. Authoritative Persist: Ghi bản sao ứng viên xuống đĩa an toàn.
  6. Projection & Invalidation: Đồng bộ SQLite và vô hiệu hóa cache vector/chỉ mục tương ứng.
  7. In-Memory Update: Cập nhật đối tượng `project` trong bộ nhớ sau khi toàn bộ bước trên hoàn tất.
