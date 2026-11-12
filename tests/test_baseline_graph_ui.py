"""Actual shared-page flows using a fake LLM and isolated test storage."""
from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest

from tests.test_free_triples_ui import SETUP


PAGE = SETUP + '''
import copy
from frontend.pages.p05_graph_export import render_graph_export_page
if "baseline_graph_fixture" not in st.session_state:
    service = get_container().extraction_service
    document = project["documents"][0]
    record = service.document_chunks(document)[0]
    service.extract_chunk(project, document, record, provider="deepseek", api_key="dummy",
                          model="test-model", persist_run=False)
    st.session_state["baseline_graph_fixture"] = copy.deepcopy(project)
render_graph_export_page(project)
'''


class BaselineGraphUITests(unittest.TestCase):
    def test_real_extraction_to_shared_graph_page_retrieval_benchmark_and_source_switch(self):
        app = AppTest.from_string(PAGE).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        project = app.session_state["baseline_project"]
        rid = project["runs"][0]["run_id"]
        app.multiselect[0].set_value([rid]).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any(button.key == "p05_graph_json" for button in app.get("download_button")))
        self.assertTrue(app.get("graphviz_chart"))
        method = next(widget for widget in app.selectbox if str(widget.key).startswith("_gret_method_"))
        method.select("compare_all").run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertGreaterEqual(len(app.get("graphviz_chart")), 3)
        bench = next(button for button in app.button if str(button.key).startswith("_gret_btn_run_bench_"))
        key = bench.key.replace("_gret_btn_run_bench_", "_gret_bench_result_")
        bench.click().run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.session_state[key]["summary_table"]), 3)
        self.assertEqual(app.session_state["baseline_project"], app.session_state["baseline_graph_fixture"])
        from backend.bootstrap import get_container
        self.assertEqual(len(get_container().extraction_service.llm_gateway.calls), 1)
        source = next(widget for widget in app.radio if str(widget.key).startswith("p05_graph_source_"))
        source.set_value("approved").run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(next(metric.value for metric in app.metric if metric.label == "Nodes"), "0")

    def test_ambiguous_attempt_selection_shows_error_instead_of_an_old_or_approved_graph(self):
        script = PAGE.replace("render_graph_export_page(project)", '''
if "second_attempt" not in st.session_state:
    second = copy.deepcopy(project["runs"][0])
    second["run_id"] = "second-attempt"
    project["runs"].append(second)
    st.session_state["second_attempt"] = True
render_graph_export_page(project)
''')
        app = AppTest.from_string(script).run(timeout=20)
        ids = [run["run_id"] for run in app.session_state["baseline_project"]["runs"]]
        app.multiselect[0].set_value(ids).run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any("một attempt" in error.value for error in app.error))
        self.assertFalse(app.get("graphviz_chart"))

    def test_uploaded_approved_snapshot_does_not_export_or_train_the_current_project(self):
        script = PAGE.replace("render_graph_export_page(project)", '''
from unittest.mock import patch
from types import SimpleNamespace
from shared.schemas.graph_input import GraphSnapshotDTO
external = GraphSnapshotDTO(project_id="external", name="External graph", source="approved",
    nodes=[{"id":"x", "name":"External A"}, {"id":"y", "name":"External B"}],
    edges=[{"id":"xy", "source":"x", "target":"y", "relation":"near"}])
raw = get_container().graph_qa_service.export_graph_json(external)
def upload(label, **kwargs):
    return SimpleNamespace(name="external.json", getvalue=lambda: raw) if label == "Nạp graph JSON/ZIP" else None
with patch("streamlit.file_uploader", side_effect=upload):
    render_graph_export_page(project)
''')
        app = AppTest.from_string(script).run(timeout=20)
        source = next(widget for widget in app.radio if str(widget.key).startswith("p05_graph_source_"))
        source.set_value("external").run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(next(metric.value for metric in app.metric if metric.label == "Nodes"), "2")
        self.assertFalse(any(button.key == "btn_prep_zip" for button in app.button))
        self.assertTrue(any(button.key == "p05_graph_json" for button in app.get("download_button")))

    def test_independent_gold_upload_runs_on_same_algorithms_and_invalidates_stale_results(self):
        script = PAGE.replace("render_graph_export_page(project)", '''
import json
from unittest.mock import patch
from types import SimpleNamespace
from tests.test_free_triples_baseline import TRIPLE
missing = st.checkbox("Gold fixture has a missing fact", key="test_missing_gold")
gold = [{"id":"q1", "question":"Di tích A được xây vào khi nào?", "gold_facts":[{
    "subject":[TRIPLE["subject"]], "predicate":[TRIPLE["predicate"]],
    "object":["missing" if missing else TRIPLE["object"]]}]}]
raw = json.dumps(gold, ensure_ascii=False).encode("utf-8")
def upload(label, **kwargs):
    return SimpleNamespace(name="gold.json", getvalue=lambda: raw) if label.startswith("Bộ câu hỏi và gold") else None
with patch("streamlit.file_uploader", side_effect=upload):
    render_graph_export_page(project)
''')
        app = AppTest.from_string(script).run(timeout=20)
        rid = app.session_state["baseline_project"]["runs"][0]["run_id"]
        app.multiselect[0].set_value([rid]).run(timeout=20)
        bench = next(button for button in app.button if str(button.key).startswith("_gret_btn_run_bench_"))
        key = bench.key.replace("_gret_btn_run_bench_", "_gret_bench_result_")
        bench.click().run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        first = app.session_state[key]
        self.assertEqual(first["format"], "kg-studio.graph-benchmark.v1")
        self.assertTrue(all(row["Facts có trong graph (%)"] == 100 for row in first["summary_table"]))
        app.checkbox(key="test_missing_gold").check().run(timeout=20)
        self.assertNotIn(key, app.session_state)
        next(button for button in app.button if str(button.key).startswith("_gret_btn_run_bench_")).click().run(timeout=20)
        self.assertEqual(len(app.exception), 0)
        second = app.session_state[key]
        self.assertNotEqual(first["dataset_fingerprint"], second["dataset_fingerprint"])
        self.assertTrue(all(row["Facts có trong graph (%)"] == 0 for row in second["summary_table"]))


if __name__ == "__main__":
    unittest.main()
