"""Kiểm thử xuất Bộ dữ liệu Huấn luyện Chuẩn G-Retriever 5 tệp (nodes/edges/evidence/questions/schema_contract)."""
from __future__ import annotations

import csv
import io
import json
import logging
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from streamlit.testing.v1 import AppTest

from backend.bootstrap import AppContainer, reset_container
from backend.domain.graph.kgqa_bundle import (
    EDGES_CSV_HEADERS,
    EVIDENCE_CSV_HEADERS,
    NODES_CSV_HEADERS,
    QUESTIONS_CSV_HEADERS,
    build_kgqa_training_bundle,
    normalize_ascii_snake_key,
)
from backend.facade import KGStudioFacade, reset_facade
from backend.repositories.json_repo import JsonProjectRepository, empty_project
from backend.repositories.sqlite_repo import SQLiteProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
import frontend.client as frontend_client
import frontend.composition as frontend_composition
from frontend.composition import FrontendComposition
from shared.constants import MODE_EDC_PLUS_R, STATUS_APPROVED


def _read_csv_bom(raw_bytes: bytes) -> tuple[list[str], list[dict[str, str]]]:
    assert raw_bytes.startswith(b"\xef\xbb\xbf"), "CSV xuất ra phải có UTF-8 BOM"
    text = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader.fieldnames or []), list(reader)


