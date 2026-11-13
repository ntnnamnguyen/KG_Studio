# Kết quả Nghiệm thu Mốc L05 — Tách I/O & Orchestration khỏi Domain

- **Run ID:** `2026-11-13-run01`
- **Mốc:** `L05`
- **Trạng thái:** `PASS`
- **Thời gian hoàn thành:** 2026-11-13 16:19:00

---

## 1. Đầu vào & Mục tiêu

- **Đầu vào:** Kết quả L04, danh sách 13 cạnh allowlist trong `test_architecture_boundaries.py`, ứng viên C06 & C07.
- **Mục tiêu:** Rà soát và kiểm chứng 5 lát cắt nghiệp vụ, bảo đảm domain thuần túy chứa quy tắc/thuật toán, application điều phối qua ports và adapters đảm nhiệm I/O/network.

---

## 2. Báo cáo Chi tiết 5 Lát cắt Nghiệp vụ

1. **Lát cắt 1: Schema Intelligence & EDC**
   - *Thuần túy (Domain):* `backend/domain/catalogs/core.py` (tính revision, làm sạch tên), `proposals.py` (chuẩn bị EDC, phát hiện xung đột, kiểm tra staleness), `review.py` (tính toán thay đổi đề xuất). 100% không I/O.
   - *Orchestration (Application):* `SchemaIntelligenceApplicationService` điều phối `SchemaRetriever` và `TargetAligner`, quản lý `commit_coordinator` và invalidation chỉ mục vector qua `SchemaVectorIndexPort`.
2. **Lát cắt 2: Extraction & Baseline**
   - *Thuần túy (Domain):* `validator.py` (kiểm tra hợp đồng trích xuất, đối chiếu span bằng chứng trong văn bản gốc), `chunking.py` (phân đoạn văn bản), `registry.py` (đăng ký các engine ID).
   - *Orchestration (Application):* `ExtractionApplicationService` điều phối gọi LLM qua `LLMExtractionPort`, quản lý attempt/run provenance, khóa tiến trình và lưu trữ kết quả. `FreeTriplesEngine` là baseline tách biệt hoàn toàn.
3. **Lát cắt 3: Curation & Knowledge Merging**
   - *Thuần túy (Domain):* `merge.py` (thuật toán gộp node DSU, collapse duplicate edges, dồn bằng chứng, cập nhật redirects), `evidence.py` (trích xuất span ngữ cảnh), `gazetteer.py` (tra cứu O(1), nạp mẫu, giải quyết bí danh). 100% không I/O.
   - *Orchestration (Application):* `CurationApplicationService` điều phối transaction commit, snapshot rollback, ghi nhận lịch sử kiểm duyệt (`curation_history`) và cập nhật `domain_gazetteer`.
4. **Lát cắt 4: Graph QA & Graph RAG**
   - *Thuần túy (Domain):* `baseline_graph.py` (chuẩn hóa RFC/Unicode NFC deterministic), `service.py` (Graphviz DOT styling, metrics), `g_retriever.py` (giải cây Steiner đa bước PCST / HippoRAG PPR).
   - *Orchestration (Application):* `GraphQAApplicationService` điều phối hỏi đáp đồ thị con, sinh câu hỏi benchmark, đồng bộ Neo4j qua `Neo4jPort`.
5. **Lát cắt 5: Training & Active Learning**
   - *Thuần túy (Domain):* Formatters dữ liệu học máy chuẩn hóa (`sr_triplets`, `canonicalization_pairs`, `sft_extractions`), kiểm tra định dạng bản ghi JSONL.
   - *Orchestration (Application):* `TrainingApplicationService` quản lý xuất file ra thư mục `data/training_exports/` độc lập.

---

## 3. Kết quả Kiểm thử & Đánh giá Cổng L05

- **Kiểm thử Biên Kiến trúc:**
  - `tests.test_architecture_boundaries`: 8/8 tests PASS (0.731s). Toàn bộ 13 cạnh allowlist được kiểm soát chặt chẽ, không phát sinh bất kỳ cạnh vi phạm mới nào.
- **Quyết định:** Đạt toàn bộ tiêu chí của mốc **L05**, sẵn sàng chuyển sang mốc **L06 — Migrate UI/API/CLI và transport**.
