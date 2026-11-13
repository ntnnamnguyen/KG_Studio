"""Kiểm thử toàn diện dự án độc lập KG_Studio (Đảm bảo 0% phụ thuộc vào KG_Studio_MVP cũ)."""
from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import tempfile
import unittest
from pathlib import Path

from backend.api.v1 import handle_api_request
from backend.domain.catalogs.service import decide_proposal
from backend.domain.curation.service import set_edge_status
from backend.domain.dataset_exporter.exporter import ActiveLearningExporter
from backend.domain.documents.processor import add_document, document_chunks
from backend.domain.extraction.base_engine import ChunkContext
from backend.domain.extraction.engines.edc_plus_r import EDCPlusREngine
from backend.domain.schema_intelligence.aligner import TargetAligner
from backend.domain.schema_intelligence.retriever import SchemaRetriever
from backend.facade import KGStudioFacade
from backend.integrations.embedder_gateway import EmbedderGateway
from backend.integrations.llm import LLMGateway, PROVIDER_DEEPSEEK, PROVIDER_OLLAMA
from backend.repositories.json_repo import JsonProjectRepository, empty_project
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from ml_lab.evaluation.benchmark import run_retriever_benchmark
from ml_lab.trainers.finetune_llm_lora import generate_lora_training_bundle
from ml_lab.trainers.train_canonicalizer import train_canonicalizer_model
from ml_lab.trainers.train_schema_retriever import train_schema_retriever_model
from shared.catalog_utils import apply_relations
from shared.config_loader import APP_ROOT, CONFIG_PATH, load_config, save_llm_token_config_to_toml
from shared.constants import EXTRACTION_MODES, MODE_EDC_PLUS_R, STATUS_APPROVED, STATUS_REJECTED


FORBIDDEN_LEGACY_MODULES = {
    "core",
    "services",
    "settings",
    "catalogs",
    "catalog_store",
    "edc_contract",
    "ui_edc",
}

SAMPLE_TEXT = (
    "Chùa Một Cột tọa lạc tại quận Ba Đình, được xây dựng năm 1049 dưới thời vua Lý Thái Tông. "
    "Năm 1955, Chùa Một Cột được trùng tu lớn."
)


@dataclass
class _FakeUsage:
    prompt_tokens: int = 100
    completion_tokens: int = 60


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage
    finish_reason: str = "stop"


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]
    usage: _FakeUsage


class _FakeCompletions:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self.payloads) - 1)
        return _FakeResponse(
            choices=[_FakeMessage(json.dumps(self.payloads[idx], ensure_ascii=False))],
            usage=_FakeUsage(),
        )


class _FakeCompletionsFixed(_FakeCompletions):
    def create(self, **kwargs):
        self.calls.append(kwargs)
        idx = min(len(self.calls) - 1, len(self.payloads) - 1)
        return _FakeResponse(
            choices=[_FakeChoice(_FakeMessage(json.dumps(self.payloads[idx], ensure_ascii=False)))],
            usage=_FakeUsage(),
        )


class _FakeChat:
    def __init__(self, payloads: list[dict]) -> None:
        self.completions = _FakeCompletionsFixed(payloads)


class FakeOpenAIClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.chat = _FakeChat(payloads)


