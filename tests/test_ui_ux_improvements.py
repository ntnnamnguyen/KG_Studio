"""Kiểm thử hồi quy UI/UX & AppTest cho kế hoạch cải tiến 8 đợt (U1–U7)."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from shared.constants import MODE_EDC_PLUS_R, MODE_FIXED, MODE_FREE_TRIPLES, STATUS_APPROVED, STATUS_PENDING


def _sample_project(mode: str = MODE_FIXED) -> dict:
    return {
        "project_id": "proj_ux_test",
        "name": "DuAnUXTest",
        "extraction_mode": mode,
        "revision": "rev1",
        "documents": [
            {
                "id": "doc_1",
                "name": "di_tich.txt",
                "text": "Chùa Một Cột nằm tại Hà Nội và được xây dựng năm 1049.",
                "source_label": "Sách lịch sử",
                "place_scope": "Hà Nội",
                "created_at": "2026-11-12T10:00:00",
                "pages": [],
                "diagnostics": {"warnings": ["Cảnh báo OCR nhẹ"]},
            }
        ],
        "entity_types": ["Di tích"],
        "entity_type_notes": {"Di tích": {"description": "Công trình lịch sử", "aliases": []}},
        "relations": ["tọa lạc tại"],
        "relation_notes": {"tọa lạc tại": {"description": "Vị trí địa lý", "aliases": []}},
        "domain_gazetteer": {"chùa một cột": "Chùa Một Cột"},
        "schema_proposals": [
            {
                "id": "prop_1",
                "kind": "entity_types",
                "name": "Kiến trúc",
                "canonical_name": "Kiến trúc",
                "status": "pending",
                "definition": "Loại công trình",
                "doc_ids": ["doc_1"],
            }
        ],
        "nodes": [
            {"id": "n1", "name": "Chùa Một Cột", "kind": "Di tích", "aliases": ["Diên Hựu Tự"], "documents": ["doc_1"]},
            {"id": "n2", "name": "Hà Nội", "kind": "Di tích", "aliases": [], "documents": ["doc_1"]},
        ],
        "edges": [
            {
                "id": "e1",
                "source": "n1",
                "relation": "tọa lạc tại",
                "target": "n2",
                "evidence": "Chùa Một Cột nằm tại Hà Nội",
                "doc_id": "doc_1",
                "doc_name": "di_tich.txt",
                "chunk_number": 1,
                "status": STATUS_PENDING,
            },
            {
                "id": "e2",
                "source": "n2",
                "relation": "tọa lạc tại",
                "target": "n1",
                "evidence": "được xây dựng năm 1049",
                "doc_id": "doc_1",
                "doc_name": "di_tich.txt",
                "chunk_number": 1,
                "status": STATUS_APPROVED,
            },
        ],
        "runs": [
            {
                "run_id": "run_ux_1",
                "doc_id": "doc_1",
                "doc_name": "di_tich.txt",
                "chunk_number": 1,
                "status": "ok",
                "extraction_mode": mode,
                "provider": "DeepSeek",
                "model": "deepseek-chat",
                "prompt_version_id": "pv_1",
                "prompt_content_hash": "abcdef1234567890",
                "prepared_request_hash": "123456abcdef7890",
                "prepared_request": {
                    "system_prompt": "System test prompt",
                    "user_message": "User test prompt",
                },
                "step_traces": [
                    {
                        "loop_index": 1,
                        "step_name": "Extract",
                        "duration_ms": 12,
                        "summary": "OK",
                        "details": {"triples": 1},
                    }
                ],
                "input_tokens": 120,
                "output_tokens": 45,
                "ingest_stats": {"added_nodes": 2, "added_edges": 1},
                "raw_response": '{"triples": []}',
            }
        ],
        "prompts": {},
        "schema_decision_batches": [],
        "curation_decision_batches": [],
        "entity_merges": [],
        "node_redirects": {},
    }


def _app_script_for_step(step: str) -> str:
    return f"""
import streamlit as st
from frontend.pages.p01_projects_docs import render_projects_docs_page
from frontend.pages.p02_catalogs_prompts import render_catalogs_prompts_page
from frontend.pages.p03_extraction import render_extraction_page
from frontend.pages.p04_curation_hub import render_curation_hub_page
from frontend.pages.p05_graph_export import render_graph_export_page
from frontend.state.session import ensure_session_state

