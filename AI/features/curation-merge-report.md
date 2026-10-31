# Báo cáo Triển khai & Kiểm thử: Trang 5 — Kiểm duyệt Quan hệ, Quản lý Thực thể & Gộp Thực thể An toàn

- **Tài liệu đặc tả gốc:** [curation-merge.md](file:///D:/DATN/CrawData/KG_Studio/AI/features/curation-merge.md)
- **Trạng thái:** ✅ **ĐÃ TRIỂN KHAI & KIỂM THỬ HOÀN TẤT (20/20 bài kiểm thử tự động PASS, 0% phụ thuộc `KG_Studio_MVP`)**
- **Phạm vi:** Tầng DTO (`shared/schemas/`), Tầng Domain (`backend/domain/`), Tầng Facade & REST API (`backend/facade.py`, `backend/api/v1.py`), Tầng Giao diện & Session State (`frontend/`), Bộ kiểm thử tự động (`tests/test_curation_merge.py`).

---

## 1. Tóm tắt kiến trúc đã triển khai

### 1.1. Tầng Mô hình Dữ liệu & DTO ([shared/schemas/curation.py](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py), [shared/schemas/graph.py](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/graph.py))
- Khởi tạo đầy đủ các DTO tĩnh phục vụ Trang 5:
  - [`CurationQueryDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L20-L46), [`EdgeReviewDecisionDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L49-L77), [`CurationReviewRequestDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L80-L117), [`CurationPreviewDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L120-L158)
  - [`EntityEditRequestDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L161-L198), [`EdgeEditRequestDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L201-L239)
  - [`EntityMergeRequestDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L242-L281), [`EntityMergePreviewDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L284-L342)
  - [`CurationResultDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L345-L396)
- Định nghĩa bảng mã lý do loại bỏ chuẩn [`REJECTION_REASON_CODES`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L7-L14) và tập mã loại trừ phi ngữ nghĩa [`NON_SEMANTIC_REJECTION_CODES`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/curation.py#L16) (`duplicate_fact`, `out_of_scope`).
- Mở rộng [`NodeDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/graph.py#L8-L51), [`EdgeDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/graph.py#L79-L176) và [`EvidenceDTO`](file:///D:/DATN/CrawData/KG_Studio/shared/schemas/graph.py#L54-L76) để bảo toàn 100% siêu dữ liệu mở rộng (`schema_proposal_ids`, `edc_observations`, `merged_from`, `edc_original`, `doc_fingerprint`, `match_method`, `override_reason`, `rejection_code`, `extra`) khi đọc/ghi.

### 1.2. Tầng Domain Kiểm duyệt, Đối chiếu Bằng chứng & Gộp Thực thể ([backend/domain/curation/service.py](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py))
- **Đối chiếu bằng chứng hai cột & Định vị đa vị trí:**
  - [`evidence_context()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L140-L280) đối chiếu theo thứ tự ưu tiên: vị trí đã xác minh (`verified_start_char..verified_end_char` khi `doc_fingerprint` khớp) -> phạm vi đoạn trích xuất (`start_char..end_char`) -> khớp nguyên văn -> khớp sau chuẩn hóa khoảng trắng/NFC.
  - Khi câu dẫn chứng xuất hiện ở nhiều vị trí trong tài liệu mà chưa khóa phạm vi, đánh dấu `ambiguous=True` kèm danh sách `candidates` và cho phép khóa vị trí chính xác qua [`select_edge_evidence_span()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L282-L330).
  - Không bịa `page = 1` cho tài liệu không có thông tin trang (`doc["pages"]` rỗng).
- **Validator thống nhất & Cổng chặn Danh mục EDC:**
  - [`inspect_edge_schema_status()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L343-L437) và [`validate_edge_for_approval()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L440-L521) dùng chung cho duyệt đơn lẻ, duyệt hàng loạt, kiểm tra toàn vẹn và xuất đồ thị ([`is_edge_exportable()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L524-L535)).
- **Duyệt hàng loạt có Xem trước & Hai chế độ Áp dụng (`all_or_nothing` / `valid_only`):**
  - [`preview_curation_decisions()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L747-L853) và [`apply_curation_decisions()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L856-L999) loại trừ cạnh đã `Đã duyệt`/`Loại bỏ` khỏi thao tác hàng loạt, chặn duyệt lô cho cạnh thiếu bằng chứng hoặc tự nối, và giữ nguyên lựa chọn của các dòng lỗi khi chạy `valid_only`.
- **Ma trận ảnh hưởng khi chỉnh sửa (Mục 8.2):**
  - [`update_edge()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L1001-L1086): Đổi bất kỳ trường ngữ nghĩa nào (`source`, `target`, `relation`, `evidence`, `doc_id`, `start_char`, `end_char`) tự động chuyển cạnh về `Cần kiểm tra` và xóa hiệu lực phê duyệt/ngoại lệ cũ, ngay cả khi câu bằng chứng vẫn khớp.
  - [`update_node()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L1089-L1176): Sửa `name`, `aliases`, `description` giữ nguyên `node_id` và trạng thái các cạnh; sửa `kind` (bắt buộc thuộc danh mục `entity_types` đã duyệt) tự động chuyển các cạnh nối với thực thể đó (trừ cạnh `Loại bỏ`) về `Cần kiểm tra`.
- **Phát hiện nghi trùng & Gộp 2..N thực thể không mất mát dữ liệu:**
  - [`duplicate_suggestions()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L1265-L1342) có bộ nhớ đệm theo `(project_id, revision, fuzzy_threshold)` và tôn trọng danh sách `not_duplicate_pairs` từ [`mark_pair_not_duplicate()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L1198-L1242) (tự động gợi ý lại nếu tên/bí danh thay đổi).
  - [`preview_entity_merge()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L1358-L1634) và [`apply_entity_merge()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L1637-L1813) hỗ trợ gộp 2..N thực thể: bảo toàn 100% ID cạnh và bằng chứng (gom nhóm cạnh trùng qua [`compute_apparent_duplicate_edge_groups()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L1345-L1355), không tự xóa cạnh), tách bạch `affected_edge_count` và `changed_endpoint_count`, chuyển cạnh tự nối mới hoặc cạnh đổi loại thực thể đầu mút về `Cần kiểm tra`, và cập nhật bảng chuyển hướng phẳng `node_redirects`.

### 1.3. Liên thông Đồ thị Xuất (Trang 6) & Active Learning (ML Lab)
- [backend/domain/graph/service.py](file:///D:/DATN/CrawData/KG_Studio/backend/domain/graph/service.py): [`approved_graph()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/graph/service.py#L56-L64) và [`validate_integrity()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/graph/service.py#L15-L53) kiểm tra lại điều kiện xuất bằng [`is_edge_exportable()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/curation/service.py#L524-L535) để chặn mọi cạnh bị mất hiệu lực sau khi duyệt.
- [backend/domain/dataset_exporter/exporter.py](file:///D:/DATN/CrawData/KG_Studio/backend/domain/dataset_exporter/exporter.py): [`build_sr_triplets()`](file:///D:/DATN/CrawData/KG_Studio/backend/domain/dataset_exporter/exporter.py#L41-L117) loại trừ các cạnh bị từ chối với mã `duplicate_fact` hoặc `out_of_scope` khỏi tập mẫu âm ngữ nghĩa.

### 1.4. Tầng Facade Transactional, REST API & Giao diện Trang 5
- [backend/facade.py](file:///D:/DATN/CrawData/KG_Studio/backend/facade.py): Thực thi transactional qua [`_commit_curation_operation()`](file:///D:/DATN/CrawData/KG_Studio/backend/facade.py#L543-L639) (khóa dự án, kiểm tra `expected_revision`, chống nhấn đúp qua `curation_idempotency_store`, tạo snapshot trước khi ghi, ghi atomic bundle JSON kèm rollback khi lỗi I/O, đồng bộ SQLite kèm cơ chế `sync_pending`).
- [backend/api/v1.py](file:///D:/DATN/CrawData/KG_Studio/backend/api/v1.py): Bổ sung nhóm endpoint `/api/v1/projects/{name}/curation/{preview-edges,apply-edges,edit-edge,edit-entity,select-span,not-duplicate,preview-merge,apply-merge}`.
- Giao diện Trang 5 ([frontend/pages/p05_curation_merge.py](file:///D:/DATN/CrawData/KG_Studio/frontend/pages/p05_curation_merge.py)) tách 3 khu vực độc lập:
  - Khu vực A (`Quan hệ & bằng chứng`): [curation_table.py](file:///D:/DATN/CrawData/KG_Studio/frontend/components/curation_table.py) + [evidence_panel.py](file:///D:/DATN/CrawData/KG_Studio/frontend/components/evidence_panel.py)
  - Khu vực B (`Thực thể`): [curation_table.py](file:///D:/DATN/CrawData/KG_Studio/frontend/components/curation_table.py) + [evidence_panel.py](file:///D:/DATN/CrawData/KG_Studio/frontend/components/evidence_panel.py)
  - Khu vực C (`Gộp thực thể`): [entity_merge_panel.py](file:///D:/DATN/CrawData/KG_Studio/frontend/components/entity_merge_panel.py)
- Điều hướng liên trang Trang 5 ↔ Trang 4 lưu trong `session_state` ([frontend/state/session.py](file:///D:/DATN/CrawData/KG_Studio/frontend/state/session.py#L884-L936), [frontend/app.py](file:///D:/DATN/CrawData/KG_Studio/frontend/app.py#L78-L108), [frontend/pages/p04_edc_alignment.py](file:///D:/DATN/CrawData/KG_Studio/frontend/pages/p04_edc_alignment.py#L137-L151)).

---

## 2. Kết quả Kiểm thử Tự động (19/19 kịch bản đặc tả Mục 13)

Chạy lệnh kiểm thử:
```powershell
..\KG_Studio_MVP\.venv-win\Scripts\python.exe -m unittest discover -s tests -t . -v
```
Kết quả: **`Ran 20 tests in 1.546s — OK`**

| Kịch bản đặc tả (Mục 13) | Bài kiểm thử trong [tests/test_curation_merge.py](file:///D:/DATN/CrawData/KG_Studio/tests/test_curation_merge.py) | Kết quả |
|---|---|---|
| 1. Chọn một/nhiều/trang/tất cả theo ID; đổi trang, sắp xếp, bộ lọc, đổi dự án | `test_01_selection_by_id_sort_pagination_filter_pruning_and_project_reset` | ✅ PASS |
| 2 & 3. Lô 10 cạnh có 2 cạnh vướng EDC (`all_or_nothing` vs `valid_only`); không lật cạnh đã duyệt/loại bỏ | `test_02_batch_10_edges_with_2_schema_blocked_and_exclude_processed` | ✅ PASS |
| 4 & 5. Cạnh thiếu bằng chứng (chặn lô, bắt buộc `override_reason` khi duyệt đơn); câu bằng chứng lặp nhiều vị trí | `test_03_missing_evidence_override_and_multi_occurrence_disambiguation` | ✅ PASS |
| 6, 7 & 8. Hậu kiểm mất hiệu lực sau duyệt; sửa cạnh đã duyệt hạ về `Cần kiểm tra`; sửa hồ sơ thực thể độc lập | `test_04_post_approval_invalidation_and_edit_impact_matrix` | ✅ PASS |
| 9, 10, 11, 12, 13 & 14. `Khác đối tượng`; gộp 2..3 thực thể; tự nối; xung đột loại; bảo toàn 100% cạnh trùng sau gộp | `test_05_not_duplicate_pairs_and_merge_2_or_3_entities_with_conflicts_and_self_loops` | ✅ PASS |
| 15 & 16. Loại trừ `duplicate_fact`/`out_of_scope` khỏi mẫu âm ML; điều hướng Trang 5 ↔ Trang 4 | `test_06_non_semantic_rejection_codes_excluded_from_exporter_and_cross_page_nav` | ✅ PASS |
| 17, 18 & 19. Đa phiên `expected_revision`, idempotency `request_id`, rollback I/O JSON, `sync_pending` SQLite, khôi phục snapshot | `test_07_transactional_concurrency_idempotency_io_rollback_sqlite_resync_and_snapshot_restore` | ✅ PASS |

