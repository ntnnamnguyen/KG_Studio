"""Contracts for a read-only LLM baseline graph and shared algorithm input."""
from __future__ import annotations

import copy
import json
import unicodedata
import unittest

from backend.domain.graph.g_retriever import get_or_build_graph_index, load_project_from_export_bytes, retrieve_subgraph
from backend.modules.extraction.public import ExtractionApplicationService
from backend.modules.graph_qa.public import GraphQAApplicationService
from shared.constants import MODE_FREE_TRIPLES
from shared.schemas.graph_input import GraphSnapshotDTO


TEXT = "Đền A tọa lạc tại Quận B."
TRIPLE = {"subject": "Đền A", "predicate": "tọa lạc tại", "object": "Quận B", "evidence": TEXT}


def make_run(rid="run-1", *, chunk=1, triples=None, status="ok"):
    return {"run_id": rid, "extraction_mode": MODE_FREE_TRIPLES, "doc_id": "doc-1", "doc_name": "fixture.txt",
            "chunk_number": chunk, "chunk_hash": f"chunk-{chunk}", "status": status,
            "extraction_payload": {"triples": copy.deepcopy(triples if triples is not None else [TRIPLE])},
            "prepared_request": {"project_id": "p-baseline", "fitted_chunk_text": TEXT},
            "raw_response": "fixture raw", "prompt_version_id": "pv-test", "prepared_request_hash": "request-test",
            "input_tokens": 10, "output_tokens": 20, "start_char": 0, "end_char": len(TEXT)}


def make_project():
    return {"project_id": "p-baseline", "name": "Baseline fixture", "extraction_mode": MODE_FREE_TRIPLES,
            "documents": [{"id": "doc-1", "text": TEXT}], "runs": [make_run()],
            "nodes": [{"id": "legacy", "name": "Đền A", "aliases": ["Tên khác"], "kind": "Catalog type"}],
            "edges": [], "relations": ["Catalog predicate"], "node_redirects": {"legacy": "other"},
            "schema_proposals": [{"name": "Legacy proposal", "status": "pending"}]}


