# Baseline Inventory & Environment Manifest (L00)

- **Run ID:** `2026-11-13-run01`
- **Thời gian lập:** 2026-11-13 16:10:00
- **Git HEAD:** `c92a6d6f689177c98e3ec998ce2cf2c6d8389b38`
- **Branch:** `feature/fastapi-pydantic-v2`
- **Python Runtime:** 3.13.2 (Windows AMD64)
- **Status:** `PASS` (Baseline tái lập thành công 100%)

---

## 1. Môi trường & Bộ thực thi Kiểm thử

- **Runner kiểm thử cô lập:** `tools/run_isolated_tests.py`
  - Đã bổ sung cấu hình đóng gói theme `.streamlit` và template từ điển mẫu `data/hanoi_historical_gazetteer.json` vào shadow workspace theo allowlist chính xác (tuân thủ mục 3 & 9 trong `AGENTS.md`, không sao chép dữ liệu thật hoặc secrets).
  - Lệnh: `.\.venv-win\Scripts\python.exe tools\run_isolated_tests.py`
  - Kết quả: **239/239 tests PASS** (0 failures, 0 errors, thời gian chạy: 9.594s).
- **Bộ kiểm tra ranh giới kiến trúc:** `tests/test_architecture_boundaries.py`
  - Lệnh: `.\.venv-win\Scripts\python.exe tools\run_isolated_tests.py tests.test_architecture_boundaries`
  - Kết quả: **4/4 tests PASS** (thời gian chạy: 0.328s).
- **Công cụ Khám phá Code Graphify:**
  - `graphify` CLI có sẵn trên PATH hệ thống (`graphify 0.4.x`).
  - Lệnh `graphify query "legacy coordinator lock"` thành công, trả về 2.836 nodes, 8.480 edges.

---

## 2. Inventory Working Tree Hiện tại

### 2.1. Tệp Đã Sửa Đổi (Tracked Modified)
- `tools/run_isolated_tests.py`: Cho phép copy `.streamlit` và `data/hanoi_historical_gazetteer.json`.
- `.streamlit/config.toml`: Cấu hình theme Light tương phản cao.
- `AGENTS.md`: Hướng dẫn kiến trúc, ranh giới và quy tắc làm việc.
- `AI/structure.md`: Bản đồ cấu trúc thư mục và trách nhiệm các tầng.
- `backend/facade.py`: Forwarding facade cho 6 application services.
- `backend/modules/curation/application/service.py`: Curation application service.
- `frontend/app.py`: Entrypoint Streamlit.
- `frontend/state/session.py`: Facade re-export tường minh (159 LOC).
- `frontend/components/prompt_editor.py`: 5 helper phân rã (468 LOC).
- `frontend/components/export_tabs/g_retriever_tab.py`: 5 helper phân rã (449 LOC).
- `frontend/components/merge/entity_tab.py`: Phân rã helper (512 LOC).
- `frontend/components/merge/relation_tab.py`: Phân rã helper (491 LOC).

### 2.2. Tệp Đã Xóa và Thay Thế bằng Package (Tracked Deleted)
- `frontend/components/curation_table.py` → thay bằng package `frontend/components/curation_table/` (5 files).
- `frontend/components/evidence_panel.py` → thay bằng package `frontend/components/evidence_panel/` (4 files).
- `frontend/components/edc_review_table.py` → thay bằng package `frontend/components/edc_review_table/` (4 files).
- `frontend/components/edc_bulk_actions.py` → thay bằng package `frontend/components/edc_bulk_actions/` (3 files).

### 2.3. Tệp Mới Chưa Track (Untracked)
- `AI/layout/*`: Đặc tả layout và kế hoạch UI/UX.
- `AI/report/*`: Các báo cáo kiểm toán và kế hoạch retirement.
- `backend/domain/curation/gazetteer.py`: Logic từ điển địa danh dự án thuần túy.
- `data/hanoi_historical_gazetteer.json`: Template mẫu từ điển di tích lịch sử Hà Nội.
- `frontend/components/gazetteer_panel.py`: Giao diện thiết lập từ điển tại Bước 2.
- `frontend/components/merge/entity_logic.py`: Logic preview và execute merge thực thể thuần túy.
- `frontend/state/` (`core.py`, `curation_state.py`, `edc_state.py`, `llm_state.py`, `navigation.py`): 5 module DAG state.
- `tests/test_evidence_matching.py`: Kiểm thử đối soát chuỗi bằng chứng.
- `tests/test_gazetteer_feedback_loop.py`: Kiểm thử vòng phản hồi từ điển sau gộp thực thể.
- `tests/test_ui_ux_improvements.py`: AppTest kiểm thử giao diện U1–U6.

---

## 3. Kết luận Cổng Kiểm soát L00

- Môi trường chạy kiểm thử cô lập được tái lập hoàn chỉnh; không còn lỗi harness do thiếu theme hay template.
- Cơ sở mã nguồn đạt trạng thái 100% xanh ở thời điểm bắt đầu triển khai kế hoạch L01–L09.
