# KG Studio Pro (`D:\DATN\CrawData\KG_Studio`) — Độc lập 100%

Bộ mã nguồn **KG Studio Pro** được tổ chức thành một dự án **hoàn toàn độc lập** tại `D:\DATN\CrawData\KG_Studio`, **không phụ thuộc bất kỳ file code nào của `KG_Studio_MVP` cũ**.

## 1. Cấu trúc Thư mục Chuẩn Thương mại & Học máy

```text
D:\DATN\CrawData\KG_Studio\
├── pyproject.toml                 # Đóng gói chuẩn Python
├── run_app.py                     # Khởi chạy Streamlit UI độc lập (cổng 8502)
├── run_windows.cmd                # Script chạy nhanh trên Windows
├── config/                        # Cấu hình tập trung & Danh mục gốc
│   ├── default.toml
│   ├── logging.yaml
│   └── catalogs/
│       ├── relations.json
│       └── entity_types.json
├── shared/                        # Tầng dùng chung (Zero Training-Serving Skew)
│   ├── config_loader.py
│   ├── constants.py
│   ├── text_utils.py
│   ├── catalog_utils.py
│   ├── prompt_templates/
│   └── schemas/                   # DTOs tĩnh (Project, Graph, EDC, Training Records)
├── backend/                       # TẦNG BACKEND & API (Không dính code UI)
│   ├── main.py                    # Máy chủ REST API (/api/v1)
│   ├── facade.py                  # Điều phối trung tâm
│   ├── api/v1.py                  # Endpoints REST API
│   ├── domain/                    # Nghiệp vụ cốt lõi (Độc lập 100%)
│   │   ├── documents/             # Đọc DOCX/PDF/TXT & chia chunk
│   │   ├── catalogs/              # Quản lý danh mục, prompt & đề xuất EDC
│   │   ├── extraction/            # Pluggable Engines: Fixed, EDC 1-Pass, EDC+R
│   │   ├── schema_intelligence/   # SchemaRetriever (+R) & TargetAligner
│   │   ├── curation/              # Kiểm duyệt bằng chứng & gộp thực thể
│   │   ├── graph/                 # Kiểm tra toàn vẹn & xuất JSON/CSV/ZIP
│   │   └── dataset_exporter/      # Xuất dữ liệu Active Learning (.jsonl)
│   ├── repositories/              # Tầng lưu trữ vật lý
│   │   ├── json_repo.py           # Lưu trữ project JSON + snapshots tại data/projects/
│   │   ├── sqlite_repo.py         # Cơ sở dữ liệu SQLite tại data/kg_studio.db
│   │   └── vector_repo.py         # Chỉ mục Vector theo model_fingerprint tại data/vector_indices/
│   ├── integrations/              # Cổng kết nối ngoài
│   │   ├── embedder_gateway.py    # Nhúng tiếng Việt (Hybrid / SentenceTransformers / Ollama)
│   │   ├── llm_gateway.py         # OpenAI / Ollama / Qwen / DeepSeek / Anthropic
│   │   └── neo4j_gateway.py       # Đồng bộ Neo4j
│   └── workers/job_manager.py     # Quản lý tiến trình
├── frontend/                      # TẦNG GIAO DIỆN ĐA TRANG (Chỉ gọi Backend/Client)
│   ├── app.py                     # Entrypoint điều hướng
│   ├── client.py                  # Client gọi Backend / API
│   ├── state/session.py           # Quản lý Session State (theo project_id + kind)
│   ├── components/                # Step Traces, EDC+R Panel, EDC Bulk Review Tables, ML Lab Panel
│   └── pages/                     # 6 màn hình chức năng độc lập (p01 -> p06)
├── ml_lab/                        # PHÒNG THÍ NGHIỆM HỌC MÁY ĐỘC LẬP
│   ├── configs/
│   ├── trainers/                  # Train Schema Retriever (+R), Target Aligner, QLoRA
│   └── evaluation/                # Benchmark Recall@K & MRR
├── data/                          # Dữ liệu vật lý (Đã sao chép sẵn hanoiqa & hanoiqav2)
│   ├── projects/
│   ├── kg_studio.db
│   ├── vector_indices/
│   ├── training_exports/
│   └── model_registry/
└── tests/                         # Kiểm thử tự động (Kèm AST test chứng minh 0 phụ thuộc code cũ)
```

## 2. Thiết lập Cấu hình & Bảo mật API Keys

Trước khi chạy, sao chép file mẫu và cấu hình API key cá nhân của bạn:

```powershell
# Cách 1: Sử dụng config/.secrets.toml (Khuyến nghị cho KG Studio)
cp config/.secrets.toml.example config/.secrets.toml
# Sau đó mở config/.secrets.toml và điền key của DeepSeek / OpenAI / Claude / Qwen

# Cách 2: Sử dụng biến môi trường qua file .env
cp .env.example .env
```
*(Lưu ý: File `.secrets.toml` và `.env` đã được cấu hình trong `.gitignore`, tuyệt đối không commit các file chứa key thực tế lên GitHub).*

## 3. Cách chạy độc lập

### Chạy giao diện KG Studio Pro (mặc định cổng `8502` để có thể chạy song song với MVP cũ nếu muốn):
```powershell
cd D:\DATN\CrawData\KG_Studio
.\run_windows.cmd
```
Mở trình duyệt tại: **http://127.0.0.1:8502**

### Chạy máy chủ REST API độc lập (cổng `8000`):
```powershell
cd D:\DATN\CrawData\KG_Studio
python -m backend.main --host 127.0.0.1 --port 8000
```

### Chạy bộ kiểm thử độc lập:
```powershell
cd D:\DATN\CrawData\KG_Studio
python -m unittest discover -s tests -t . -v
```

