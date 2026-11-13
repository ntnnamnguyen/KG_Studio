# Ma trận Kiểm chứng Tính năng & Bài Test (Feature Test Matrix)

- **Run ID:** `2026-11-13-run01`

---

| Nhóm Tính năng | Kịch bản / Scenario Cần Bảo vệ | Test Files & Test Cases Tương ứng | Trạng thái Baseline |
| :--- | :--- | :--- | :--- |
| **Projects & Storage** | Create, load, save, restore snapshot; unknown fields; atomic rollback; stale revision; sync pending | `tests.test_commit_coordinator`, `tests.test_api_v1_and_composition` | `PASS` |
| **Concurrency & Lock** | Giao dịch đồng thời giữa use cases; cùng request retry; replay sau restart | `tests.test_commit_coordinator.TestProjectCommitCoordinator` | `PASS` |
| **Projection & Cache** | JSON authoritative commit; SQLite sync lỗi bật `sync_pending`; query ID/object; resync; vector cache invalidation | `tests.test_commit_coordinator`, `tests.test_performance_optimizations` | `PASS` |
| **Schema Intelligence** | Đề xuất EDC, 2 bảng thực thể & quan hệ, preview & apply batch, stale candidates, model fingerprint | `tests.test_edc_bulk_review`, `tests.test_standalone_architecture` | `PASS` |
| **Extraction & Baseline** | 4 extraction modes (`fixed`, `edc`, `edc_plus_r`, `free_triples`), prompt versioning, prepared request parity, attempts tracking, Free Triples baseline cách ly | `tests.test_free_triples_baseline`, `tests.test_free_triples_ui`, `tests.test_standalone_architecture` | `PASS` |
| **Curation & Merging** | Curation hub 3 phân khu, bằng chứng span, gộp thực thể 3 bước, gộp quan hệ, chuẩn hóa loại thực thể, thu gọn cạnh lặp, phản hồi từ điển `domain_gazetteer` | `tests.test_curation_hub`, `tests.test_curation_merge`, `tests.test_gazetteer_feedback_loop`, `tests.test_evidence_matching` | `PASS` |
| **Graph RAG & Export** | G-Retriever PCST, HippoRAG PPR, Naive Top-K, benchmark tự sinh và độc lập, Neo4j export, graph view DOT | `tests.test_baseline_graph`, `tests.test_standalone_architecture` | `PASS` |
| **UI State & Layout** | 5 màn hình tuần tự, giữ state chuyển tab/trang, theme Light tương phản cao, pipeline readiness | `tests.test_layout_pipeline`, `tests.test_ui_ux_improvements`, `tests.test_secrets_manager` | `PASS` |
| **Ranh giới Kiến trúc** | Backend/Shared không import Frontend; Shared pure; Domain không tự import Infrastructure ngoài allowlist; LLM clean import | `tests.test_architecture_boundaries` | `PASS` |
