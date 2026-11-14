"""Bộ kiểm thử hồi quy offline toàn diện cho các bản vá P0 (CR-01..CR-08) và P1 (HI-01..HI-08)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from typing import Any

from backend.domain.catalogs.core import compute_project_revision
from backend.domain.curation.entities import duplicate_suggestions, mark_pair_not_duplicate, review_stats
from backend.domain.curation.merge_core import _clone_project_for_merge_mutation, flatten_redirects
from backend.domain.curation.review import set_edge_status
from backend.domain.curation.semantic_clustering import bulk_apply_entity_type_merges
from backend.domain.extraction.base_engine import BaseExtractionEngine, ChunkContext, EngineOutput
from backend.domain.extraction.registry import EngineRegistry
from backend.domain.graph.g_retriever import (
    answer_question_with_graph,
    get_or_build_graph_index,
    retrieve_subgraph,
)
from backend.domain.graph.qa_generator import generate_training_qa_dataset
from backend.domain.prompts.service import get_active_prompt_version, save_prompt_version
from backend.domain.schema_intelligence.aligner import TargetAligner
from backend.facade import KGStudioFacade
from backend.integrations.llm.parsing import pick_choice_letter
from backend.integrations.neo4j_gateway import CONSTRAINT_ENTITY_ID, MERGE_EDGES, Neo4jGateway
from backend.modules.curation.application.service import CurationApplicationService
from backend.modules.extraction.application.service import ExtractionApplicationService
from backend.modules.graph_qa.application.service import GraphQAApplicationService
from backend.modules.projects.application.commit_coordinator import ProjectCommitCoordinator
from backend.modules.projects.application.service import ProjectsApplicationService
from backend.modules.schema_intelligence.application.service import SchemaIntelligenceApplicationService
from backend.modules.training.application.service import TrainingApplicationService
from backend.repositories.json_repo import JsonProjectRepository, empty_project
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from shared.catalog_utils import (
    apply_relations,
    catalog_bytes,
    catalog_csv_bytes,
    parse_catalog,
    relation_catalog,
)
from shared.constants import MODE_EDC_PLUS_R, STATUS_APPROVED, STATUS_CHECK, STATUS_PENDING, STATUS_REJECTED
from shared.prompt_templates import (
    PASSAGE_TEMPLATE_VERSION,
    format_catalog_passage,
    format_sr_query,
    should_use_e5_instruct,
)
from shared.schemas.project import EDCPlusRSettingsDTO


def _make_sample_project(pid: str = "proj_p0_p1") -> dict[str, Any]:
    proj = empty_project("Du an Kiem thu P0 P1")
    proj["project_id"] = pid
    proj["documents"] = [
        {
            "id": "doc_1",
            "name": "van_mieu.txt",
            "text": "Văn Miếu Quốc Tử Giám được xây dựng vào năm 1070 tại Thăng Long dưới triều vua Lý Thánh Tông.",
        }
    ]
    proj["nodes"] = [
        {"id": "n_vm", "name": "Văn Miếu Quốc Tử Giám", "kind": "E22_Human-Made_Object", "aliases": ["Văn Miếu"]},
        {"id": "n_tl", "name": "Thăng Long", "kind": "E53_Place", "aliases": []},
        {"id": "n_1070", "name": "năm 1070", "kind": "E52_Time-Span", "aliases": []},
        {"id": "n_ltt", "name": "Lý Thánh Tông", "kind": "E21_Person", "aliases": []},
        {"id": "n_nl", "name": "Triều đại nhà Lý", "kind": "E74_Group", "aliases": []},
    ]
    proj["edges"] = [
        {
            "id": "e_1",
            "source": "n_vm",
            "relation": "P53_has_former_or_current_location",
            "target": "n_tl",
            "status": STATUS_APPROVED,
            "evidence": "Văn Miếu Quốc Tử Giám được xây dựng vào năm 1070 tại Thăng Long",
            "evidence_found": True,
            "doc_id": "doc_1",
            "doc_name": "van_mieu.txt",
            "chunk_number": 1,
        },
        {
            "id": "e_2",
            "source": "n_vm",
            "relation": "P4_has_time-span",
            "target": "n_1070",
            "status": STATUS_APPROVED,
            "evidence": "được xây dựng vào năm 1070",
            "evidence_found": True,
            "doc_id": "doc_1",
            "doc_name": "van_mieu.txt",
            "chunk_number": 1,
        },
        {
            "id": "e_3",
            "source": "n_ltt",
            "relation": "P107i_is_current_or_former_member_of",
            "target": "n_nl",
            "status": STATUS_PENDING,
            "evidence": "dưới triều vua Lý Thánh Tông",
            "evidence_found": True,
            "doc_id": "doc_1",
            "doc_name": "van_mieu.txt",
            "chunk_number": 1,
        },
    ]
    proj["entity_types"] = [
        {"name": "E22_Human-Made_Object", "description": "Công trình/hiện vật", "definition": "Hiện vật nhân tạo"},
        {"name": "E53_Place", "description": "Địa điểm", "definition": "Không gian địa lý"},
        {"name": "E52_Time-Span", "description": "Mốc thời gian", "definition": "Khoảng thời gian"},
        {"name": "E21_Person", "description": "Nhân vật", "definition": "Cá nhân lịch sử"},
        {"name": "E74_Group", "description": "Tập thể/triều đại", "definition": "Nhóm người hoặc triều đại"},
    ]
    apply_relations(
        proj,
        [
            {
                "name": "P53_has_former_or_current_location",
                "description": "Vị trí hiện tại hoặc trước đây",
                "definition": "Liên kết di tích với địa danh",
                "domain": "E18_Physical_Thing",
                "range": "E53_Place",
                "aliases": ["tọa lạc tại"],
            },
            {
                "name": "P4_has_time-span",
                "description": "Khung thời gian diễn ra",
                "definition": "Gắn mốc thời gian cho sự kiện/di tích",
                "domain": "E2_Temporal_Entity",
                "range": "E52_Time-Span",
                "aliases": ["có niên đại"],
            },
            {
                "name": "P107i_is_current_or_former_member_of",
                "description": "Thuộc về tổ chức/triều đại",
                "definition": "Nhân vật thuộc nhóm hoặc triều đại",
                "domain": "E21_Person",
                "range": "E74_Group",
                "aliases": ["thuộc triều đại"],
            },
            {
                "name": "tọa lạc tại",
                "description": "Đóng tại địa điểm",
                "definition": "Quan hệ vị trí tiếng Việt",
                "domain": "E22_Human-Made_Object",
                "range": "E53_Place",
                "aliases": [],
            },
        ],
    )
    return proj


class TestP0P1RegressionFixes(unittest.TestCase):
    def test_cr01_catalog_domain_range_aliases_csv_and_json_roundtrip(self) -> None:
        rows = [
            {
                "name": "P108_has_produced",
                "description": "Hoạt động sản xuất tạo ra hiện vật",
                "definition": "Nối E12_Production tới E24_Physical_Human-Made_Thing",
                "domain": "E12_Production",
                "range": "E24_Physical_Human-Made_Thing",
                "aliases": ["đã chế tác", "tạo tác ra"],
            }
        ]
        csv_data = catalog_csv_bytes(rows, "relations")
        parsed_csv = parse_catalog(csv_data, "relations", filename="relations.csv")
        self.assertEqual(len(parsed_csv), 1)
        self.assertEqual(parsed_csv[0]["domain"], "E12_Production")
        self.assertEqual(parsed_csv[0]["range"], "E24_Physical_Human-Made_Thing")
        self.assertEqual(parsed_csv[0]["aliases"], ["đã chế tác", "tạo tác ra"])

        json_data = catalog_bytes(rows, "relations")
        parsed_json = parse_catalog(json_data, "relations", filename="relations.json")
        self.assertEqual(parsed_json[0]["domain"], "E12_Production")
        self.assertEqual(parsed_json[0]["range"], "E24_Physical_Human-Made_Thing")
        self.assertEqual(parsed_json[0]["aliases"], ["đã chế tác", "tạo tác ra"])

        proj = empty_project("CIDOC Roundtrip")
        apply_relations(proj, parsed_csv)
        re_read = relation_catalog(proj)
        self.assertEqual(re_read[0]["domain"], "E12_Production")
        self.assertEqual(re_read[0]["range"], "E24_Physical_Human-Made_Thing")

    def test_cr02_cr05_prompt_version_expected_revision_and_service_signature(self) -> None:
        proj = _make_sample_project()
        active_before = get_active_prompt_version(proj, "edc")
        assert active_before is not None
        with self.assertRaises(ValueError):
            save_prompt_version(
                proj,
                "edc",
                "Prompt mới không khớp revision",
                expected_revision="rev_sai_123",
            )

        svc = ExtractionApplicationService()
        rev_now = compute_project_revision(proj)
        ver, changed = svc.save_prompt_version(
            proj,
            "edc",
            "Hướng dẫn trích xuất mới cho EDC",
            change_description="Cập nhật hướng dẫn",
            author="tester_p0",
            expected_revision=rev_now,
        )
        self.assertTrue(changed)
        self.assertEqual(ver["note"], "Cập nhật hướng dẫn")
        self.assertEqual(ver["created_by"], "tester_p0")

        proj["extraction_mode"] = "edc"
        req = svc.prepare_extraction_request(
            proj,
            "Văn Miếu tại Hà Nội",
            provider="Ollama",
            model="qwen3.5:4b",
        )
        self.assertTrue(req.request_hash)
        self.assertEqual(req.prompt_version_id, ver["id"])

    def test_cr03_evidence_override_note_and_dismissed_pair_filter_and_revision_hash(self) -> None:
        proj = _make_sample_project()
        proj["nodes"].append({"id": "n_vm_dup", "name": "Văn Miếu - Quốc Tử Giám", "kind": "E22_Human-Made_Object", "aliases": []})
        pairs = duplicate_suggestions(proj, fuzzy_threshold=0.82)
        self.assertEqual(len(pairs), 1)
        rev1 = compute_project_revision(proj)
        mark_pair_not_duplicate(proj, pairs[0]["keep_id"], pairs[0]["drop_id"])
        rev2 = compute_project_revision(proj)
        self.assertNotEqual(rev1, rev2)

        from backend.domain.curation.entities import _DUPLICATE_SUGGESTIONS_CACHE
        rev2_cache_key = (str(proj["project_id"]), rev2, 0.82)
        _DUPLICATE_SUGGESTIONS_CACHE[rev2_cache_key] = pairs
        stats_after = review_stats(proj, include_duplicates=False)
        self.assertEqual(stats_after["duplicate_pairs"], 0)

        # Duyệt ngoại lệ có cả review note: vẫn phải giữ tag [Ngoại lệ bằng chứng]
        proj["edges"].append(
            {
                "id": "e_missing_ev",
                "source": "n_vm",
                "relation": "tọa lạc tại",
                "target": "n_tl",
                "status": STATUS_PENDING,
                "evidence": "",
                "doc_id": "doc_1",
                "doc_name": "van_mieu.txt",
            }
        )
        edited = set_edge_status(
            proj,
            "e_missing_ev",
            STATUS_APPROVED,
            override_reason="Xác minh từ tài liệu lưu trữ",
            reviewer="reviewer_p0",
            note="Ghi chú biên tập viên",
            allow_schema_bypass=True,
        )
        self.assertIn("[Ngoại lệ bằng chứng]", edited["review_note"])
        self.assertIn("Ghi chú biên tập viên", edited["review_note"])

    def test_cr04_bulk_merge_invalidates_approved_edges_and_rejects_redirect_cycle(self) -> None:
        with self.assertRaises(ValueError):
            flatten_redirects({"n_a": "n_b", "n_b": "n_a"})

        proj = _make_sample_project()
        proj["domain_gazetteer"] = {"Thăng Long": {"name": "Thăng Long", "kind": "Địa danh"}}
        clone = _clone_project_for_merge_mutation(proj)
        clone["domain_gazetteer"]["Extra"] = {"name": "Extra", "kind": "Other"}
        self.assertEqual(len(proj["domain_gazetteer"]), 1)

        # Thiếu coordinator -> fail closed
        curation_no_coord = CurationApplicationService(commit_coordinator=None)
        with self.assertRaises(RuntimeError):
            curation_no_coord.apply_bulk_entity_merges(
                proj,
                [{"keep_id": "n_vm", "drop_id": "n_tl", "new_name": "Văn Miếu - Thăng Long", "new_kind": "E53_Place"}],
            )

        # Gộp thực thể có coordinator: ép đổi kind của node được giữ khiến e_2 bị hạ về STATUS_CHECK
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            json_repo = JsonProjectRepository(root / "projects")
            sqlite_repo = SQLiteProjectRepository(root / "kg_merge.sqlite3")
            coord = ProjectCommitCoordinator(project_store=json_repo, read_projection=sqlite_repo)
            curation_svc = CurationApplicationService(commit_coordinator=coord)
            merge_res = curation_svc.apply_bulk_entity_merges(
                proj,
                [{"keep_id": "n_vm", "drop_id": "n_tl"}],
                collapse_edges=False,
                note="Gộp thử nghiệm",
                actor="reviewer_1",
            )
            self.assertEqual(merge_res.status, "applied")
            loaded_merged = json_repo.load_project(proj["name"])
            e1 = next(e for e in loaded_merged["edges"] if e["id"] == "e_1")
            self.assertEqual(e1["status"], STATUS_CHECK)
            self.assertTrue(any(h.get("action") == "bulk_entity_merge" for h in loaded_merged.get("curation_history", [])))

        # Gộp loại thực thể: đổi loại node dùng trong cạnh đã duyệt cũng hạ về STATUS_CHECK
        proj2 = _make_sample_project("proj_type_merge")
        cand_proj2, type_res = bulk_apply_entity_type_merges(
            proj2,
            [{"source_kind": "E22_Human-Made_Object", "target_kind": "E53_Place"}],
            actor="reviewer_2",
        )
        self.assertGreaterEqual(type_res.invalidated_approved_count, 1)
        e1_p2 = next(e for e in cand_proj2["edges"] if e["id"] == "e_1")
        self.assertEqual(e1_p2["status"], STATUS_CHECK)
        self.assertTrue(any(h.get("action") == "bulk_entity_type_merge" for h in cand_proj2.get("curation_history", [])))

    def test_cr06_hi03_coordinator_mandatory_and_sqlite_auto_resync(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            json_repo = JsonProjectRepository(root / "projects")
            sqlite_repo = SQLiteProjectRepository(root / "kg_studio_test.sqlite3")
            vec_repo = VectorIndexRepository(root / "vectors")
            coord = ProjectCommitCoordinator(
                project_store=json_repo,
                read_projection=sqlite_repo,
                vector_repo=vec_repo,
            )
            proj_svc = ProjectsApplicationService(
                json_repo,
                read_projection=sqlite_repo,
                vector_repo=vec_repo,
                commit_coordinator=coord,
            )

            proj = _make_sample_project("proj_coord")
            proj["schema_proposals"] = [
                {
                    "id": "prop_1",
                    "kind": "relations",
                    "name": "tọa lạc tại",
                    "definition": "Vị trí của di tích",
                    "status": "pending",
                    "count": 2,
                }
            ]
            json_repo.save_project(proj)

            # Query edges trước khi sync: ProjectsApplicationService + SQLite phải tự resync theo revision authoritative trên JSON
            page = proj_svc.query_edges_page(proj, search="Văn Miếu")
            self.assertEqual(page["total_count"], 2)
            self.assertFalse(page.get("sync_pending"))
            self.assertTrue(any(r.get("source_name") == "Văn Miếu Quốc Tử Giám" for r in page["items"]))

            # Thiếu coordinator -> fail closed
            schema_no_coord = SchemaIntelligenceApplicationService(commit_coordinator=None)
            with self.assertRaises(RuntimeError):
                schema_no_coord.decide_single_proposal(proj, "prop_1", "approve")

            # Có coordinator -> commit qua coordinator
            schema_with_coord = SchemaIntelligenceApplicationService(commit_coordinator=coord)
            dec = schema_with_coord.decide_single_proposal(
                proj,
                "prop_1",
                "merge",
                canonical_name="P53_has_former_or_current_location",
            )
            self.assertIsInstance(dec, dict)
            loaded = json_repo.load_project("Du an Kiem thu P0 P1")
            prop = next(p for p in loaded["schema_proposals"] if p["id"] == "prop_1")
            self.assertEqual(prop["status"], "merged")

    def test_cr07_hi07_hi08_graphrag_neo4j_and_disjoint_qa(self) -> None:
        # 1. Empty approved graph tuyệt đối không fallback sang all
        unapproved_proj = _make_sample_project("proj_no_approved")
        for e in unapproved_proj["edges"]:
            e["status"] = STATUS_PENDING
        idx_empty = get_or_build_graph_index(unapproved_proj, approved_only=True)
        self.assertEqual(len(idx_empty.edges), 0)

        # 2. approved_only=False phải loại cạnh STATUS_REJECTED
        unapproved_proj["edges"][0]["status"] = STATUS_REJECTED
        idx_all = get_or_build_graph_index(unapproved_proj, approved_only=False)
        self.assertNotIn("e_1", idx_all.edges_by_id)

        # 3. CIDOC snake_case tokenization & generic GraphRAG prompt + max_input_tokens truncation
        proj_cidoc = _make_sample_project("proj_cidoc_rag")
        sub = retrieve_subgraph(
            proj_cidoc,
            "P53 has former or current location của Văn Miếu Quốc Tử Giám ở đâu?",
            method="pcst",
            max_edges=6,
        )
        self.assertTrue(any(e["id"] == "e_1" for e in sub.edges))

        class _EchoLLM:
            def __init__(self) -> None:
                self.last_sys = ""
                self.last_user = ""

            def chat_text(self, *, system_prompt: str, user_prompt: str, **kwargs: Any) -> str:
                self.last_sys = system_prompt
                self.last_user = user_prompt
                return "Văn Miếu Quốc Tử Giám tọa lạc tại Thăng Long [e_1]."

        echo = _EchoLLM()
        huge_sub = copy.deepcopy(sub)
        huge_sub.textualized_graph = "\n".join(f"line_{i}: " + ("x" * 120) for i in range(40))
        answer_question_with_graph(huge_sub, max_input_tokens=450, llm_client=echo)
        self.assertNotIn("chuyên sâu về Hà Nội", echo.last_sys)
        self.assertIn("Đã rút gọn ngữ cảnh đồ thị theo giới hạn max_input_tokens", echo.last_user)

        # 4. Neo4j constraint project-scoped uid & 'trang_thai' fix & exportable filter
        self.assertIn("n.uid IS UNIQUE", CONSTRAINT_ENTITY_ID)
        self.assertIn("r.trang_thai = e.trang_thai", MERGE_EDGES)
        self.assertNotIn("r.trang =", MERGE_EDGES)

        captured_params: list[tuple[str, dict[str, Any]]] = []

        class _FakeTx:
            def run(self, cypher: str, **kwargs: Any):
                captured_params.append((cypher.strip(), kwargs))
                return SimpleNamespace(consume=lambda: None)

        class _FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def run(self, cypher: str, **kwargs: Any):
                captured_params.append((cypher.strip(), kwargs))
                return SimpleNamespace(consume=lambda: None)

            def execute_read(self, fn):
                return []

            def execute_write(self, fn):
                return fn(_FakeTx())

        class _FakeDriver:
            def verify_connectivity(self):
                return None

            def session(self, database: str = "neo4j"):
                return _FakeSession()

        proj_neo = copy.deepcopy(proj_cidoc)
        proj_neo["edges"].append(
            {
                "id": "e_bad_ev",
                "source": "n_vm",
                "relation": "tọa lạc tại",
                "target": "n_tl",
                "status": STATUS_APPROVED,
                "evidence": "câu không tồn tại trong văn bản",
                "evidence_found": False,
                "doc_id": "doc_1",
            }
        )
        ga_svc = GraphQAApplicationService(neo4j_gateway=Neo4jGateway())
        res_neo = ga_svc.sync_neo4j(proj_neo, "bolt://localhost:7687", "neo4j", "pw", driver=_FakeDriver())
        self.assertEqual(res_neo["edges_written"], 2)
        merge_calls = [kw for cypher, kw in captured_params if "MERGE (a)-[r:QUAN_HE" in cypher]
        self.assertEqual(len(merge_calls), 1)
        written_edges = merge_calls[0]["edges"]
        self.assertTrue(all(e["trang_thai"] == STATUS_APPROVED for e in written_edges))
        self.assertFalse(any(e["id"] == "e_bad_ev" for e in written_edges))

        # 5. QA Generator: disjoint split = 0 edge leakage + explain_path target consistency
        proj_qa = _make_sample_project("proj_qa_split")
        for idx in range(4, 12):
            nid_a, nid_b = f"na_{idx}", f"nb_{idx}"
            proj_qa["nodes"].extend(
                [
                    {"id": nid_a, "name": f"Di tích Mẫu {idx}", "kind": "E22_Human-Made_Object"},
                    {"id": nid_b, "name": f"Vùng Mẫu {idx}", "kind": "E53_Place"},
                ]
            )
            proj_qa["edges"].append(
                {
                    "id": f"e_{idx}",
                    "source": nid_a,
                    "relation": "tọa lạc tại",
                    "target": nid_b,
                    "status": STATUS_APPROVED,
                    "evidence": f"Di tích Mẫu {idx} tọa lạc tại Vùng Mẫu {idx}.",
                    "override": True,
                    "review_note": "ok",
                    "doc_id": "doc_1",
                    "doc_name": "van_mieu.txt",
                }
            )
        ds = generate_training_qa_dataset(proj_qa, max_samples=40, approved_only=True, disjoint_split=True)
        self.assertEqual(ds["split_metrics"]["train_val_edge_overlap"], 0)
        self.assertEqual(ds["split_metrics"]["train_test_edge_overlap"], 0)
        self.assertEqual(ds["split_metrics"]["val_test_edge_overlap"], 0)
        self.assertGreater(ds["train_count"], 0)
        self.assertGreater(ds["val_count"], 0)
        self.assertGreater(ds["test_count"], 0)
        for s in ds["all_samples"]:
            if s.get("category", "").startswith("Explainable Path"):
                self.assertEqual(s["target_entity_id"], s["bridge_entity_id"])
                self.assertEqual(s["target_entity_name"], s["bridge_entity_name"])

    def test_cr08_hi05_fail_closed_verifier_and_parsing(self) -> None:
        self.assertIsNone(pick_choice_letter("Có thể là A hoặc B đều đúng", ["A", "B"]))
        self.assertEqual(pick_choice_letter("<think>phân tích dài</think>\nĐáp án: B", ["A", "B", "C"]), "B")

        proj = _make_sample_project("proj_align")
        proj["schema_proposals"] = [
            {
                "id": "p_type",
                "kind": "entity_types",
                "name": "E53_Place_Custom",
                "definition": "Địa điểm di tích lịch sử",
                "status": "pending",
            },
            {
                "id": "p_rel",
                "kind": "relations",
                "name": "nằm ở",
                "definition": "Vị trí địa lý của di tích",
                "status": "pending",
            },
        ]
        proj["entity_types"] = [
            {"name": "E53_Place", "description": "Địa điểm", "definition": "Không gian địa lý"},
        ]

        class _BrokenCompletions:
            def create(self, **kwargs: Any) -> Any:
                raise RuntimeError("Ollama timeout")

        broken_client = SimpleNamespace(chat=SimpleNamespace(completions=_BrokenCompletions()))

        with tempfile.TemporaryDirectory() as tmpdir:
            aligner = TargetAligner(vector_repo=VectorIndexRepository(Path(tmpdir)))
            res = aligner.align_project_proposals(
                proj,
                auto_align_threshold=0.99,  # Buộc đi qua tầng verifier
                candidate_threshold=0.05,
                enable_llm_verifier=True,
                llm_params={
                    "provider": "DeepSeek",
                    "api_key": "sk-dummy",
                    "model": "deepseek-chat",
                    "client": broken_client,
                },
            )
            # Verifier lỗi -> fail-closed: giữ pending, không tự map sai
            self.assertEqual(res["auto_aligned"], 0)
            self.assertGreaterEqual(res["error_count"], 1)

    def test_hi01_hi02_parallel_error_redaction_and_non_e5_prompt_formatting(self) -> None:
        self.assertFalse(should_use_e5_instruct("ollama:bge-m3"))
        self.assertTrue(should_use_e5_instruct("intfloat/multilingual-e5-large"))
        self.assertNotIn("Instruct:", format_sr_query("vị trí", use_instruct=should_use_e5_instruct("ollama:bge-m3")))
        self.assertIn("Instruct:", format_sr_query("vị trí", use_instruct=should_use_e5_instruct("e5-large")))
        passage_v2 = format_catalog_passage("P53", "d", domain="E18", range="E53")
        self.assertIn("Scope: E18 -> E53", passage_v2)
        self.assertEqual(PASSAGE_TEMPLATE_VERSION, "v2-domain-range")

        class _FailingEngine(BaseExtractionEngine):
            mode_id = MODE_EDC_PLUS_R
            label = "Failing EDC+R"

            def process_chunk(self, ctx: ChunkContext) -> EngineOutput:
                exc = RuntimeError(f"Lỗi kết nối secret={ctx.api_key}")
                exc.input_tokens = 123  # type: ignore[attr-defined]
                exc.output_tokens = 45  # type: ignore[attr-defined]
                raise exc

        reg = EngineRegistry()
        reg.register(_FailingEngine())
        svc = ExtractionApplicationService(engine_registry=reg)
        proj = _make_sample_project("proj_fail_chunk")
        proj["extraction_mode"] = MODE_EDC_PLUS_R
        proj["edc_plus_r_settings"] = EDCPlusRSettingsDTO().to_dict()
        doc = proj["documents"][0]
        rec = {"chunk_number": 1, "text": doc["text"], "chunk_hash": "hash1"}

        with self.assertRaises(RuntimeError):
            svc.extract_chunk(
                proj,
                doc,
                rec,
                provider="DeepSeek",
                api_key="sk-super-secret-value-9999",
                model="deepseek-chat",
            )
        self.assertEqual(len(proj["runs"]), 1)
        err_run = proj["runs"][0]
        self.assertEqual(err_run["status"], "error")
        self.assertEqual(err_run["input_tokens"], 123)
        self.assertEqual(err_run["output_tokens"], 45)
        self.assertNotIn("sk-super-secret-value-9999", err_run["error"])
        self.assertNotIn("sk-super-secret-value-9999", json.dumps(err_run))
        self.assertFalse(proj.get("processed_chunks"))

    def test_cr02_cr03_cr04_cr05_hi04_facade_training_and_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            json_repo = JsonProjectRepository(root / "projects")
            sqlite_repo = SQLiteProjectRepository(root / "kg.sqlite3")
            vec_repo = VectorIndexRepository(root / "vectors")
            facade = KGStudioFacade(
                json_repo=json_repo,
                sqlite_repo=sqlite_repo,
                vector_repo=vec_repo,
            )

            proj = _make_sample_project("proj_facade_v1")
            proj["nodes"].extend(
                [
                    {"id": "n_dup_a", "name": "Chùa Một Cột A", "kind": "E22_Human-Made_Object", "aliases": []},
                    {"id": "n_dup_b", "name": "Chùa Một Cột B", "kind": "E22_Human-Made_Object", "aliases": []},
                    {"id": "n_dup_c", "name": "Đền Ngọc Sơn C", "kind": "E22_Human-Made_Object", "aliases": []},
                    {"id": "n_dup_d", "name": "Đền Ngọc Sơn D", "kind": "E22_Human-Made_Object", "aliases": []},
                ]
            )
            proj["edges"].append(
                {
                    "id": "e_1_dup",
                    "source": "n_vm",
                    "relation": "P53_has_former_or_current_location",
                    "target": "n_tl",
                    "status": STATUS_APPROVED,
                    "evidence": "Văn Miếu Quốc Tử Giám được xây dựng vào năm 1070 tại Thăng Long",
                    "evidence_found": True,
                    "doc_id": "doc_1",
                    "doc_name": "van_mieu.txt",
                    "chunk_number": 1,
                }
            )
            facade.save_project(proj)

            # CR-02: Prompt wrappers + schema wrappers qua Facade/ApplicationService
            v1, ch1 = facade.save_prompt_version(proj, "edc", "Prompt V1 test", note="v1")
            v2, ch2 = facade.save_prompt_version(proj, "edc", "Prompt V2 test", note="v2")
            self.assertTrue(ch1 and ch2)
            self.assertEqual(facade.get_prompt_version(proj, v1["id"])["id"], v1["id"])
            diff_txt = facade.diff_prompt_versions(v1["content"], v2["content"])
            self.assertIn("-Prompt V1 test", diff_txt)
            self.assertIn("+Prompt V2 test", diff_txt)
            restored_v, ch_res = facade.restore_prompt_version(proj, v1["id"], note="rollback v1")
            self.assertTrue(ch_res)
            self.assertEqual(restored_v["content"], "Prompt V1 test")

            pid_prop, _ = facade.schema_service.propose_term(
                proj,
                "relations",
                "dựng tại",
                "Định nghĩa test",
                source_chunk_id="c_1",
                doc_id="doc_1",
            )
            self.assertTrue(pid_prop)
            clean_box: dict[str, Any] = {
                "thuc_the": [{"ten": "Tháp Rùa", "loai": "E22_Human-Made_Object"}],
                "quan_he": [],
            }
            facade.schema_service.prepare_edc(
                proj,
                clean_box,
                {"dinh_nghia_loai": [], "dinh_nghia_quan_he": []},
                {"chunk_id": "c_1", "doc_id": "doc_1"},
            )
            self.assertEqual(clean_box["thuc_the"][0]["loai"], "E22_Human-Made_Object")

            # CR-03: Hai lần apply_bulk_entity_merges khác cặp qua Facade không replay kết quả cũ
            res_m1 = facade.apply_bulk_entity_merges(
                proj,
                [{"keep_id": "n_dup_a", "drop_id": "n_dup_b"}],
                note="batch 1",
            )
            self.assertEqual(res_m1.status, "applied")
            res_m2 = facade.apply_bulk_entity_merges(
                proj,
                [{"keep_id": "n_dup_c", "drop_id": "n_dup_d"}],
                note="batch 2",
            )
            self.assertEqual(res_m2.status, "applied")
            self.assertNotEqual(res_m1.request_id, res_m2.request_id)

            # CR-04: compute_apparent_duplicate_edge_groups qua Facade nhận edges đúng
            dup_groups = facade.compute_apparent_duplicate_edge_groups(proj)
            self.assertEqual(len(dup_groups), 1)
            self.assertEqual(dup_groups[0]["count"], 2)

            # CR-05: TrainingApplicationService.build_sft_instructions không còn AttributeError
            train_svc = TrainingApplicationService(export_dir=root / "exports")
            sft_recs = train_svc.build_sft_instructions(proj)
            self.assertIsInstance(sft_recs, list)
            self.assertGreaterEqual(len(sft_recs), 1)

            # HI-04: Path traversal bị chặn trong restore_snapshot + SQLite xử lý UNIQUE(name) khi đổi project_id
            outside_file = root / "outside.json"
            outside_file.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                json_repo.restore_snapshot(proj, outside_file)

            recreated = _make_sample_project("proj_facade_v2_recreated")
            recreated["name"] = proj["name"]
            sqlite_repo.sync_from_project_dict(recreated)
            summ = sqlite_repo.get_project_summary("proj_facade_v2_recreated")
            self.assertEqual(summ.project_id, "proj_facade_v2_recreated")


if __name__ == "__main__":
    unittest.main()
