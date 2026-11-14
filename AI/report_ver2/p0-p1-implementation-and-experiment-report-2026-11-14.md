# Báo Cáo Triển Khai P0 + P1, Kiểm Chứng Thực Nghiệm & Đánh Giá Sẵn Sàng Nghiên Cứu (KG Studio)

**Ngày lập báo cáo:** 2026-11-14  
**Nhánh / Workspace:** `d:\DATN\CrawData\KG_Studio` (`feature/fastapi-pydantic-v2`)  
**Môi trường kiểm chứng:** Python `3.13.2` (`.venv-win`), runner cô lập `tools/run_isolated_tests.py`, Ollama cục bộ (`bge-m3:latest`, `qwen3.5:4b`)  
**Tài liệu liên quan:**
- [Báo cáo rà soát cơ chế cốt lõi (2026-11-14)](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/core-mechanisms-audit-and-fixes-2026-11-14.md)
- [Hướng dẫn sử dụng KG Studio phiên bản CIDOC CRM song ngữ](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/huong-dan-cidoc-crm-song-ngu.md)
- [Bản đồ kiến trúc & luồng dữ liệu hệ thống](file:///d:/DATN/CrawData/KG_Studio/AI/structure.md)

---

## 1. Tóm Tắt Điều Hành (Executive Summary)

Đợt triển khai **P0 + P1** tập trung xử lý các điểm gãy logic, rủi ro mất/lệch dữ liệu, lỗi đồng thời (concurrency), rò rỉ bí mật cấu hình, và rò rỉ dữ liệu đánh giá (data leakage) trên 6 phân hệ cốt lõi của KG Studio, đồng thời hoàn thiện bộ nền tảng phục vụ thí nghiệm **CIDOC CRM song ngữ (Anh – Việt)**.

### Kết quả kiểm chứng sau chỉnh sửa cuối cùng

| Hạng mục kiểm chứng | Lệnh / Nguồn bằng chứng | Kết quả trực tiếp quan sát được | Phạm vi & Ghi chú trung thực |
| --- | --- | --- | --- |
| **Kiểm thử ranh giới kiến trúc (8 rules AST)** | `& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py tests.test_architecture_boundaries` | **8/8 PASS** (`0.765s`, `OK`) | Chạy offline trong thư mục tạm cô lập; bao gồm negative test cho cross-module private import. |
| **Toàn bộ bộ kiểm thử offline hệ thống** | `& .\.venv-win\Scripts\python.exe tools\run_isolated_tests.py` | **253/253 PASS** (`14.451s`, `OK`) | Đã gồm `tests.test_architecture_boundaries`, `tests.test_p0_p1_fixes` (9 nhóm hồi quy phủ `CR-01`..`CR-08`, `HI-01`..`HI-08`), `tests.test_standalone_architecture`. Bỏ 0 ca, lỗi 0 ca; ẩn `4266` cảnh báo Streamlit bare-mode. |
| **Bộ 6 thực nghiệm P0 + P1 & CIDOC song ngữ** | `& .\.venv-win\Scripts\python.exe AI\report_ver2\evidence\run_p0_p1_experiments.py` | **Hoàn tất sạch (exit `0`, `288.9s`)** | Xuất [p0_p1_experiments_results.json](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/p0_p1_experiments_results.json) (`ran_at: 2026-11-14T14:46:11`). Exp 2, 3B, 5E dùng **Ollama thật**; Exp 4 dùng mock engine test luồng điều phối; Exp 6 đọc **bản sao chỉ đọc** của `kg_hanoi_edc_r_a` với Neo4j `_FakeDriver`. |
| **Bộ danh mục mẫu CIDOC CRM song ngữ** | [cidoc_starter](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/cidoc_starter) | **30 Entity Types + 55 Relations** | Round-trip CSV/JSON giữ nguyên `55/55` `domain`, `range`, `aliases` tiếng Việt. |
| **Cập nhật Knowledge Graph mã nguồn** | `graphify update .` | **Đã hoàn tất (`3,231` nút, `9,709` cạnh, `161` cụm)** | Đã chạy AST rebuild sau chỉnh sửa mã & test cuối cùng (`AST cache: 268/270`, `2/2 uncached`); `data/projects/*` và `config/catalogs/*` giữ nguyên 100%. |

---

## 2. Tổng Hợp Triển Khai Các Khắc Phục P0 (`CR-01`..`CR-08`) & P1 (`HI-01`..`HI-08`)

Bảng dưới đây đối chiếu đúng từng mã lỗi từ [Báo cáo rà soát cơ chế cốt lõi](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/core-mechanisms-audit-and-fixes-2026-11-14.md), tệp đã sửa trong mã nguồn và kiểm thử/thực nghiệm chứng minh trong [`tests/test_p0_p1_fixes.py`](file:///d:/DATN/CrawData/KG_Studio/tests/test_p0_p1_fixes.py):

| Mã / Nhóm | Cơ chế & Bất biến được khôi phục | Tệp tin & Ký hiệu chính đã kiểm tra | Kiểm thử hồi quy & Thực nghiệm chứng minh |
| --- | --- | --- | --- |
| **`CR-01`** | **Catalog v2 Round-Trip (`domain`, `range`, `aliases`) & Encoding CSV/JSON:** Hỗ trợ `domain`, `range` (`OPTIONAL_CATALOG_FIELDS`) và `aliases` qua `validate_catalog`, `catalog_csv_bytes`, `relation_catalog`, `apply_relations`; UI Bước 2 nhận/hiển thị `domain`, `range` -> mở khóa `[Domain -> Range]` cho `SchemaRetriever`. | [shared/catalog_utils.py](file:///d:/DATN/CrawData/KG_Studio/shared/catalog_utils.py), [backend/domain/schema_intelligence/retriever.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/schema_intelligence/retriever.py), [frontend/pages/p02_catalogs_prompts.py](file:///d:/DATN/CrawData/KG_Studio/frontend/pages/p02_catalogs_prompts.py) | `test_cr01_catalog_domain_range_aliases_csv_and_json_roundtrip`; **Exp 1** (`55/55` khớp tuyệt đối). |
| **`CR-02`** | **Đồng bộ Chữ ký Prompts & Schema qua Facade / ApplicationService:** Sửa `get_prompt_version`, `save_prompt_version`, `restore_prompt_version`, `diff_prompt_versions`, `prepare_edc`, `propose_term` và chuyển lời gọi `KGStudioFacade` qua đúng Application Service, kiểm tra `expected_revision`. | [backend/domain/prompts/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/prompts/service.py), [backend/modules/extraction/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/extraction/application/service.py), [backend/modules/schema_intelligence/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/schema_intelligence/application/service.py), [backend/facade.py](file:///d:/DATN/CrawData/KG_Studio/backend/facade.py) | `test_cr02_cr05_prompt_version_expected_revision_and_service_signature`, `test_cr02_cr03_cr04_cr05_hi04_facade_training_and_repos`. |
| **`CR-03`** | **Sửa Bulk Entity Merge & Bỏ Hardcode Idempotency trên Facade:** `CurationApplicationService.apply_bulk_entity_merges` nhận danh sách cặp và hash toàn bộ nội dung cặp + tùy chọn thay cho `r.target_canonical_name`; `KGStudioFacade` không còn hardcode `request_id="bulk_merge"` / `request_hash=""`. | [backend/modules/curation/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/curation/application/service.py), [backend/facade.py](file:///d:/DATN/CrawData/KG_Studio/backend/facade.py) | `test_cr04_bulk_merge_invalidates_approved_edges_and_rejects_redirect_cycle`, `test_cr02_cr03_cr04_cr05_hi04_facade_training_and_repos`. |
| **`CR-04`** | **Sửa truyền `edges` cho `compute_apparent_duplicate_edge_groups`:** `CurationApplicationService` và `KGStudioFacade` truyền `project.get("edges", [])` thay vì truyền nguyên `dict` dự án. | [backend/modules/curation/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/curation/application/service.py), [backend/facade.py](file:///d:/DATN/CrawData/KG_Studio/backend/facade.py) | `test_cr02_cr03_cr04_cr05_hi04_facade_training_and_repos`. |
| **`CR-05`** | **Sửa `TrainingApplicationService.build_sft_instructions`:** Nối đúng sang `self.exporter.build_sft_records(project)` thay vì phương thức không tồn tại gây `AttributeError`. | [backend/modules/training/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/training/application/service.py) | `test_cr02_cr03_cr04_cr05_hi04_facade_training_and_repos`. |
| **`CR-06`** | **Thống nhất Coordinator Revision Tracking & Clone Proposal trước Commit:** Đồng nhất `_last_committed_revision` với `ProjectCommitCoordinator`; `decide_single_proposal` clone trước (`mutate_in_place=False`) và bắt buộc coordinator; bọc xử lý lỗi lưu Step 2. | [backend/modules/projects/application/commit_coordinator.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/projects/application/commit_coordinator.py), [backend/modules/projects/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/projects/application/service.py), [backend/modules/schema_intelligence/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/schema_intelligence/application/service.py), [frontend/pages/p02_catalogs_prompts.py](file:///d:/DATN/CrawData/KG_Studio/frontend/pages/p02_catalogs_prompts.py) | `test_cr06_hi03_coordinator_mandatory_and_sqlite_auto_resync`; **Exp 4 & Exp 6A**. |
| **`CR-07`** | **Fail-Closed cho Đồ thị Đã duyệt (`Approved KG`) & Chặn Fallback:** `get_or_build_graph_index(..., approved_only=True)` trả `0` cạnh khi đồ thị đã duyệt rỗng (không fallback `all`); khi `approved_only=False` vẫn loại `STATUS_REJECTED`. | [backend/domain/graph/g_retriever.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/graph/g_retriever.py) | `test_cr07_hi07_hi08_graphrag_neo4j_and_disjoint_qa`; **Exp 5A** (`empty_approved_edges_count = 0`). |
| **`CR-08`** | **Target Alignment & Verifier Fail-Closed:** `pick_choice_letter` gỡ `<think>` và trả `None` khi mơ hồ; `verify_alignment_detailed` báo lỗi tường minh; `TargetAligner` giữ `pending` khi Verifier lỗi và không tự gộp vượt `auto_align_threshold`; `run_target_alignment_on_pending` & UI Hub truyền `llm_params`/`enable_llm_verifier`. | [backend/integrations/llm/parsing.py](file:///d:/DATN/CrawData/KG_Studio/backend/integrations/llm/parsing.py), [backend/integrations/llm/gateway.py](file:///d:/DATN/CrawData/KG_Studio/backend/integrations/llm/gateway.py), [backend/domain/schema_intelligence/aligner.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/schema_intelligence/aligner.py), [backend/modules/schema_intelligence/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/schema_intelligence/application/service.py), [frontend/pages/p04_curation_hub.py](file:///d:/DATN/CrawData/KG_Studio/frontend/pages/p04_curation_hub.py) | `test_cr08_hi05_fail_closed_verifier_and_parsing`; **Exp 3A & Exp 3B**. |
| **`HI-01` / `HI-02`** | **An toàn Đa luồng Trích xuất, Ghi Run Lỗi, Che Bí mật & Log UI P03:** Bỏ ghi `extraction_mode` ngoài lock; `EDCPlusREngine` dùng `MODE_EDC_PLUS_R`, truyền `proposal_ids` đúng lượt; `extract_chunk`/`extract_chunks_parallel` lưu `status="error"` + token + che API key; `p03_extraction.py` đọc `run.get("ingest_stats") or run`; `should_use_e5_instruct` tắt tiền tố E5 cho `bge-m3`. | [backend/domain/extraction/base_engine.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/extraction/base_engine.py), [backend/domain/extraction/engines/edc_one_pass.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/extraction/engines/edc_one_pass.py), [backend/domain/extraction/engines/edc_plus_r.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/extraction/engines/edc_plus_r.py), [backend/modules/extraction/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/extraction/application/service.py), [frontend/pages/p03_extraction.py](file:///d:/DATN/CrawData/KG_Studio/frontend/pages/p03_extraction.py), [shared/prompt_templates/__init__.py](file:///d:/DATN/CrawData/KG_Studio/shared/prompt_templates/__init__.py) | `test_hi01_hi02_parallel_error_redaction_and_non_e5_prompt_formatting`; **Exp 2 & Exp 4**. |
| **`HI-03`** | **Khóa `restore_snapshot` theo `project_id` & Gỡ Bypass Coordinator:** `_resolve_lock_id` khóa theo `project_id`; chuyển các lệnh ghi ở Curation (`_commit_with_domain_return`), Schema Intelligence (`save_metadata_in_lock`, `commit`) và `p04_curation_hub.py` về coordinator. | [backend/modules/projects/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/projects/application/service.py), [backend/modules/curation/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/curation/application/service.py), [backend/modules/schema_intelligence/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/schema_intelligence/application/service.py), [frontend/pages/p04_curation_hub.py](file:///d:/DATN/CrawData/KG_Studio/frontend/pages/p04_curation_hub.py) | `test_cr06_hi03_coordinator_mandatory_and_sqlite_auto_resync`, `test_cr04_bulk_merge_invalidates_approved_edges_and_rejects_redirect_cycle`. |
| **`HI-04`** | **SQLite Projection & Crash Recovery / Path Containment JSON:** `SQLiteProjectRepository` lưu `revision`, metadata staleness cho `schema_proposals`, join tên nút `sn.name`/`tn.name` trong `query_edges_page`, thêm `search` ở `query_proposals_page`, xử lý `UNIQUE(name)` và sửa `_paginate`; `JsonProjectRepository` giữ backup khi hồi phục lỗi và chặn path traversal trong `restore_snapshot`. | [backend/repositories/sqlite_repo.py](file:///d:/DATN/CrawData/KG_Studio/backend/repositories/sqlite_repo.py), [backend/repositories/json_repo.py](file:///d:/DATN/CrawData/KG_Studio/backend/repositories/json_repo.py), [backend/modules/projects/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/projects/application/service.py) | `test_cr06_hi03_coordinator_mandatory_and_sqlite_auto_resync`, `test_cr02_cr03_cr04_cr05_hi04_facade_training_and_repos`; **Exp 6A**. |
| **`HI-05`** | **Vector Cache `v2-domain-range`, Invalidation & Embedder Default:** `ProjectsApplicationService` truyền `catalog_rows(project, kind)` thay cho `list[str]`; `VectorIndexRepository` gắn `PASSAGE_TEMPLATE_VERSION = "v2-domain-range"`, ghi atomic + khóa thread, kiểm tra khớp chiều vector; `_current_model_fingerprint` mặc định `"hybrid_vn:default"`. | [backend/modules/projects/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/projects/application/service.py), [backend/repositories/vector_repo.py](file:///d:/DATN/CrawData/KG_Studio/backend/repositories/vector_repo.py), [backend/modules/schema_intelligence/application/service.py](file:///d:/DATN/CrawData/KG_Studio/backend/modules/schema_intelligence/application/service.py), [shared/prompt_templates/__init__.py](file:///d:/DATN/CrawData/KG_Studio/shared/prompt_templates/__init__.py) | `test_cr08_hi05_fail_closed_verifier_and_parsing`; **Exp 1 & Exp 2**. |
| **`HI-06`** | **Bất biến Curation Merge, Chu trình Redirect, Not-Duplicate Hash & Override Note:** `_clone_project_for_merge_mutation` sao chép đầy đủ khóa gazetteer/catalog/proposal; bulk merge & entity-type merge hạ cạnh `STATUS_APPROVED -> STATUS_CHECK` khi đổi loại hoặc thành self-loop; `flatten_redirects` chặn chu trình (`ValueError`); `compute_project_revision` hash nội dung cặp not-duplicate; `review_stats` lọc cặp đã dismiss; `set_edge_status` bảo toàn tag `[Ngoại lệ bằng chứng]`. | [backend/domain/curation/merge_core.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/curation/merge_core.py), [backend/domain/curation/merge.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/curation/merge.py), [backend/domain/curation/semantic_clustering.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/curation/semantic_clustering.py), [backend/domain/curation/entities.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/curation/entities.py), [backend/domain/catalogs/core.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/catalogs/core.py), [backend/domain/curation/review.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/curation/review.py) | `test_cr03_evidence_override_note_and_dismissed_pair_filter_and_revision_hash`, `test_cr04_bulk_merge_invalidates_approved_edges_and_rejects_redirect_cycle`; **Exp 6D**. |
| **`HI-07`** | **Neo4j Cô lập Đa dự án & Lọc bằng chứng trước Đồng bộ:** Constraint theo khóa `uid` gắn `project_id`, sửa ánh xạ `trang_thai`, và lọc nghiêm ngặt cạnh hợp lệ trước khi ghi. | [backend/integrations/neo4j_gateway.py](file:///d:/DATN/CrawData/KG_Studio/backend/integrations/neo4j_gateway.py) | `test_cr07_hi07_hi08_graphrag_neo4j_and_disjoint_qa`; **Exp 5D & Exp 6E**. |
| **`HI-08`** | **GraphRAG CIDOC `_`/`-`, Prompt Động & QA Disjoint Split:** Tách token qua `_`/`-`, nhận `domain_topic` và giới hạn `max_input_tokens`, sửa PCST/PPR, và mặc định `disjoint_split=True` bảo đảm `0` cạnh rò rỉ giữa `train / val / test` kèm khớp target cho `Explainable Path`. | [backend/domain/graph/g_retriever.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/graph/g_retriever.py), [backend/domain/graph/qa_generator.py](file:///d:/DATN/CrawData/KG_Studio/backend/domain/graph/qa_generator.py) | `test_cr07_hi07_hi08_graphrag_neo4j_and_disjoint_qa`; **Exp 5B–E & Exp 6B–C**. |

---

## 3. Kết Quả 6 Thực Nghiệm Kiểm Chứng (Empirical Verification)

Toàn bộ kết quả dưới đây trích xuất trực tiếp từ file kết quả chạy thực tế [`p0_p1_experiments_results.json`](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/p0_p1_experiments_results.json) (sinh bởi [`run_p0_p1_experiments.py`](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/run_p0_p1_experiments.py) lúc `2026-11-14T14:46:11`, tổng thời gian `288.9s`). Mọi file JSON/SQLite/Vector tạm chỉ ghi trong `tempfile.TemporaryDirectory()`.

### Thực nghiệm 1 (`exp1_catalog_roundtrip`): Round-trip Danh mục CIDOC CRM Song ngữ (CSV & JSON)

- **Thiết lập:** Bộ danh mục mẫu [cidoc_starter](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/cidoc_starter) gồm **30 lớp thực thể CIDOC** (`E1_CRM_Entity` ..) và **55 thuộc tính quan hệ CIDOC** (`P1_is_identified_by`, `P53_has_former_or_current_location`, ...) kèm `domain`, `range`, `aliases` tiếng Việt -> xuất ra `catalog_csv_bytes` & `catalog_bytes` -> nạp lại qua `parse_catalog` -> áp vào `empty_project` qua `apply_relations`.
- **Kết quả đo được:**
  - `entity_types_count`: `30` | `relations_count`: `55` | `json_relations_count`: `55`
  - `domain_preserved`: **`55/55`** | `range_preserved`: **`55/55`** | `aliases_preserved`: **`55/55`**
  - `passage_template_version`: `"v2-domain-range"`
  - Mẫu passage kiểm tra:
    `P53_has_former_or_current_location: Tọa lạc tại địa điểm hoặc vùng đất. | Vị trí không gian cố định hoặc lịch sử của công trình, di tích và hiện vật vật chất. | Scope: E18_Physical_Thing -> E53_Place | Aliases: tọa lạc tại, nằm tại, đặt tại, ở địa điểm`

### Thực nghiệm 2 (`exp2_schema_retrieval_sr`): Đối sánh Schema Retriever (`+R`) trên 20 truy vấn CIDOC Song ngữ

- **Thiết lập:** 20 đoạn/câu truy vấn tiếng Việt miền di sản Việt Nam ánh xạ tới 20 quan hệ chuẩn CIDOC khác nhau trong catalog 55 quan hệ; so sánh 3 cấu hình trong `SchemaRetriever`:
  1. `hybrid_vn:default` (`dim=1024`, dùng từ điển tiếng Việt + n-gram) trên catalog giàu (`v2-domain-range` + `aliases`).
  2. `ollama:bge-m3` **Live Ollama** (`dim=1024`, `should_use_e5_instruct = False`, query thuần `"vị trí xây dựng"` không bị ép tiền tố E5) trên catalog **bare** (bỏ `domain`, `range`, `aliases`).
  3. `ollama:bge-m3` **Live Ollama** trên catalog **rich** (`v2-domain-range` + `aliases`).

| Cấu hình mô hình | Dùng E5 Instruct? | Recall@5 | Recall@15 | Recall@30 | MRR | Build + Query đầu (ms) | Query TB (ms) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `hybrid_vn:default` (rich) | `True` (`uses_e5_instruct=true`) | `0.85` (17/20) | `1.00` | `1.00` | `0.7812` | `56.9` | `0.82` |
| `ollama:bge-m3` (bare — thiếu scope/aliases) | `False` (`uses_e5_instruct=false`) | `0.90` (18/20) | `1.00` | `1.00` | `0.6863` | `9541.0` | `4200.42` |
| `ollama:bge-m3` (rich — **`v2-domain-range` + `aliases`**) | `False` (`uses_e5_instruct=false`) | **`0.95` (19/20)** | **`1.00`** | **`1.00`** | **`0.7625`** | `9413.1` | `4176.93` |

- **Nhận xét chuyên môn:**
  - Việc truyền thêm `[Domain -> Range]` và `aliases` tiếng Việt qua `v2-domain-range` giúp `ollama:bge-m3` tăng `Recall@5` từ `0.90` lên **`0.95`** và cải thiện mạnh `MRR` thêm **`+0.0762`** (`0.6863 -> 0.7625`).
  - Từ `Top-K >= 15`, cả 3 cấu hình đều đạt **`Recall = 1.00`** trên catalog 55 quan hệ CIDOC.
  - **Độ trễ thực tế:** `ollama:bge-m3` cục bộ mất trung bình **`~4.18 giây/truy vấn`** (`avg_query_ms = 4176.93`), nhanh hay chậm phụ thuộc phần cứng GPU cục bộ (so với `<1 ms` của `hybrid_vn:default`). Điều này lý giải vì sao cần giữ số luồng thấp (`1–2`) khi dùng chung Ollama cho LLM và Embedder.

### Thực nghiệm 3 (`exp3_target_alignment_verifier`): Parsing, Fail-Closed Verifier & Live `qwen3.5:4b` trên 9 Đề xuất Song ngữ

1. **Kiểm tra bộ phân giải & Fail-closed (`Exp 3A`):**
   - `pick_choice_letter("Có thể là A hoặc B đều đúng", ["A", "B"])` -> **`None`** (`parsing_ambiguous_ab: null` — từ chối câu trả lời mơ hồ).
   - `pick_choice_letter("<think>xem xét...</think>\nLựa chọn: B", ["A", "B", "C"])` -> **`"B"`** (gỡ thẻ suy nghĩ nội bộ sạch sẽ).
   - Khi mô phỏng lỗi `RuntimeError("Simulated Ollama Timeout")` từ Verifier trên 3 đề xuất: `auto_aligned = 0`, `error_count = 3`, **`all_still_pending = True`**.
2. **Thử nghiệm Live Ollama `bge-m3` + Verifier `qwen3.5:4b` (`Exp 3B`):** Đánh giá 9 đề xuất mở tiếng Việt (`5` loại thực thể, `4` quan hệ) ở hai mức `auto_align_threshold`:

| Chế độ ngưỡng | Thời gian (s) | Auto-aligned (`merged`) | Chờ duyệt (`pending`) | Error | Verifier Input / Output Tokens | Ý nghĩa & Quan sát thực nghiệm |
| --- | :---: | :---: | :---: | :---: | :---: | --- |
| **Mặc định thận trọng `0.86`** | `44.15` | **`0`** | **`9`** | `0` | `3,155 / 18` | Tuân thủ `CR-08`: điểm cosine chéo ngôn ngữ của `bge-m3` nằm trong `0.5533 – 0.7756` (< `0.86`), nên **0 đề xuất nào bị tự động hợp nhất vượt ngưỡng**, dù cả 9/9 đều được `qwen3.5:4b` gắn nhãn `llm_verified_candidates`. |
| **Hiệu chuẩn song ngữ `0.72`** | `44.69` | **`4`** | **`5`** | `0` | `3,157 / 18` | 4 cặp >= `0.72` được Verifier xác nhận tự động gộp (`decision_origin = "llm_verified_auto"`): `E53_Place` (`0.7386`), `E57_Material` (`0.7756`), `P53_has_former_or_current_location` (`0.7238`), `P7_took_place_at` (`0.7445`). 5 cặp `< 0.72` vẫn giữ an toàn ở `pending`. |

- **Chi tiết giá trị từ Verifier `qwen3.5:4b` (cùng quan sát định tính):**
  - Với đề xuất `"ghi nhớ tôn vinh"` (`p_rel_about`), top cosine `bge-m3` chọn nhầm `P129_is_about` (`0.6576`), nhưng Verifier `qwen3.5:4b` đọc `[Domain -> Range]` và sửa lại thành **`P138_represents`**.
  - Ở phía ngược lại, trên `"Ngôi chùa cổ"` (`0.5533`, Verifier chọn lớp cha `E24_Physical_Human-Made_Thing` thay vì `E22_Human-Made_Object`) và `"Sự kiện văn hóa truyền thống"` (`0.655`, Verifier chọn `E2_Temporal_Entity` thay vì `E5_Event`), điều này cho thấy ngưỡng mặc định `0.86` giữ lại khâu duyệt của con người là hợp lý khi làm dữ liệu nghiên cứu chuẩn.

### Thực nghiệm 4 (`exp4_parallel_edcr_stress`): Stress Test Trích xuất Song song 4 Luồng, Cô lập Lỗi & Che Bí mật

- **Thiết lập:** Chạy `ExtractionApplicationService.extract_chunks_parallel(..., max_workers=4, save_after_chunk=True)` trên 3 tài liệu x 4 đoạn = **12 tác vụ**, dùng `_MockEDCREngine` có tiêm 1 lỗi 429 chứa API key giả `sk-test-secret-do-not-leak-999` kèm `input_tokens=210, output_tokens=14` ở đoạn 2 tài liệu `doc_2`. *(Lưu ý: dùng mock engine để cô lập kiểm chứng luồng lock/commit/redaction, không phải 12 lần gọi LLM thật).*
- **Kết quả:**
  - `total_tasks`: `12` | `success_count`: **`11`** | `failed_count`: **`1`** | `elapsed_ms`: **`381.8 ms`**
  - `saved_nodes`: `22` | `saved_edges`: `11` | `ok_runs_persisted`: `11` | `error_runs_persisted`: `1` | `processed_chunks_count`: **`11`** (đoạn lỗi không bị đánh dấu hoàn tất để có thể chạy lại sau)
  - `sqlite_synced_edges`: `11` | `sync_pending`: `False`
  - `secret_leaked_in_saved_json`: **`False`** (API key đã được che sạch trước khi lưu)
  - `error_run_token_accounting`: **`{"input_tokens": 210, "output_tokens": 14}`** (bảo toàn hạch toán token lượt lỗi)

### Thực nghiệm 5 (`exp5_graphrag_cidoc_and_qa`): GraphRAG CIDOC `_`, Fail-Closed, Live `qwen3.5:4b` & QA Disjoint Split

- **Thiết lập:** Đồ thị CIDOC song ngữ mẫu gồm **18 nút**, **19 cạnh `APPROVED` có trích dẫn khớp tài liệu nguồn**, kèm 1 cạnh `PENDING`, 1 cạnh `REJECTED` và 1 cạnh `APPROVED` nhưng bằng chứng bịa (`evidence_found=False`, không `override`).
- **Kết quả kiểm chứng bất biến:**
  - `empty_approved_edges_count`: **`0`** (khi gỡ hết trạng thái `approved`, `get_or_build_graph_index(approved_only=True)` trả về 0 cạnh — fail-closed `CR-07`).
  - `approved_only_false_excludes_rejected`: **`True`** (`e_rej` bị loại kể cả khi `approved_only=False`).
  - `neo4j_exportable_edges_with_evidence_filter`: **`19` / `20`** cạnh `APPROVED` thô (tự động lọc bỏ cạnh bịa bằng chứng `e_badev`).
- **Đối sánh GraphRAG (5 truy vấn CIDOC có `_`/`-`) & Live `qwen3.5:4b` (`Exp 5B`, `5E`):**
  - Cả 3 phương pháp `naive_topk`, `ppr`, `pcst` đạt **`100.0%`** trên 3 chỉ số Thu hồi Đáp án Đích, Thu hồi Cạnh Chuẩn và Nối mạch 2-Hop Bridge trên tập nhỏ 5 câu; trong đó `pcst` cho ngữ cảnh gọn nhất (`458 tokens` trung bình, `0.52 ms`, độ liên thông `94.0%`, so với `ppr` `634 tokens` / `97.8%` / `0.64 ms`).
  - **Live GraphRAG QA (`qwen3.5:4b`):** `status = "ok"`, `used_llm = True`, `retrieved_edges = 6`, `has_hanoi_hardcode_in_prompt = False` (nhận `domain_topic`), `input_tokens = 808`, `output_tokens = 512`, `llm_latency_ms = 5972.5 ms`.
- **QA Dataset Split (43 mẫu sinh ra từ 19 cạnh):**
  - `disjoint_split=True` (`[35, 4, 4]`): **`train_val_edge_overlap = 0`**, **`train_test_edge_overlap = 0`**, **`val_test_edge_overlap = 0`**.
  - `disjoint_split=False` (`[34, 3, 6]`): bị rò rỉ **`1` / `2` / `3`** cạnh chéo giữa các tập.

### Thực nghiệm 6 (`exp6_real_project_readonly`): Kiểm Chứng Bản Sao Dữ Liệu Thật `KG_HaNoi_EDC_R_A`

- **Thiết lập:** Nạp bản sao chỉ đọc trong `tempfile.TemporaryDirectory()` của dự án thật `data/projects/kg_hanoi_edc_r_a/project.json` (**`1,587` thực thể**, **`1,941` cạnh**, **`1,655` cạnh `APPROVED` thô**, **`1,048` đề xuất lược đồ**). Tuyệt đối không ghi vào thư mục `data/projects/`. Sync Neo4j chạy qua `_FakeDriver` offline.

1. **SQLite Auto-Resync & Consistency (`Exp 6A`, `6D`, `6E`):**
   - Lần truy vấn đầu tiên khi SQLite trống tự động đồng bộ toàn bộ 1,587 nút và 1,941 cạnh chỉ trong **`122.3 ms`** (`cold_resync_and_query_ms`), truy vấn kế tiếp từ SQLite mất **`18.36 ms`** (`warm_node_query_ms`), `sync_pending = False`.
   - Bộ lọc bằng chứng `approved_graph` giữ **`1,651` / `1,655`** cạnh hợp lệ; `_FakeDriver` ghi **`1,435`** nút và **`1,651`** cạnh.
   - Đánh dấu 1 cặp *Không trùng lặp* giảm ngay số gợi ý trùng thực thể từ **`72` -> `71`** (`dismissed_pair_immediately_filtered = True`).

2. **Đối sánh thuật toán GraphRAG trên 18 câu hỏi thực tế (`Exp 6B`):**

| Phương pháp (`max_edges=12`) | Thu hồi Đáp án Đích | Thu hồi Cạnh Chuẩn | Nối mạch 2-Hop Bridge | Độ liên thông Đồ thị con | Token Ngữ cảnh TB | Thời gian TB (ms) |
| --- | :---: | :---: | :---: | :---: | :---: | :---: |
| `naive_topk` (Baseline) | `66.7%` | `83.3%` | `33.3%` | `47.7%` | `1,984` | `42.06` |
| `ppr` (HippoRAG) | **`100.0%`** | **`100.0%`** | **`100.0%`** | `60.2%` | **`1,765`** | `51.15` |
| `pcst` (G-Retriever) | `94.4%` | `97.2%` | **`100.0%`** | **`63.2%`** | `1,934` | `43.74` |

3. **Chống rò rỉ dữ liệu QA Studio (`Exp 6C`, 400 mẫu từ 323 cạnh chuẩn phân biệt):**

| Chế độ chia tập | Số mẫu (`Train / Val / Test`) | Rò rỉ cạnh `Train∩Val` | Rò rỉ cạnh `Train∩Test` | Rò rỉ cạnh `Val∩Test` | Rò rỉ thực thể neo (`Tr∩Te`) |
| --- | :---: | :---: | :---: | :---: | :---: |
| `disjoint_split=True` (Mặc định mới) | `345 / 36 / 19` | **`0`** | **`0`** | **`0`** | `5` (chấp nhận qua thực thể bắc cầu) |
| `disjoint_split=False` (Legacy đối chứng) | `320 / 40 / 40` | `21` | `19` | `5` | `12` |

---

## 4. Đánh Giá Trung Thực Mức Độ Hoàn Thiện & Khả Năng Làm Thí Nghiệm

Dựa trên kết quả `253/253` test offline (kèm 8 rule AST), 6 thực nghiệm định lượng trên hệ thống và khảo sát mã nguồn hiện tại:

### Đã sẵn sàng cho nhóm thí nghiệm nào?
- **Sẵn sàng (với điều kiện vận hành chuẩn single-user local Streamlit):**
  1. **Thí nghiệm trích xuất Tri thức & Xây dựng KG tiếng Việt / CIDOC CRM song ngữ:** Đọc PDF/DOCX/TXT UTF-8 -> `EDC + R` (kèm `ollama:bge-m3` hoặc `hybrid_vn:default`) -> Rà soát & Hợp nhất tại Hub (`CR-01`..`CR-08`, `HI-01`..`HI-06`) -> Đồ thị Đã duyệt lưu Atomic JSON + SQLite đồng bộ.
  2. **Thí nghiệm đối sánh Retrieval & GraphRAG:** So sánh `naive_topk` vs `ppr` vs `pcst` trên đồ thị Đã duyệt (`Approved KG`) đối chiếu với Baseline B (`free_triples` chưa kiểm duyệt), xuất bộ dữ liệu QA không rò rỉ (`disjoint_split=True`), và xuất sang Neo4j cô lập theo `project_id`.

### Nợ kỹ thuật còn lại ngoài phạm vi P0 + P1 (P2 – P3 Backlog)

Để bảo đảm tính trung thực khoa học, hệ thống **chưa xử lý hết mọi hạng mục P2–P3** trong báo cáo rà soát kiến trúc; cần ghi rõ giới hạn này nếu đề cập trong khóa luận:

1. **`HI-09` (ML Lab Train/Serve Parity & Offline Holdout Evaluation):**
   - Ví dụ quan sát trực tiếp tại [`ml_lab/trainers/train_schema_retriever.py`](file:///d:/DATN/CrawData/KG_Studio/ml_lab/trainers/train_schema_retriever.py#L82-L125): hàm `train_schema_retriever_model` hiện đánh giá `before_metrics` và `after_metrics` trên **chính tập `records` huấn luyện** (chưa chia holdout/val nội bộ) và mới tối ưu trọng số từ vựng/synonym trên nền `hybrid_vn` (không trực tiếp fine-tune neural weights cho `ollama:bge-m3`). Do đó, **khuyên chưa dùng nút train nội bộ như một đóng góp học sâu độc lập** nếu chưa bổ sung bước holdout split ở P2.
2. **`HI-10` (Remote HTTP Transport & Multi-user UI Session Isolation):**
   - Trong [`frontend/client.py`](file:///d:/DATN/CrawData/KG_Studio/frontend/client.py#L26-L44), phần lớn phương thức của `FrontendClient` hiện gọi trực tiếp in-process tới `self.facade` (ngoại trừ `get_embedding_models` thử `/api/v1/models`). Các bài kiểm thử giao diện đa phiên người dùng đồng thời và AppTest / kiểm thử truy cập (accessibility) trên trình duyệt thực tế chưa được phủ toàn bộ.
3. **Điểm nhỏ còn mở đã phát hiện khi rà soát sau cùng:**
   - Trong [`backend/modules/schema_intelligence/application/service.py`](file:///d:/DATN/CrawData/KG_Studio/backend/modules/schema_intelligence/application/service.py#L356), nhánh `run_target_alignment_on_pending(save=True)` (chỉ kích hoạt khi gọi qua application service với dự án đã lưu đĩa, không ảnh hưởng luồng chạy trong engine `edc_plus_r.py` hay `save=False` ở Exp 3) truyền thiếu tham số `expected_revision` cho `commit_coordinator.commit(...)`. Nên bổ sung tham số `expected_revision` ở đợt P2.
   - Các hạng mục UI/UX cỡ trung bình & nhỏ (`MD-01..06`, `LW-01..02` như tự sinh mẫu khi vừa mở tab `QA Studio` trên dự án mới hoặc mã hóa `.txt` Windows CP1258) chưa gộp vào đợt P0–P1 này.
4. **Neo4j & DeepSeek live:** Trong đợt kiểm chứng này, bộ thí nghiệm xác minh `ollama:bge-m3` và `qwen3.5:4b` **live thật**, còn kết nối Neo4j thực tế và API DeepSeek hàng loạt không chạy live trong script tự động (Neo4j chạy qua `_FakeDriver`, trích xuất song song 4 luồng stress test qua `_MockEDCREngine`). Trước khi chạy batch lớn trên tài liệu thật, luôn thực hiện 1 lần `🧪 Chạy thử 1 đoạn mẫu (Dry-run)` như đã hướng dẫn ở tài liệu CIDOC song ngữ.

---

## 5. Tài Liệu & Hiện Vật Kèm Theo

- **Mã nguồn kiểm thử hồi quy P0 + P1:** [`tests/test_p0_p1_fixes.py`](file:///d:/DATN/CrawData/KG_Studio/tests/test_p0_p1_fixes.py)
- **Script chạy 6 thực nghiệm cô lập:** [`AI/report_ver2/evidence/run_p0_p1_experiments.py`](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/run_p0_p1_experiments.py)
- **Dữ liệu kết quả thực nghiệm JSON:** [`AI/report_ver2/evidence/p0_p1_experiments_results.json`](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/p0_p1_experiments_results.json)
- **Bộ danh mục mẫu CIDOC CRM song ngữ (30 lớp, 55 quan hệ):** [`AI/report_ver2/evidence/cidoc_starter/`](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/evidence/cidoc_starter)
- **Hướng dẫn thao tác từng bước trên UI cho CIDOC song ngữ:** [`AI/report_ver2/huong-dan-cidoc-crm-song-ngu.md`](file:///d:/DATN/CrawData/KG_Studio/AI/report_ver2/huong-dan-cidoc-crm-song-ngu.md)