class BaselineGraphTests(unittest.TestCase):
    def setUp(self):
        self.project = make_project()
        self.extraction = ExtractionApplicationService()
        self.service = GraphQAApplicationService(neo4j_gateway=object(), baseline_source=self.extraction)

    def build(self, run_ids=None):
        return self.service.build_baseline_graph(self.project, {"project_id": self.project["project_id"],
                                                               "run_ids": run_ids or ["run-1"]})

    def test_read_and_build_are_detached_and_do_not_change_any_project_field(self):
        before = copy.deepcopy(self.project)
        bundle = self.extraction.read_free_triples_runs(self.project)
        bundle["runs"][0]["extraction_payload"]["triples"].clear()
        graph = self.build()
        graph.nodes[0]["name"] = "Edited detached view"
        self.assertEqual(self.project, before)
        self.assertEqual(self.build().nodes[0]["name"], TRIPLE["subject"])

    def test_normalization_merges_only_technical_variants_and_keeps_all_edges(self):
        self.project["runs"][0]["extraction_payload"]["triples"] = [TRIPLE, {
            **TRIPLE, "subject": unicodedata.normalize("NFD", "  đền   a "), "object": " QUẬN B "},
            {**TRIPLE, "subject": "Den A"}, {**TRIPLE, "subject": "Tên khác"}]
        graph = self.build()
        self.assertEqual(len(graph.nodes), 4)
        self.assertEqual(len(graph.edges), 4)
        self.assertEqual(graph.edges[0]["source"], graph.edges[1]["source"])
        self.assertNotEqual(graph.edges[0]["source"], graph.edges[2]["source"])
        self.assertNotEqual(graph.edges[0]["source"], graph.edges[3]["source"])
        self.assertTrue(all(node["kind"] == "" for node in graph.nodes))

    def test_predicates_are_verbatim_duplicates_and_self_loops_are_preserved(self):
        triple = {**TRIPLE, "predicate": "ĐƯỢC_xây_vào_khoảng!", "object": " ĐỀN A "}
        self.project["runs"][0]["extraction_payload"]["triples"] = [triple, triple]
        graph = self.build()
        self.assertEqual(len(graph.nodes), 1)
        self.assertEqual(len(graph.edges), 2)
        self.assertNotEqual(graph.edges[0]["id"], graph.edges[1]["id"])
        self.assertEqual(graph.edges[0]["relation"], triple["predicate"])
        self.assertEqual(graph.edges[0]["source"], graph.edges[0]["target"])
        self.assertNotIn("status", graph.edges[0])

    def test_invalid_items_remain_in_diagnostics_and_bad_evidence_still_has_an_edge(self):
        items = [None, {"subject": 42}, {**TRIPLE, "evidence": "absent"}, {**TRIPLE, "evidence": None, "extra": "retained"}]
        self.project["runs"][0]["extraction_payload"]["triples"] = items
        graph = self.build()
        self.assertEqual(len(graph.edges), 2)
        self.assertFalse(graph.edges[0]["evidence_found"])
        self.assertIsNone(graph.edges[1]["evidence_found"])
        self.assertEqual([d["item"] for d in graph.diagnostics], items)

    def test_missing_fitted_input_is_unknown_evidence_and_does_not_filter(self):
        self.project["runs"][0]["prepared_request"].pop("fitted_chunk_text")
        graph = self.build()
        self.assertEqual(len(graph.edges), 1)
        self.assertIsNone(graph.edges[0]["evidence_found"])
        self.assertTrue(any("Thiếu input" in issue for item in graph.diagnostics for issue in item["issues"]))
        self.assertFalse(any("không xuất hiện" in issue for item in graph.diagnostics for issue in item["issues"]))

    def test_failed_attempt_is_kept_in_manifest_and_diagnostics(self):
        self.project["runs"].append(make_run("failed", chunk=2, status="error"))
        graph = self.build(["failed", "run-1"])
        self.assertEqual(len(graph.edges), 1)
        self.assertEqual(len(graph.manifest["runs"]), 2)
        self.assertEqual(graph.diagnostics[0]["code"], "run_error")

    def test_cannot_mix_two_attempts_for_one_chunk_even_with_different_text_hash(self):
        rerun = make_run("rerun")
        rerun["chunk_hash"] = "other-version"
        self.project["runs"].append(rerun)
        with self.assertRaisesRegex(ValueError, "một attempt"):
            self.build(["run-1", "rerun"])
        self.assertEqual(len(self.build(["rerun"]).edges), 1)

    def test_identical_text_in_two_different_chunk_numbers_is_not_lost(self):
        second = make_run("run-2", chunk=2)
        second["chunk_hash"] = "chunk-1"
        self.project["runs"].append(second)
        self.assertEqual(len(self.build(["run-1", "run-2"]).edges), 2)

    def test_order_does_not_change_ids_or_fingerprint(self):
        self.project["runs"].append(make_run("run-2", chunk=2))
        first = self.build(["run-1", "run-2"])
        self.project["runs"].reverse()
        self.assertEqual(first.to_dict(), self.build(["run-2", "run-1"]).to_dict())

    def test_selection_fails_closed_for_scope_unknown_mode_or_duplicate_ids(self):
        for request in (
            {"project_id": "wrong", "run_ids": ["run-1"]},
            {"project_id": "p-baseline", "run_ids": ["missing"]},
            {"project_id": "p-baseline", "run_ids": ["run-1", "run-1"]},
            {"project_id": "p-baseline", "run_ids": ["run-1"], "policy": "semantic"},
        ):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.service.build_baseline_graph(self.project, request)
        self.project["runs"].append({**make_run("closed-run"), "extraction_mode": "closed"})
        with self.assertRaises(ValueError):
            self.build(["closed-run"])
        self.project["runs"][0]["prepared_request"]["project_id"] = "wrong"
        with self.assertRaises(ValueError):
            self.build()

    def test_source_changes_update_fingerprint_and_catalog_changes_do_not(self):
        first = self.build()
        self.project["nodes"].clear()
        self.project["relations"].append("Different catalog")
        self.assertEqual(first.fingerprint, self.build().fingerprint)
        self.project["runs"][0]["raw_response"] += "changed"
        self.assertNotEqual(first.fingerprint, self.build().fingerprint)

    def test_export_import_round_trip_and_mutated_snapshot_rejected(self):
        graph = self.build()
        graph.nodes[0]["unknown_unicode_field"] = "Văn hóa"
        graph.fingerprint = ""
        exported = self.service.export_graph_json(graph)
        loaded = self.service.import_graph_json(exported)
        self.assertEqual(loaded.nodes[0]["unknown_unicode_field"], "Văn hóa")
        project_input = load_project_from_export_bytes(exported, "baseline.json")
        self.assertEqual(project_input["graph_source"], "baseline")
        self.assertEqual(project_input["edges"], graph.edges)
        loaded.edges[0]["relation"] = "tampered"
        with self.assertRaisesRegex(ValueError, "Fingerprint"):
            self.service.export_graph_json(loaded)

    def test_dangling_or_duplicate_graph_ids_fail_before_algorithm_entry(self):
        data = self.build().to_dict()
        data["fingerprint"] = ""
        data["edges"][0]["target"] = "missing"
        with self.assertRaises(ValueError):
            GraphSnapshotDTO.model_validate(data)
        data = self.build().to_dict()
        data["nodes"].append(data["nodes"][0])
        data["fingerprint"] = ""
        with self.assertRaises(ValueError):
            GraphSnapshotDTO.model_validate(data)

    def test_all_existing_algorithms_run_on_unreviewed_baseline_without_source_mutation(self):
        graph = self.build()
        before = graph.to_dict()
        for method in ("naive_topk", "ppr", "pcst"):
            result = self.service.retrieve_subgraph(graph.as_project(), "Đền A tọa lạc tại Quận B", method=method)
            self.assertTrue(result.edges, method)
            self.assertEqual(result.edges[0]["run_id"], "run-1")
        self.assertEqual(graph.to_dict(), before)

    def test_explicit_approved_graph_never_falls_back_to_unreviewed_edges(self):
        self.project["nodes"] = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
        self.project["edges"] = [{"id": "e", "source": "a", "target": "b", "relation": "near"}]
        graph = self.service.graph_snapshot(self.project, source="approved")
        self.assertEqual(graph.edges, [])
        self.assertEqual(retrieve_subgraph(graph.as_project(), "A near B").edges, [])

    def test_cache_distinguishes_same_sized_graphs_and_isolated_old_index(self):
        original = self.build().as_project()
        first = get_or_build_graph_index(original)
        changed = copy.deepcopy(original)
        changed["nodes"][0]["name"] = "Different name"
        second = get_or_build_graph_index(changed)
        self.assertIsNot(first, second)
        original["nodes"][0]["name"] = "Another edit"
        self.assertNotEqual(first.nodes[0]["name"], original["nodes"][0]["name"])
        other_source = copy.deepcopy(changed)
        other_source["graph_source"] = "all"
        self.assertIsNot(second, get_or_build_graph_index(other_source))

    def test_independent_benchmark_uses_fact_variants_not_other_graph_ids_or_duplicate_counts(self):
        self.project["runs"][0]["extraction_payload"]["triples"] = [TRIPLE, TRIPLE]
        graph = self.build()
        fact = {"subject": ["Đền A"], "predicate": ["tọa lạc tại", "ở"], "object": ["Quận B"]}
        missing = {**fact, "object": ["Không có trong graph"]}
        gold = [{"id": "q1", "question": "Đền A tọa lạc tại đâu?", "gold_facts": [fact, missing]}]
        result = self.service.evaluate_graph_benchmark(graph, gold, max_edges=10)
        self.assertEqual(len(result["summary_table"]), 3)
        self.assertTrue(all(row["Facts có trong graph (%)"] == 50 for row in result["summary_table"]))
        self.assertTrue(all(row["Thu hồi facts chuẩn (%)"] == 50 for row in result["summary_table"]))
        changed = graph.to_dict()
        changed["source"], changed["fingerprint"] = "all", ""
        for edge in changed["edges"]:
            edge["id"] += "-different-id"
        second = self.service.evaluate_graph_benchmark(GraphSnapshotDTO.model_validate(changed), gold, max_edges=10)
        self.assertEqual(result["dataset_fingerprint"], second["dataset_fingerprint"])
        self.assertEqual([d["retrieved_fact_recall"] for d in result["per_question"]],
                         [d["retrieved_fact_recall"] for d in second["per_question"]])

    def test_benchmark_rejects_empty_gold_and_overlapping_fact_variants(self):
        graph = self.build()
        fact = {"subject": ["Đền A"], "predicate": ["tọa lạc tại"], "object": ["Quận B"]}
        for gold in ([], [{"id": "q", "question": "?", "gold_facts": []}],
                     [{"id": "q", "question": "?", "gold_facts": [fact, fact]}]):
            with self.assertRaises(ValueError):
                self.service.evaluate_graph_benchmark(graph, gold)

    def test_raw_run_download_is_not_silently_treated_as_a_graph(self):
        raw = self.extraction.export_free_triples_results(self.project)
        with self.assertRaisesRegex(ValueError, "raw runs"):
            load_project_from_export_bytes(raw, "raw.json")

    def test_shared_renderer_uses_ids_not_labels_and_escapes_text(self):
        from frontend.components.graph_view import build_graph_dot
        dot = build_graph_dot([{"id": "a", "name": 'same "label"'}, {"id": "b", "name": 'same "label"'}],
                              [{"id": "edge", "source": "a", "target": "b", "relation": "x\ny"}])
        self.assertIn('"a" -> "b"', dot)
        self.assertIn('same \\"label\\"', dot)


if __name__ == "__main__":
    unittest.main()
