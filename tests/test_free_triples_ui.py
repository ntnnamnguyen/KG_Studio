"""Offline Streamlit smoke tests for selecting, previewing and running baseline B."""
from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest


SETUP = '''
import streamlit as st
from backend.bootstrap import get_container
from backend.modules.extraction.public import FreeTriplesEngine
from backend.repositories.json_repo import empty_project
from shared.constants import MODE_FREE_TRIPLES
from tests.test_free_triples_baseline import FakeFreeTriplesGateway, SOURCE_TEXT

if "baseline_project" not in st.session_state:
    project = empty_project("UI baseline fixture")
    project["extraction_mode"] = MODE_FREE_TRIPLES
    project["documents"] = [{"id": "ui-doc", "name": "fixture.txt", "text": SOURCE_TEXT, "chars": len(SOURCE_TEXT)}]
    st.session_state["baseline_project"] = project
    gateway = FakeFreeTriplesGateway()
    container = get_container()
    container.extraction_service.llm_gateway = gateway
    container.extraction_service.engine_registry.register(FreeTriplesEngine(gateway))
    st.session_state["llm_provider"] = "deepseek"
    st.session_state["llm_model"] = "test-model"
    st.session_state["llm_api_key"] = "dummy"
    st.session_state["llm_max_input_tokens"] = 16384
    st.session_state["llm_max_output_tokens"] = 8192
project = st.session_state["baseline_project"]
'''


class FreeTriplesUISmokeTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        import shutil
        from pathlib import Path
        fixture_dir = Path("data/projects/ui_baseline_fixture")
        if fixture_dir.exists():
            shutil.rmtree(fixture_dir, ignore_errors=True)

    def test_baseline_option_and_preview_use_raw_contract(self):
        app = AppTest.from_string(SETUP + '''
from frontend.components.prompt_editor import render_prompt_management_panel
render_prompt_management_panel(project)
''').run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("B. Bộ ba tự do" in option for option in app.radio[0].options))
        app.button(key="btn_build_preview_free_triples").click().run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        preview = app.session_state["last_preview_free_triples"]
        self.assertEqual(preview.configuration_id, "free_triples")
        self.assertEqual(preview.allowed_relations, [])
        self.assertNotIn("dinh_nghia_quan_he", preview.system_prompt)

    def test_dry_run_displays_artifacts_and_download_without_graph_ingestion(self):
        app = AppTest.from_string(SETUP + '''
from frontend.pages.p03_extraction import render_extraction_page
render_extraction_page(project)
''').run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        app.button(key="btn_dry_run_one_chunk").click().run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        project = app.session_state["baseline_project"]
        self.assertEqual(len(project["runs"]), 1)
        self.assertEqual(project["runs"][0]["status"], "ok")
        self.assertEqual(project["runs"][0]["extraction_mode"], "free_triples")
        self.assertEqual(len(project["runs"][0]["extraction_payload"]["triples"]), 1)
        self.assertEqual(project["nodes"], [])
        self.assertEqual(project["edges"], [])
        self.assertGreaterEqual(len(app.get("download_button")), 1)
        app.button(key="p03_btn_baseline_graph").click().run(timeout=15)
        self.assertEqual(len(app.exception), 0)
        from frontend.state.session import get_active_step
        self.assertEqual(get_active_step({"active_page": app.session_state["active_page"]})[0], "explore")


if __name__ == "__main__":
    unittest.main()