def _build_rich_history_project() -> dict:
    doc1_text = (
        "Chùa Một Cột tọa lạc tại Ba Đình và khởi dựng dưới triều Lý Thái Tông. "
        "Chùa Trấn Quốc tọa lạc tại Ba Đình. "
        "Lý Thái Tông thuộc triều đại Nhà Lý. "
        "Chùa Một Cột thờ Phật Quan Âm và thờ Vua Hùng. "
        "Đền Ngọc Sơn tọa lạc tại Hoàn Kiếm."
    )
    proj = empty_project("Hà Nội Di Sản")
    proj["project_id"] = "proj_kgqa_hn"
    proj["extraction_mode"] = MODE_EDC_PLUS_R
    proj["entity_types"] = [
        {"name": "E22_HUMAN_MADE_OBJECT", "description": "Di tích lịch sử", "definition": "Công trình văn hóa di tích"},
        {"name": "E21_PERSON", "description": "Nhân vật lịch sử", "definition": "Con người lịch sử"},
        {"name": "E53_PLACE", "description": "Địa danh", "definition": "Không gian địa lý"},
        {"name": "E74_GROUP", "description": "Triều đại / Tổ chức", "definition": "Tổ chức xã hội, triều đại"},
    ]
    proj["relations"] = ["tọa lạc tại", "khởi dựng dưới triều", "thuộc triều đại", "thờ"]
    proj["relation_notes"] = {
        "tọa lạc tại": {"description": "Vị trí địa lý", "definition": "Công trình đặt tại địa bàn nào"},
        "thờ": {"description": "Thờ phụng", "definition": "Nhân vật được thờ tự tại di tích"},
    }
    proj["documents"] = [
        {
            "id": "doc_hn_1",
            "name": "ha_noi_di_tich.txt",
            "text": doc1_text,
            "chars": len(doc1_text),
            "source_label": "wikipedia_infobox",
        },
        {
            "id": "doc_hn_2",
            "name": "thang_long_ky.txt",
            "text": "Diên Hựu tọa lạc tại quận Ba Đình.",
            "chars": 34,
            "source_label": "",
        },
    ]
    proj["domain_gazetteer"] = {
        "liên hoa đài": {
            "alias": "Liên Hoa Đài",
            "canonical_name": "Chùa Một Cột",
            "kind": "E22_HUMAN_MADE_OBJECT",
            "source": "manual_editor",
        },
        "quốc tử giám khổng": {
            "alias": "Bí danh nhầm loại",
            "canonical_name": "Chùa Một Cột",
            "kind": "E21_PERSON",  # Khác kind: phải giữ ranh giới đồng âm, không gộp vào E22_HUMAN_MADE_OBJECT
            "source": "manual_editor",
        },
    }
    proj["nodes"] = [
        {"id": "n_cmc", "name": "Chùa Một Cột", "kind": "E22_HUMAN_MADE_OBJECT", "aliases": ["Chùa Diên Hựu"]},
        {"id": "n_ctq", "name": "Chùa Trấn Quốc", "kind": "E22_HUMAN_MADE_OBJECT", "aliases": ["Chùa Khai Quốc"]},
        {"id": "n_dns", "name": "Đền Ngọc Sơn", "kind": "E22_HUMAN_MADE_OBJECT", "aliases": []},
        {"id": "n_bd", "name": "Ba Đình", "kind": "E53_PLACE", "aliases": ["Quận Ba Đình"]},
        {"id": "n_hk", "name": "Hoàn Kiếm", "kind": "E53_PLACE", "aliases": []},
        {"id": "n_ltt", "name": "Lý Thái Tông", "kind": "E21_PERSON", "aliases": []},
        {"id": "n_nl", "name": "Nhà Lý", "kind": "E74_GROUP", "aliases": ["Triều Lý"]},
        {"id": "n_pqa", "name": "Phật Quan Âm", "kind": "E21_PERSON", "aliases": []},
        {"id": "n_vh", "name": "Vua Hùng", "kind": "E21_PERSON", "aliases": []},
    ]
    proj["edges"] = [
        {
            "id": "e1",
            "source": "n_cmc",
            "target": "n_bd",
            "relation": "tọa lạc tại",
            "evidence": "Chùa Một Cột tọa lạc tại Ba Đình và khởi dựng dưới triều Lý Thái Tông.",
            "evidences": [
                {
                    "edge_id": "e1",
                    "doc_id": "doc_hn_1",
                    "doc_name": "ha_noi_di_tich.txt",
                    "chunk_number": 1,
                    "chunk_hash": "11112222333344445555",
                    "evidence": "Chùa Một Cột tọa lạc tại Ba Đình.",
                },
                {
                    "edge_id": "e1_dup",
                    "doc_id": "doc_hn_2",
                    "doc_name": "thang_long_ky.txt",
                    "chunk_number": 1,
                    "chunk_hash": "99998888777766665555",
                    "evidence": "Diên Hựu tọa lạc tại quận Ba Đình.",
                    "extraction_mode": "chunk_extraction",
                },
            ],
            "doc_id": "doc_hn_1",
            "doc_name": "ha_noi_di_tich.txt",
            "status": STATUS_APPROVED,
            "override": True,
            "review_note": "ok",
        },
        {
            "id": "e2",
            "source": "n_ctq",
            "target": "n_bd",
            "relation": "tọa lạc tại",
            "evidence": "Chùa Trấn Quốc tọa lạc tại Ba Đình.",
            "doc_id": "doc_hn_1",
            "doc_name": "ha_noi_di_tich.txt",
            "chunk_hash": "11112222333344445555",
            "status": STATUS_APPROVED,
            "override": True,
            "review_note": "ok",
        },
        {
            "id": "e3",
            "source": "n_cmc",
            "target": "n_ltt",
            "relation": "khởi dựng dưới triều",
            "evidence": "Chùa Một Cột tọa lạc tại Ba Đình và khởi dựng dưới triều Lý Thái Tông.",
            "doc_id": "doc_hn_1",
            "doc_name": "ha_noi_di_tich.txt",
            "chunk_hash": "aaaa1111bbbb2222",
            "status": STATUS_APPROVED,
            "override": True,
            "review_note": "ok",
        },
        {
            "id": "e4",
            "source": "n_ltt",
            "target": "n_nl",
            "relation": "thuộc triều đại",
            "evidence": "Lý Thái Tông thuộc triều đại Nhà Lý.",
            "doc_id": "doc_hn_1",
            "doc_name": "ha_noi_di_tich.txt",
            "chunk_hash": "cccc3333dddd4444",
            "status": STATUS_APPROVED,
            "override": True,
            "review_note": "ok",
        },
        {
            "id": "e5",
            "source": "n_cmc",
            "target": "n_pqa",
            "relation": "thờ",
            "evidence": "Chùa Một Cột thờ Phật Quan Âm và thờ Vua Hùng.",
            "doc_id": "doc_hn_1",
            "doc_name": "ha_noi_di_tich.txt",
            "chunk_hash": "11112222333344445555",
            "status": STATUS_APPROVED,
            "override": True,
            "review_note": "ok",
        },
        {
            "id": "e6",
            "source": "n_cmc",
            "target": "n_vh",
            "relation": "thờ",
            "evidence": "Chùa Một Cột thờ Phật Quan Âm và thờ Vua Hùng.",
            "doc_id": "doc_hn_1",
            "doc_name": "ha_noi_di_tich.txt",
            "chunk_hash": "11112222333344445555",
            "status": STATUS_APPROVED,
            "override": True,
            "review_note": "ok",
        },
        {
            "id": "e7",
            "source": "n_dns",
            "target": "n_hk",
            "relation": "tọa lạc tại",
            "evidence": "Đền Ngọc Sơn tọa lạc tại Hoàn Kiếm.",
            "doc_id": "doc_hn_1",
            "doc_name": "ha_noi_di_tich.txt",
            "chunk_hash": "eeee5555ffff6666",
            "status": STATUS_APPROVED,
            "override": True,
            "review_note": "ok",
        },
    ]
    return proj


class KGQABundleExportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tmp.name)
        self.json_repo = JsonProjectRepository(self.temp_path / "projects")
        self.sqlite_repo = SQLiteProjectRepository(self.temp_path / "test.db")
        self.vector_repo = VectorIndexRepository(index_root=self.temp_path / "vectors")
        self.container = AppContainer(
            json_repo=self.json_repo,
            sqlite_repo=self.sqlite_repo,
            vector_repo=self.vector_repo,
        )
        self.facade = KGStudioFacade(
            json_repo=self.json_repo,
            sqlite_repo=self.sqlite_repo,
            vector_repo=self.vector_repo,
        )
        self.comp = FrontendComposition(container=self.container, facade=self.facade)
        self._prev_container = reset_container(self.container)
        self._prev_facade = reset_facade(self.facade)
        self._prev_comp = frontend_composition._COMPOSITION
        frontend_composition._COMPOSITION = self.comp
        self._prev_client = frontend_client.reset_client(None)
        self._env_patcher = patch.dict(
            os.environ,
            {
                "KG_STUDIO_PROJECTS_DIR": str(self.temp_path / "projects"),
                "KG_STUDIO_SECRETS_FILE": str(self.temp_path / ".secrets.toml"),
            },
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()
        frontend_client.reset_client(self._prev_client)
        frontend_composition._COMPOSITION = self._prev_comp
        reset_facade(self._prev_facade)
        reset_container(self._prev_container)
        self.tmp.cleanup()

    def test_ascii_snake_key_vietnamese_d(self) -> None:
        self.assertEqual(normalize_ascii_snake_key("Ba Đình"), "ba_dinh")
        self.assertEqual(normalize_ascii_snake_key("Đền Ngọc Sơn"), "den_ngoc_son")
        self.assertEqual(normalize_ascii_snake_key("Chùa Một Cột"), "chua_mot_cot")

    def test_5_file_bundle_schema_homonym_aliases_and_referential_integrity(self) -> None:
        proj = _build_rich_history_project()
        bundle = build_kgqa_training_bundle(proj, approved_only=True, max_samples=100)

        # Kiểm tra đúng 5 tệp trong ZIP
        with zipfile.ZipFile(io.BytesIO(bundle["zip_bytes"]), "r") as zf:
            self.assertEqual(
                set(zf.namelist()),
                {"nodes.csv", "edges.csv", "evidence.csv", "questions.csv", "schema_contract.json"},
            )
            nodes_hdr, nodes_rows = _read_csv_bom(zf.read("nodes.csv"))
            edges_hdr, edges_rows = _read_csv_bom(zf.read("edges.csv"))
            ev_hdr, ev_rows = _read_csv_bom(zf.read("evidence.csv"))
            q_hdr, q_rows = _read_csv_bom(zf.read("questions.csv"))
            contract = json.loads(zf.read("schema_contract.json").decode("utf-8"))

        self.assertEqual(nodes_hdr, NODES_CSV_HEADERS)
        self.assertEqual(edges_hdr, EDGES_CSV_HEADERS)
        self.assertEqual(ev_hdr, EVIDENCE_CSV_HEADERS)
        self.assertEqual(q_hdr, QUESTIONS_CSV_HEADERS)

        # Kiểm tra nodes.csv: bảo toàn nguyên loại thực thể dự án & ranh giới alias đồng âm
        nodes_by_id = {r["node_id"]: r for r in nodes_rows}
        cmc_row = next(r for r in nodes_rows if r["canonical_name"] == "Chùa Một Cột")
        self.assertEqual(cmc_row["type"], "E22_HUMAN_MADE_OBJECT")
        self.assertEqual(cmc_row["normalized_key"], "chua_mot_cot")
        self.assertIn("Chùa Diên Hựu", cmc_row["aliases"])
        self.assertIn("Liên Hoa Đài", cmc_row["aliases"])
        self.assertNotIn("Bí danh nhầm loại", cmc_row["aliases"])

        # Kiểm tra schema_contract.json: giữ nguyên entity_types và relations của project
        self.assertIn("E22_HUMAN_MADE_OBJECT", contract["node_types"])
        self.assertEqual(contract["node_types"]["E22_HUMAN_MADE_OBJECT"]["type"], "E22_HUMAN_MADE_OBJECT")
        self.assertIn("tọa lạc tại", contract["relation_types"])
        self.assertEqual(contract["relation_types"]["tọa lạc tại"]["template"], "{head} tọa lạc tại {tail}")

        # Kiểm tra tổng hợp nhiều bằng chứng trên 1 cạnh
        ev_by_id = {r["evidence_id"]: r for r in ev_rows}
        e_cmc_bd = next(
            r for r in edges_rows if r["source_name"] == "Chùa Một Cột" and r["target_name"] == "Ba Đình"
        )
        e_ev_ids = [x for x in e_cmc_bd["evidence_ids"].split("|") if x]
        self.assertEqual(len(e_ev_ids), 2)
        self.assertIn("wikipedia_infobox", e_cmc_bd["sources"])
        self.assertIn("chunk_extraction", e_cmc_bd["sources"])
        self.assertTrue(all(ev_id in ev_by_id for ev_id in e_ev_ids))
        self.assertTrue(any(r["chunk_uid"].startswith("CHK_") for r in ev_rows))

        # Kiểm tra đủ các topology G-Retriever: single_hop, multi_hop (fwd+fwd & rev+fwd), list
        edges_by_id = {r["edge_id"]: r for r in edges_rows}
        q_types = {r["question_type"] for r in q_rows}
        self.assertEqual(q_types, {"single_hop", "multi_hop", "list"})
        dirs_seen = {tuple(json.loads(r["traversal_directions"])) for r in q_rows}
        self.assertIn(("forward",), dirs_seen)
        self.assertIn(("reverse",), dirs_seen)
        self.assertIn(("forward", "forward"), dirs_seen)
        self.assertIn(("reverse", "forward"), dirs_seen)

        # Kiểm tra tính toàn vẹn tham chiếu 100% giữa 5 tệp & review_status trung thực
        for qr in q_rows:
            self.assertEqual(qr["review_status"], "auto_generated")
            answers = json.loads(qr["answers"])
            ans_ids = json.loads(qr["answer_entity_ids"])
            topic_ids = json.loads(qr["topic_entity_ids"])
            gold_eids = json.loads(qr["gold_edge_ids"])
            gold_paths = json.loads(qr["gold_paths"])
            ev_edges = json.loads(qr["evidence_edges"])
            ev_list = json.loads(qr["evidence"])

            self.assertEqual(qr["answer_text"], "; ".join(answers))
            self.assertEqual(len(answers), len(ans_ids))
            self.assertTrue(all(nid in nodes_by_id for nid in topic_ids))
            self.assertTrue(all(nid in nodes_by_id for nid in ans_ids))
            self.assertTrue(all(eid in edges_by_id for eid in gold_eids))
            self.assertTrue(all(eid in edges_by_id for path in gold_paths for eid in path))
            self.assertTrue(all(ee["edge_id"] in edges_by_id for ee in ev_edges))
            self.assertTrue(all(ev["evidence_id"] in ev_by_id for ev in ev_list))

            if qr["question_type"] == "list":
                self.assertGreaterEqual(len(answers), 2)
                self.assertGreaterEqual(len(gold_paths), 2)

        for n in nodes_rows:
            self.assertIn(n["type"], contract["node_types"])
        for e in edges_rows:
            self.assertIn(e["relation"], contract["relation_types"])

    def test_llm_paraphrase_pipeline_entity_guard_and_anti_leak(self) -> None:
        proj = _build_rich_history_project()
        client = frontend_client.get_client()
        bundle = client.build_kgqa_training_bundle(proj, approved_only=True, max_samples=10)
        records = bundle["question_records"]
        self.assertGreaterEqual(len(records), 4)

        # Mock LLM trả về 4 trường hợp:
        # 1. Hợp lệ, giữ đủ thực thể hạt giống & tự nhiên
        # 2. Lỗi làm rơi thực thể hạt giống -> phải bị chặn
        # 3. Lỗi tự làm lộ đáp án vào câu hỏi -> phải bị chặn
        # 4. LLM trả nhầm dạng dict -> phải bóc sạch lấy trường question
        def _build_mock_client():
            class _FakeCompletions:
                def create(self, **kwargs):
                    user_msg = kwargs["messages"][1]["content"]
                    lines = [ln for ln in user_msg.splitlines() if ln.strip() and ln.strip()[0].isdigit()]
                    n_batch = len(lines)
                    outputs = []
                    for i in range(n_batch):
                        rec = records[i]
                        topic = rec["topic_names"][0]
                        ans = rec["answers"][0]
                        if i == 0:
                            outputs.append(f"Bạn có biết {topic} gắn với thông tin nào trong sử liệu không?")
                        elif i == 1:
                            outputs.append("Ngôi chùa cổ này nằm ở quận nào vậy?")  # Rơi tên thực thể!
                        elif i == 2:
                            outputs.append(f"Có phải {topic} liên quan đến {ans} không?")  # Lộ đáp án!
                        elif i == 3:
                            outputs.append({"id": rec["question_id"], "question": f"Cho hỏi về {topic}, câu này viết lại tự nhiên ra sao?"})
                        else:
                            outputs.append(rec["question"])  # Không đổi
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(content=json.dumps(outputs, ensure_ascii=False))
                            )
                        ]
                    )

            return SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))

        updated, pstats = client.paraphrase_kgqa_training_bundle(
            bundle,
            client=_build_mock_client(),
            batch_size=20,
        )
        self.assertEqual(pstats["accepted"], 2)
        self.assertEqual(pstats["rejected_entity_drop"], 1)
        self.assertEqual(pstats["rejected_answer_leak"], 1)
        self.assertEqual(updated["stats"]["llm_paraphrased_count"], 2)

        upd_records = updated["question_records"]
        self.assertEqual(upd_records[0]["review_status"], "llm_paraphrased")
        self.assertEqual(upd_records[1]["review_status"], "auto_generated")
        self.assertEqual(upd_records[2]["review_status"], "auto_generated")
        self.assertEqual(upd_records[3]["review_status"], "llm_paraphrased")
        self.assertFalse(upd_records[3]["question"].startswith("{"))

        # Kiểm tra bytes ZIP & questions.csv được cập nhật đồng bộ
        with zipfile.ZipFile(io.BytesIO(updated["zip_bytes"]), "r") as zf:
            _, q_rows = _read_csv_bom(zf.read("questions.csv"))
        self.assertEqual(q_rows[0]["review_status"], "llm_paraphrased")
        self.assertEqual(q_rows[1]["review_status"], "auto_generated")

    def test_p05_ui_gretriever_5file_section_no_state_warnings(self) -> None:
        proj = _build_rich_history_project()
        self.json_repo.save_project(proj)

        script = """
from backend.facade import get_facade
from frontend.pages.p05_graph_export import render_graph_export_page

proj = get_facade().load_project("Hà Nội Di Sản")
render_graph_export_page(proj)
"""
        recorded_warnings: list[str] = []

        class _WarnRecorder(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                recorded_warnings.append(self.format(record))

        lg = logging.getLogger("streamlit")
        prev_level = lg.level
        lg.setLevel(logging.WARNING)
        rec_handler = _WarnRecorder(level=logging.WARNING)
        lg.addHandler(rec_handler)
        try:
            at = AppTest.from_string(script, default_timeout=15)
            at.run()
            self.assertFalse(at.exception)

            # Tab 4 (bản cũ) và Tab 5 (5 tệp mới) tách biệt độc lập
            self.assertTrue(
                any(b.key == "_p06_btn_gen_natural_qa_proj_kgqa_hn" for b in at.button),
                "Tab 4 bản cũ vẫn phải độc lập không bị xóa.",
            )
            self.assertTrue(
                any(b.key == "p05_gret_studio_proj_kgqa_hn_btn_build" for b in at.button),
                "Tab 5 mới phải có nút tạo Bộ 5 tệp chuẩn G-Retriever riêng.",
            )

            at.button(key="p05_gret_studio_proj_kgqa_hn_btn_build").click().run()
            self.assertFalse(at.exception)
            gret_dl_buttons = [
                btn for btn in at.download_button if str(btn.key).startswith("p05_gret_studio_proj_kgqa_hn_")
            ]
            self.assertEqual(
                [b.key for b in gret_dl_buttons],
                ["p05_gret_studio_proj_kgqa_hn_dl_zip"],
                "Tab 5 chỉ xuất hiện duy nhất 1 nút tải gói ZIP 5 tệp.",
            )
        finally:
            lg.removeHandler(rec_handler)
            lg.setLevel(prev_level)

        bad_warnings = [
            m for m in recorded_warnings
            if "Session State API" in m or "created with a default value" in m
        ]
        self.assertEqual(bad_warnings, [], f"Phát hiện cảnh báo widget Session State: {bad_warnings}")

    def test_empty_graph_and_snapshot_unapproved_mode(self) -> None:
        empty_proj = empty_project("Trống")
        empty_bundle = build_kgqa_training_bundle(empty_proj, approved_only=True, max_samples=20)
        self.assertEqual(empty_bundle["stats"]["nodes_count"], 0)
        self.assertEqual(empty_bundle["stats"]["edges_count"], 0)
        self.assertEqual(empty_bundle["stats"]["questions_count"], 0)
        with zipfile.ZipFile(io.BytesIO(empty_bundle["zip_bytes"]), "r") as zf:
            self.assertEqual(
                set(zf.namelist()),
                {"nodes.csv", "edges.csv", "evidence.csv", "questions.csv", "schema_contract.json"},
            )

        # Snapshot/baseline chưa duyệt (approved_only=False) phải giữ confidence=0.7 trung thực
        raw_proj = empty_project("Baseline B")
        raw_proj["nodes"] = [
            {"id": "n1", "name": "Hồ Hoàn Kiếm", "kind": "E53_PLACE"},
            {"id": "n2", "name": "Hà Nội", "kind": "E53_PLACE"},
        ]
        raw_proj["edges"] = [
            {
                "id": "e1",
                "source": "n1",
                "target": "n2",
                "relation": "nằm tại",
                "evidence": "Hồ Hoàn Kiếm nằm tại Hà Nội.",
                "doc_name": "ho.txt",
            }
        ]
        raw_bundle = build_kgqa_training_bundle(raw_proj, approved_only=False, max_samples=20)
        self.assertEqual(raw_bundle["stats"]["nodes_count"], 2)
        self.assertEqual(raw_bundle["stats"]["edges_count"], 1)
        self.assertEqual(raw_bundle["edges"][0]["confidence"], 0.7)
        self.assertGreaterEqual(raw_bundle["stats"]["questions_count"], 1)

    def test_p05_ui_paraphrase_without_api_key_shows_warning_not_crash(self) -> None:
        proj = _build_rich_history_project()
        self.json_repo.save_project(proj)

        script = """
import streamlit as st
from backend.facade import get_facade
from frontend.pages.p05_graph_export import render_graph_export_page

st.session_state["llm_provider"] = "DeepSeek"
st.session_state["llm_model"] = "deepseek-chat"
st.session_state["llm_api_key"] = ""
proj = get_facade().load_project("Hà Nội Di Sản")
render_graph_export_page(proj)
"""
        with patch("frontend.state.llm_state.get_api_key", return_value=""):
            at = AppTest.from_string(script, default_timeout=15)
            at.run()
            at.checkbox(key="p05_gret_studio_proj_kgqa_hn_use_paraphrase").set_value(True).run()
            at.button(key="p05_gret_studio_proj_kgqa_hn_btn_build").click().run()
        self.assertFalse(at.exception)
        self.assertTrue(
            any("Chưa cấu hình nhà cung cấp LLM" in str(w.value) for w in at.warning),
            "Phải cảnh báo rõ khi chưa có API key cho bước Paraphrase.",
        )
        self.assertTrue(
            any(btn.key == "p05_gret_studio_proj_kgqa_hn_dl_zip" for btn in at.download_button),
            "Vẫn phải cho tải gói 5 tệp chuẩn sinh tự động khi thiếu API key paraphrase.",
        )


if __name__ == "__main__":
    unittest.main()