proj = st.session_state["_test_project"]
st.session_state["project"] = proj
st.session_state["active_project_name"] = proj["name"]
st.session_state["_loaded_name"] = proj["name"]
ensure_session_state()

step = "{step}"
if step == "documents":
    render_projects_docs_page(proj)
elif step == "setup":
    render_catalogs_prompts_page(proj)
elif step == "extraction":
    render_extraction_page(proj)
elif step == "review":
    render_curation_hub_page(proj)
elif step == "explore":
    render_graph_export_page(proj)
"""


class TestUIUXImprovements(unittest.TestCase):
    def test_u1_theme_config_and_pipeline_banner_hierarchy(self) -> None:
        cfg_text = Path(".streamlit/config.toml").read_text(encoding="utf-8")
        self.assertIn("[theme]", cfg_text)
        self.assertIn('base = "light"', cfg_text)
        self.assertIn('primaryColor = "#1D4ED8"', cfg_text)
        self.assertIn("showSidebarNavigation = false", cfg_text)

        def _script():
            from frontend.components.pipeline_banner import render_pipeline_header, render_step_next_action

            proj = {
                "project_id": "p_banner",
                "name": "BannerProj",
                "extraction_mode": "fixed",
                "documents": [{"id": "d1", "name": "a.txt", "text": "abc"}],
                "catalog": {"entity_types": [{"name": "A"}], "relations": [{"name": "r"}]},
                "nodes": [],
                "edges": [],
                "runs": [],
            }
            render_pipeline_header(proj)
            render_step_next_action("documents", proj)

        at = AppTest.from_function(_script)
        at.run()
        self.assertFalse(at.exception)
        # Header no longer renders 5 competing navigation buttons; only the 1 secondary step CTA button renders
        self.assertEqual(len(at.button), 1)
        self.assertEqual(at.button[0].key, "btn_next_action_documents")

    def test_u2_step1_simplified_table_and_persistent_upload_report(self) -> None:
        at = AppTest.from_string(_app_script_for_step("documents"))
        proj = _sample_project()
        proj["documents"][0]["text"] = proj["documents"][0]["text"] + (" A" * 1600)
        at.session_state["_test_project"] = proj
        at.session_state["_p01_upload_report_proj_ux_test"] = [
            {"name": "valid_doc.txt", "ok": True, "msg": "Đã đọc thành công 100 ký tự."},
            {"name": "empty_doc.txt", "ok": False, "msg": "Tệp không chứa văn bản đọc được."},
        ]
        at.run()
        self.assertFalse(at.exception)
        self.assertTrue(any("valid_doc.txt" in s.value for s in at.success))
        self.assertTrue(any("empty_doc.txt" in e.value for e in at.error))
        self.assertTrue(any("3,000" in c.value for c in at.caption))
        self.assertTrue(any("3,000" in t.label for t in at.text_area))
        self.assertTrue(len(at.dataframe) >= 1)

    def test_u3_step2_preview_isolation_and_baseline_b_warning(self) -> None:
        def _script():
            import streamlit as st
            from frontend.pages.p02_catalogs_prompts import render_catalogs_prompts_page
            from frontend.state.session import ensure_session_state

            proj = st.session_state["_test_project"]
            st.session_state["project"] = proj
            st.session_state["active_project_name"] = proj["name"]
            st.session_state["_loaded_name"] = proj["name"]
            ensure_session_state()
            render_catalogs_prompts_page(proj)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("backend.facade.get_facade") as mock_get_facade:
                facade = mock_get_facade.return_value
                facade.list_prompt_versions.return_value = []
                facade.get_edc_plus_r_settings.return_value = type(
                    "Cfg",
                    (),
                    {
                        "enable_schema_retrieval": False,
                        "retrieval_top_k": 5,
                        "candidate_threshold": 0.55,
                        "auto_align_threshold": 0.88,
                        "max_refine_loops": 1,
                        "embedding_model": "BAAI/bge-m3",
                    },
                )()
                facade.preview_prompt_request.return_value = {
                    "system_prompt": "sys",
                    "user_message": "usr",
                    "prompt_content_hash": "h123",
                    "prepared_request_hash": "r123",
                }
                proj = _sample_project(mode=MODE_FIXED)
                proj["_storage_dir"] = tmp

                at = AppTest.from_function(_script)
                at.session_state["_test_project"] = proj
                at.run()
                self.assertFalse(at.exception)

                # Changing radio to free_triples only inspects specs, does NOT mutate project["extraction_mode"]
                mode_radio = [r for r in at.radio if r.key == "p02_radio_extraction_mode"][0]
                mode_radio.set_value(MODE_FREE_TRIPLES).run()
                self.assertFalse(at.exception)
                self.assertEqual(proj["extraction_mode"], MODE_FIXED)
                self.assertTrue(any("Baseline B" in str(m.value) for m in at.markdown))

                # When applied mode is free_triples, Vùng 3 warns that catalogs/gazetteer are NOT used
                proj_b = _sample_project(mode=MODE_FREE_TRIPLES)
                at_b = AppTest.from_function(_script)
                at_b.session_state["_test_project"] = proj_b
                at_b.run()
                self.assertFalse(at_b.exception)
                self.assertTrue(any("KHÔNG" in w.value and "Baseline B" in w.value for w in at_b.warning))

    def test_u4_step3_summary_card_disclosure_and_no_nested_expander(self) -> None:
        at = AppTest.from_string(_app_script_for_step("extraction"))
        at.session_state["_test_project"] = _sample_project()
        at.run()
        self.assertFalse(at.exception)
        btn_keys = {b.key for b in at.button}
        self.assertIn("p03_btn_goto_setup", btn_keys)
        self.assertNotIn("p03_btn_save_toml", btn_keys)
        self.assertNotIn("p03_slider_in_tokens", {s.key for s in at.slider})
        self.assertTrue(any("vẫn gọi AI thực tế" in c.value for c in at.caption))

    def test_u5_step4_prev_next_navigation_and_direct_decision_panel(self) -> None:
        def _script():
            import streamlit as st
            from frontend.components.evidence_panel import render_edge_evidence_and_inspector_panel
            from frontend.state.session import ensure_session_state, get_curation_section_state

            proj = st.session_state["_test_project"]
            st.session_state["project"] = proj
            st.session_state["active_project_name"] = proj["name"]
            st.session_state["_loaded_name"] = proj["name"]
            ensure_session_state()
            s_state = get_curation_section_state(proj, "edges")
            if not s_state.get("ordered_edge_ids"):
                s_state["ordered_edge_ids"] = ["e1", "e2"]
            fid = s_state.get("focused_edge_id") or "e1"
            render_edge_evidence_and_inspector_panel(proj, fid)

        at = AppTest.from_function(_script)
        at.session_state["_test_project"] = _sample_project()
        at.run()
        self.assertFalse(at.exception)
        btn_keys = {b.key for b in at.button}
        self.assertIn("btn_next_focused_edge_e1", btn_keys)
        self.assertIn("btn_save_single_edge_e1", btn_keys)

        # Click "Mục tiếp ▶️" -> moves focus by edge_id from e1 to e2
        next_btn = [b for b in at.button if b.key == "btn_next_focused_edge_e1"][0]
        next_btn.click().run()
        self.assertFalse(at.exception)
        self.assertIn("btn_prev_focused_edge_e2", {b.key for b in at.button})
        self.assertIn("btn_save_single_edge_e2", {b.key for b in at.button})

    def test_u6_step5_source_badge_contrast_dot_and_keyboard_table(self) -> None:
        from frontend.components.graph_view import build_graph_dot

        dot = build_graph_dot([{"id": "n1", "name": "Chùa Một Cột"}], [])
        self.assertIn("#EFF6FF", dot)
        self.assertIn("#1D4ED8", dot)

        at = AppTest.from_string(_app_script_for_step("explore"))
        at.session_state["_test_project"] = _sample_project()
        at.run()
        self.assertFalse(at.exception)
        self.assertTrue(any("ĐỒ THỊ ĐÃ ĐƯỢC NGƯỜI DÙNG KIỂM DUYỆT" in s.value for s in at.success))
        self.assertTrue(any("Giới hạn cạnh hiển thị chỉ áp dụng cho sơ đồ minh họa" in c.value for c in at.caption))

    def test_e2e_all_five_steps_smoke_and_project_isolation(self) -> None:
        for step in ("documents", "setup", "extraction", "review", "explore"):
            with self.subTest(step=step):
                at = AppTest.from_string(_app_script_for_step(step))
                at.session_state["_test_project"] = _sample_project(mode=MODE_EDC_PLUS_R)
                at.run()
                self.assertFalse(at.exception, f"Step {step} raised exception: {at.exception}")


if __name__ == "__main__":
    unittest.main()