class StandaloneArchitectureTests(unittest.TestCase):
    def test_zero_dependency_on_legacy_mvp_code(self) -> None:
        """Quét AST của toàn bộ file .py trong KG_Studio để chứng minh 0% phụ thuộc vào code cũ."""
        py_files = [
            p
            for p in APP_ROOT.rglob("*.py")
            if ".venv" not in p.parts and "__pycache__" not in p.parts
        ]
        self.assertGreaterEqual(len(py_files), 30)

        for py_file in py_files:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_pkg = alias.name.split(".")[0]
                        self.assertNotIn(
                            top_pkg,
                            FORBIDDEN_LEGACY_MODULES,
                            f"File {py_file} vẫn import module cũ: {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    top_pkg = node.module.split(".")[0]
                    self.assertNotIn(
                        top_pkg,
                        FORBIDDEN_LEGACY_MODULES,
                        f"File {py_file} vẫn from-import module cũ: {node.module}",
                    )

    def test_edc_plus_r_retriever_and_target_aligner_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vec_repo = VectorIndexRepository(tmp)
            embedder = EmbedderGateway("hybrid_vn:default")
            retriever = SchemaRetriever(vector_repo=vec_repo, embedder=embedder)
            aligner = TargetAligner(vector_repo=vec_repo, embedder=embedder)

            project = empty_project("Test EDC+R Standalone")
            project["extraction_mode"] = MODE_EDC_PLUS_R
            apply_relations(
                project,
                [
                    {
                        "name": "nằm tại",
                        "description": "Vị trí địa lý của di tích",
                        "definition": "Thực thể nguồn có vị trí địa lý thuộc địa điểm hoặc khu vực đích.",
                    },
                    {
                        "name": "xây dựng năm",
                        "description": "Năm khởi công xây dựng",
                        "definition": "Công trình nguồn được khởi công hoặc xây dựng vào năm đích.",
                    },
                    {
                        "name": "thờ phụng",
                        "description": "Đối tượng được thờ tại di tích",
                        "definition": "Di tích nguồn là nơi thờ cúng nhân vật hoặc vị thần đích.",
                    },
                ],
            )
            add_document(project, "chua_mot_cot.txt", SAMPLE_TEXT.encode("utf-8"))

            retrieved = retriever.retrieve_for_chunk(
                project,
                SAMPLE_TEXT,
                top_k_relations=2,
                top_k_entity_types=2,
                embedder=embedder,
            )
            rel_names = [r["name"] for r in retrieved["relations"]]
            self.assertIn("nằm tại", rel_names)

            cands = aligner.rank_candidates(
                project,
                "relations",
                "tọa lạc tại",
                "Di tích nguồn có vị trí địa lý nằm tại địa điểm đích.",
                embedder=embedder,
            )
            self.assertEqual(cands[0].name, "nằm tại")
            self.assertGreater(cands[0].score, 0.55)

    def test_edc_plus_r_engine_refinement_and_auto_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vec_repo = VectorIndexRepository(tmp)
            engine = EDCPlusREngine(
                retriever=SchemaRetriever(vector_repo=vec_repo),
                aligner=TargetAligner(vector_repo=vec_repo),
            )
            project = empty_project("Test Engine")
            project["extraction_mode"] = MODE_EDC_PLUS_R
            project["edc_plus_r_settings"] = {
                "embedder_model": "hybrid_vn:default",
                "top_k_relations": 3,
                "top_k_entity_types": 3,
                "auto_align_threshold": 0.60,
                "candidate_threshold": 0.30,
                "refinement_loops": 2,
                "enable_llm_verifier": False,
            }
            add_document(project, "chua_mot_cot.txt", SAMPLE_TEXT.encode("utf-8"))
            doc = project["documents"][0]
            chunk_rec = document_chunks(doc)[0]

            loop1 = {
                "thuc_the": [
                    {"ten": "Chùa Một Cột", "loai": "di tích", "mo_ta": "Ngôi chùa cổ"},
                    {"ten": "quận Ba Đình", "loai": "quận", "mo_ta": "Quận trung tâm"},
                ],
                "quan_he": [
                    {
                        "nguon": "Chùa Một Cột",
                        "quan_he": "tọa lạc ở",
                        "dich": "quận Ba Đình",
                        "trich_dan": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                    }
                ],
                "dinh_nghia_quan_he": [
                    {"ten": "tọa lạc ở", "dinh_nghia": "Thực thể nguồn nằm tại vị trí địa lý ở địa điểm đích."}
                ],
                "dinh_nghia_loai": [
                    {"ten": "di tích", "dinh_nghia": "Công trình văn hóa lịch sử"},
                    {"ten": "quận", "dinh_nghia": "Đơn vị hành chính cấp quận"},
                ],
            }
            loop2 = {
                "thuc_the": loop1["thuc_the"] + [{"ten": "1955", "loai": "niên đại", "mo_ta": "Năm trùng tu"}],
                "quan_he": loop1["quan_he"]
                + [
                    {
                        "nguon": "Chùa Một Cột",
                        "quan_he": "tu bổ năm",
                        "dich": "1955",
                        "trich_dan": "Năm 1955, Chùa Một Cột được trùng tu lớn.",
                    }
                ],
                "dinh_nghia_quan_he": loop1["dinh_nghia_quan_he"]
                + [{"ten": "tu bổ năm", "dinh_nghia": "Di tích được sửa chữa và trùng tu vào năm đích."}],
                "dinh_nghia_loai": loop1["dinh_nghia_loai"]
                + [{"ten": "niên đại", "dinh_nghia": "Mốc thời gian theo năm"}],
            }

            fake_client = FakeOpenAIClient([loop1, loop2])
            ctx = ChunkContext(
                project=project,
                document=doc,
                chunk_record=chunk_rec,
                provider="OpenAI / API tương thích",
                api_key="test",
                model="gpt-4o-mini",
                client=fake_client,
            )
            out = engine.process_chunk(ctx)
            self.assertEqual(len(fake_client.chat.completions.calls), 2)
            self.assertEqual(len(out.step_traces), 5)
            self.assertEqual(len(project["edges"]), 2)

    def test_active_learning_ml_lab_and_rest_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facade = KGStudioFacade(
                json_repo=JsonProjectRepository(tmp_path / "projects"),
                sqlite_repo=SQLiteProjectRepository(tmp_path / "test.db"),
                vector_repo=VectorIndexRepository(tmp_path / "vectors"),
                exporter=ActiveLearningExporter(tmp_path / "exports"),
            )
            project = facade.load_project("ML_Project")
            project["extraction_mode"] = MODE_EDC_PLUS_R
            apply_relations(
                project,
                [
                    {
                        "name": "được xây dựng vào",
                        "description": "Thời gian xây dựng.",
                        "definition": "Công trình nguồn được xây dựng vào mốc hoặc giai đoạn đích.",
                    },
                    {
                        "name": "nằm tại",
                        "description": "Vị trí địa lý.",
                        "definition": "Nguồn có vị trí tại địa điểm đích.",
                    },
                ],
            )
            add_document(project, "chua_mot_cot.txt", SAMPLE_TEXT.encode("utf-8"))
            doc = project["documents"][0]
            rec = facade.document_chunks(doc)[0]

            payload = {
                "thuc_the": [
                    {"ten": "Chùa Một Cột", "loai": "di tích", "mo_ta": "Di tích"},
                    {"ten": "quận Ba Đình", "loai": "quận", "mo_ta": "Quận"},
                    {"ten": "1049", "loai": "niên đại", "mo_ta": "Năm"},
                ],
                "quan_he": [
                    {
                        "nguon": "Chùa Một Cột",
                        "quan_he": "nằm tại",
                        "dich": "quận Ba Đình",
                        "trich_dan": "Chùa Một Cột tọa lạc tại quận Ba Đình",
                    },
                    {
                        "nguon": "Chùa Một Cột",
                        "quan_he": "khởi dựng vào",
                        "dich": "1049",
                        "trich_dan": "được xây dựng năm 1049",
                    },
                ],
                "dinh_nghia_quan_he": [
                    {"ten": "nằm tại", "dinh_nghia": "Vị trí địa lý"},
                    {"ten": "khởi dựng vào", "dinh_nghia": "Công trình được khởi công xây dựng vào năm đích"},
                ],
                "dinh_nghia_loai": [
                    {"ten": "di tích", "dinh_nghia": "Di tích"},
                    {"ten": "quận", "dinh_nghia": "Quận"},
                    {"ten": "niên đại", "dinh_nghia": "Năm"},
                ],
            }
            facade.extract_chunk(
                project,
                doc,
                rec,
                provider="OpenAI / API tương thích",
                api_key="test",
                model="gpt-4o-mini",
                client=FakeOpenAIClient([payload]),
            )

            for prop in list(project["schema_proposals"]):
                if prop["status"] == "pending":
                    if prop["kind"] == "relations":
                        decide_proposal(project, prop["id"], "merge", canonical_name="được xây dựng vào")
                    else:
                        decide_proposal(
                            project,
                            prop["id"],
                            "approve",
                            canonical_name=prop["name"],
                            definition=prop.get("definition") or "Loại thực thể di sản",
                        )

            set_edge_status(project, project["edges"][0]["id"], STATUS_APPROVED)
            set_edge_status(project, project["edges"][1]["id"], STATUS_REJECTED)
            facade.save_project(project)

            export_report = facade.export_training_datasets(project)
            self.assertGreaterEqual(export_report["sr_triplets_count"], 1)

            reg_dir = tmp_path / "registry"
            sr_meta = train_schema_retriever_model(export_report["files"]["sr_triplets"], "sr-test", registry_dir=reg_dir)
            self.assertTrue(sr_meta["model_id"].startswith("registry:"))

            canon_meta = train_canonicalizer_model(export_report["files"]["canonicalization_pairs"], "canon-test", registry_dir=reg_dir)
            self.assertTrue(canon_meta["model_id"].startswith("registry:"))

            lora_meta = generate_lora_training_bundle(export_report["files"]["sft_extractions"], "lora-test", registry_dir=reg_dir)
            self.assertTrue(Path(lora_meta["script_path"]).exists())

            board = run_retriever_benchmark(export_report["files"]["sr_triplets"], registry_dir=reg_dir)
            self.assertGreaterEqual(len(board), 2)

            status, health = handle_api_request("GET", "/api/v1/health", facade=facade)
            self.assertEqual(status, 200)
            self.assertEqual({m["mode_id"] for m in health["modes"]}, set(EXTRACTION_MODES))

    def test_migrated_projects_exist_and_load_in_standalone_app(self) -> None:
        facade = KGStudioFacade()
        projects = facade.list_projects()
        target = "HaNoiQA6" if "HaNoiQA6" in projects else next((p for p in projects if "hanoi" in p.lower()), projects[0] if projects else "HanoiQA")
        self.assertIn(target, projects)
        p1 = facade.load_project(target)
        self.assertGreaterEqual(len(p1.get("documents", [])), 1)
        self.assertGreaterEqual(len(p1.get("nodes", [])), 1)
        self.assertGreaterEqual(len(p1.get("edges", [])), 1)

    def test_deepseek_token_auto_recommend_and_save_toml(self) -> None:
        rec_ds = LLMGateway.recommend_token_limits(PROVIDER_DEEPSEEK, "deepseek-chat")
        self.assertEqual(rec_ds["max_input_tokens"], 12000)
        self.assertEqual(rec_ds["max_output_tokens"], 8192)
        self.assertEqual(rec_ds["api_max_output_cap"], 16384)

        rec_ol = LLMGateway.recommend_token_limits(PROVIDER_OLLAMA, "qwen3.5:latest")
        self.assertEqual(rec_ol["max_input_tokens"], 4096)
        self.assertEqual(rec_ol["max_output_tokens"], 4096)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_toml = Path(tmp) / "default.toml"
            tmp_toml.write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            save_llm_token_config_to_toml(
                provider_key="deepseek",
                model="deepseek-chat",
                base_url="https://api.deepseek.com/v1",
                max_input_tokens=16384,
                max_output_tokens=8192,
                chunk_size=5000,
                path=tmp_toml,
            )
            reloaded = load_config(tmp_toml)
            self.assertEqual(reloaded["llm"]["default_provider"], "deepseek")
            self.assertEqual(reloaded["llm"]["max_input_tokens"], 16384)
            self.assertEqual(reloaded["llm"]["max_tokens"], 8192)
            self.assertEqual(reloaded["llm"]["providers"]["deepseek"]["max_input_tokens"], 16384)
            self.assertEqual(reloaded["extraction"]["chunk_size"], 5000)
            # Khôi phục CONFIG trong bộ nhớ từ CONFIG_PATH gốc
            load_config(CONFIG_PATH)

    def test_empty_default_catalogs_and_json_upload(self) -> None:
        from shared.catalog_utils import parse_catalog, relation_catalog
        import shared.config_loader as cfg_mod

        # Đảm bảo không còn biến hardcode DEFAULT_BUILTIN_*
        self.assertFalse(hasattr(cfg_mod, "DEFAULT_BUILTIN_RELATIONS"))
        self.assertFalse(hasattr(cfg_mod, "DEFAULT_BUILTIN_ENTITY_TYPES"))

        # Dự án rỗng khởi tạo với danh mục rỗng
        proj = empty_project("CleanProject")
        self.assertEqual(proj["relations"], [])
        self.assertEqual(proj["relation_notes"], {})
        self.assertEqual(proj["entity_types"], [])
        self.assertEqual(relation_catalog(proj), [])

        # Kiểm tra nạp file JSON dưới dạng mảng thuần
        raw_json_array = json.dumps([{"name": "sở hữu", "description": "Sở hữu tài sản"}]).encode("utf-8")
        parsed_rels = parse_catalog(raw_json_array, "relations")
        self.assertEqual(len(parsed_rels), 1)
        self.assertEqual(parsed_rels[0]["name"], "sở hữu")

        # Kiểm tra nạp file JSON dưới dạng bọc schema
        schema_json = json.dumps({"schema_version": 2, "entity_types": [{"name": "cổ vật", "description": "Hiện vật cổ"}]}).encode("utf-8")
        parsed_types = parse_catalog(schema_json, "entity_types")
        self.assertEqual(len(parsed_types), 1)
        self.assertEqual(parsed_types[0]["name"], "cổ vật")

        # Kiểm tra nạp file CSV có tiêu đề tiếng Anh
        from shared.catalog_utils import catalog_csv_bytes
        csv_en = "name,description,definition\nE21 Person,Nhân vật,Con người cụ thể\nE53 Place,Địa danh,Vị trí địa lý\n".encode("utf-8-sig")
        parsed_csv = parse_catalog(csv_en, "entity_types", filename="types.csv")
        self.assertEqual(len(parsed_csv), 2)
        self.assertEqual(parsed_csv[0]["name"], "E21 Person")
        self.assertEqual(parsed_csv[0]["description"], "Nhân vật")
        self.assertEqual(parsed_csv[0]["definition"], "Con người cụ thể")

        # Kiểm tra nạp file CSV có tiêu đề tiếng Việt
        csv_vi = "tên,mô tả,định nghĩa\nP14 carried out by,Do ai thực hiện,Quan hệ chỉ huy\nP7 took place at,Diễn ra tại,Địa điểm\n".encode("utf-8")
        parsed_rel_csv = parse_catalog(csv_vi, "relations", filename="relations.csv")
        self.assertEqual(len(parsed_rel_csv), 2)
        self.assertEqual(parsed_rel_csv[0]["name"], "P14 carried out by")
        self.assertEqual(parsed_rel_csv[1]["name"], "P7 took place at")

        # Kiểm tra xuất và tái phân tích (roundtrip) CSV với BOM
        csv_bytes = catalog_csv_bytes(parsed_csv, "entity_types")
        self.assertTrue(csv_bytes.startswith(b"\xef\xbb\xbf"))  # UTF-8 BOM
        reparsed = parse_catalog(csv_bytes, "entity_types", filename="exported.csv")
        self.assertEqual(len(reparsed), 2)
        self.assertEqual(reparsed[0]["name"], "E21 Person")

        # Kiểm tra giải mã an toàn CSV mã hóa ANSI/CP1258 từ Excel Windows chứa byte 0xd0
        # 0xd0 trong CP1258 là chữ Đ ("Địa danh")
        cp1258_csv_bytes = bytes([
            0x6e, 0x61, 0x6d, 0x65, 0x2c, 0x64, 0x65, 0x73, 0x63, 0x72, 0x69, 0x70, 0x74, 0x69, 0x6f, 0x6e, 0x0a,
            0x45, 0x35, 0x33, 0x20, 0x50, 0x6c, 0x61, 0x63, 0x65, 0x2c,
            0xd0, 0x69, 0xf2, 0x61, 0x20, 0x64, 0x61, 0x6e, 0x68, 0x0a,
        ])
        parsed_cp1258 = parse_catalog(cp1258_csv_bytes, "entity_types", filename="excel_ansi.csv")
        self.assertEqual(len(parsed_cp1258), 1)
        self.assertEqual(parsed_cp1258[0]["name"], "E53 Place")
        self.assertEqual(parsed_cp1258[0]["description"], "Địa danh")

    def test_add_document_via_facade_and_extraction_service(self) -> None:
        """Kiểm tra add_document và document_chunks qua facade và extraction_service."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            json_repo = JsonProjectRepository(tmp_path / "projects")
            sqlite_repo = SQLiteProjectRepository(tmp_path / "test.db")
            vector_repo = VectorIndexRepository(tmp_path / "vectors")
            facade = KGStudioFacade(
                json_repo=json_repo,
                sqlite_repo=sqlite_repo,
                vector_repo=vector_repo,
            )
            proj = empty_project("DocTestProj")
            sample_content = "Đình Kim Liên thờ phụng Cao Sơn Đại Vương tại phường Phương Liên, Đống Đa, Hà Nội."

            # 1. Gọi qua facade với bytes
            ok, msg = facade.add_document(proj, "dinh_kim_lien.txt", sample_content.encode("utf-8"), "Hà Nội", "Hồ sơ 2024")
            self.assertTrue(ok)
            self.assertIn("Đã thêm dinh_kim_lien.txt", msg)
            self.assertEqual(len(proj.get("documents", [])), 1)
            doc = proj["documents"][0]
            self.assertEqual(doc["name"], "dinh_kim_lien.txt")
            self.assertEqual(doc["place_scope"], "Hà Nội")
            self.assertEqual(doc["source_label"], "Hồ sơ 2024")

            # 2. Gọi lại với nội dung trùng -> False
            ok2, msg2 = facade.add_document(proj, "dinh_kim_lien.txt", sample_content.encode("utf-8"))
            self.assertFalse(ok2)
            self.assertIn("Tài liệu trùng nội dung", msg2)

            # 3. Gọi qua extraction_service trực tiếp bằng string
            sample_content_2 = "Chùa Một Cột tọa lạc tại quận Ba Đình, Hà Nội. Được xây dựng năm 1049."
            ok3, msg3 = facade.extraction_service.add_document(proj, "chua_mot_cot.txt", sample_content_2)
            self.assertTrue(ok3)
            self.assertEqual(len(proj["documents"]), 2)

            # 4. Kiểm tra document_chunks
            chunks = facade.document_chunks(doc, limit=500, overlap=50)
            self.assertGreater(len(chunks), 0)
            self.assertEqual(chunks[0]["doc_id"], doc["id"])


if __name__ == "__main__":
    unittest.main()
