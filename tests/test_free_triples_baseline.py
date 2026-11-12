"""Behavioral contracts for the schema-free, artifact-only extraction baseline.

All repositories in this suite use temporary roots. No provider SDK or network
connection is needed: the fake gateway reuses only request preparation.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.domain.extraction.base_engine import ChunkContext
from backend.domain.extraction.registry import EngineRegistry
from backend.domain.prompts.service import (
    ensure_project_prompt_history,
    get_active_prompt_content,
)
from backend.integrations.llm.errors import LLMError
from backend.integrations.llm.gateway import LLMGateway
from backend.modules.extraction.application.free_triples_engine import FreeTriplesEngine
from backend.modules.extraction.public import ExtractionApplicationService
from backend.modules.projects.public import ProjectCommitCoordinator
from backend.repositories.json_repo import JsonProjectRepository, empty_project
from shared.constants import (
    DEFAULT_FREE_TRIPLES_PROMPT,
    MODE_FIXED,
    MODE_FREE_TRIPLES,
)
from shared.schemas.free_triples import (
    FREE_TRIPLES_SCHEMA,
    parse_free_triples_json,
    validate_free_triples,
)


SOURCE_TEXT = "Di tích A được xây vào khoảng năm 1800. Đợt sửa chữa chưa rõ người chủ trì."
TRIPLE = {
    "subject": " Di tích A ",
    "predicate": "được_xây_vào_khoảng",
    "object": "khoảng năm 1800",
    "evidence": "Di tích A được xây vào khoảng năm 1800.",
}
PROTECTED_FIELDS = (
    "nodes", "edges", "relations", "relation_notes", "entity_types",
    "schema_proposals", "schema_decisions", "node_redirects", "relation_redirects",
)


class FakeFreeTriplesGateway:
    """Return raw free triples without delegating to a provider or EDC logic."""

    prepare_extraction_request = staticmethod(LLMGateway.prepare_extraction_request)

    def __init__(self, payload: dict | None = None, *, raw: str | None = None, fail: bool = False):
        self.payload = copy.deepcopy(payload if payload is not None else {"triples": [TRIPLE]})
        self.raw = raw if raw is not None else json.dumps(self.payload, ensure_ascii=False)
        self.fail = fail
        self.calls: list[dict] = []

    def extract(self, provider, api_key, model, system_prompt, chunk, allowed_relations, **kwargs):
        self.calls.append({
            "provider": provider, "model": model, "system_prompt": system_prompt,
            "chunk": chunk, "allowed_relations": list(allowed_relations), **kwargs,
        })
        prep_keys = {
            "temperature", "max_tokens", "max_input_tokens", "open_mode",
            "output_contract", "project_id", "configuration_id", "prompt_version_id",
            "prompt_content_hash", "base_instructions", "appended_content", "loop_index",
            "retrieval_summary",
        }
        prep = self.prepare_extraction_request(
            provider, model, system_prompt, chunk, allowed_relations,
            **{key: value for key, value in kwargs.items() if key in prep_keys},
        )
        if self.fail:
            error = LLMError(
                "Invalid baseline response", "json", input_tokens=23,
                output_tokens=11, raw=self.raw,
            )
            error.prepared_request = prep
            raise error
        return SimpleNamespace(
            data=copy.deepcopy(self.payload), raw=self.raw, input_tokens=100,
            output_tokens=40, warnings=[], prepared_request=prep,
        )


def make_project() -> tuple[dict, dict, dict]:
    project = empty_project("Free Triples Test")
    project["extraction_mode"] = MODE_FREE_TRIPLES
    project["edc_prompt"] = "EDC_ONLY_MARKER: require definitions and canonical labels."
    project["relations"] = ["CATALOG_ONLY_MARKER"]
    project["relation_notes"] = {
        "CATALOG_ONLY_MARKER": {"description": "Existing relation", "definition": "Existing canonical predicate"},
    }
    project["entity_types"] = [{"name": "CATALOG_TYPE_MARKER", "description": "Existing type", "definition": "An existing type"}]
    project["nodes"] = [{"id": "old-node", "name": "Existing", "kind": "CATALOG_TYPE_MARKER", "attributes": {}}]
    project["schema_proposals"] = [{
        "id": "old-proposal", "kind": "relations", "name": TRIPLE["predicate"],
        "status": "merged", "canonical_name": "CATALOG_ONLY_MARKER", "definition": "Existing mapping",
    }]
    document = {"id": "doc-free", "name": "di_tich.txt", "text": SOURCE_TEXT, "chars": len(SOURCE_TEXT)}
    project["documents"] = [document]
    record = {
        "text": SOURCE_TEXT, "chunk_number": 1, "chunk_hash": "fixture-free-chunk",
        "start_char": 0, "end_char": len(SOURCE_TEXT),
    }
    return project, document, record


def protected_snapshot(project: dict) -> dict:
    return {key: copy.deepcopy(project.get(key)) for key in PROTECTED_FIELDS}


class FreeTriplesContractTests(unittest.TestCase):
    def test_structural_schema_does_not_enumerate_domain_labels(self):
        item = FREE_TRIPLES_SCHEMA["properties"]["triples"]["items"]
        self.assertEqual(set(item["properties"]), {"subject", "predicate", "object", "evidence"})
        self.assertNotIn("enum", item["properties"]["predicate"])
        self.assertNotIn("dinh_nghia_quan_he", json.dumps(FREE_TRIPLES_SCHEMA))

    def test_parser_preserves_unicode_whitespace_and_duplicate_triples(self):
        payload = {"triples": [TRIPLE, TRIPLE]}
        raw = json.dumps(payload, ensure_ascii=False)
        parsed = parse_free_triples_json(raw)
        self.assertEqual(parsed, payload)
        self.assertEqual(parsed["triples"][0]["subject"], " Di tích A ")
        self.assertEqual(parsed["triples"][0]["predicate"], "được_xây_vào_khoảng")
        self.assertEqual(parse_free_triples_json("```json\n" + raw + "\n```"), payload)

    def test_parser_rejects_non_json_and_wrong_top_level_contract(self):
        for text in (
            "not JSON", '[]', '{"triples": null}', '{"triples": {}}',
            '{"triples": []} trailing output', '{"thuc_the": [], "quan_he": []}',
            '{"triples": [], "triples": []}', '{"triples": [NaN]}',
            '{"triples": [1e9999]}', '{"triples": [-1e9999]}',
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_free_triples_json(text)

    def test_invalid_items_and_evidence_mismatches_are_diagnosed_without_rewriting(self):
        mismatch = {**TRIPLE, "evidence": "This quote does not occur in the document."}
        payload = {"triples": [TRIPLE, mismatch, {"subject": "Incomplete"}, "not an object"]}
        before = copy.deepcopy(payload)
        report = validate_free_triples(payload, SOURCE_TEXT)
        self.assertEqual(payload, before)
        self.assertEqual(report["total_triples"], 4)
        self.assertEqual(report["valid_triples"], 2)
        self.assertEqual(report["invalid_triples"], 2)
        self.assertEqual(report["evidence_mismatch"], 1)
        self.assertEqual(len(report["items"]), 4)

    def test_duplicate_triples_are_counted_not_deduplicated(self):
        payload = {"triples": [TRIPLE, TRIPLE]}
        report = validate_free_triples(payload, SOURCE_TEXT)
        self.assertEqual(report["duplicate_triples"], 1)
        self.assertEqual(len(payload["triples"]), 2)

    def test_empty_result_is_a_valid_baseline_result(self):
        report = validate_free_triples({"triples": []}, SOURCE_TEXT)
        self.assertEqual(report["total_triples"], 0)
        self.assertEqual(report["invalid_triples"], 0)
        self.assertEqual(report["items"], [])

    def test_prompt_migration_has_independent_default_and_is_idempotent(self):
        project, _, _ = make_project()
        ensure_project_prompt_history(project)
        old_bindings = copy.deepcopy(project["prompt_bindings"])
        old_versions = copy.deepcopy(project["prompt_versions"])
        self.assertEqual(get_active_prompt_content(project, MODE_FREE_TRIPLES), DEFAULT_FREE_TRIPLES_PROMPT.strip())
        self.assertNotIn("EDC_ONLY_MARKER", get_active_prompt_content(project, MODE_FREE_TRIPLES))
        ensure_project_prompt_history(project)
        self.assertEqual(project["prompt_bindings"], old_bindings)
        self.assertEqual(project["prompt_versions"], old_versions)

    def test_migration_of_three_mode_project_preserves_all_existing_versions(self):
        project, _, _ = make_project()
        project["prompt_bindings"].pop(MODE_FREE_TRIPLES, None)
        project["prompt_versions"] = [
            version for version in project["prompt_versions"]
            if version.get("configuration_id") != MODE_FREE_TRIPLES
        ]
        old_versions = copy.deepcopy(project["prompt_versions"])
        old_bindings = copy.deepcopy(project["prompt_bindings"])
        ensure_project_prompt_history(project)
        self.assertEqual(project["prompt_versions"][:len(old_versions)], old_versions)
        self.assertTrue(all(project["prompt_bindings"][key] == value for key, value in old_bindings.items()))
        self.assertEqual(get_active_prompt_content(project, MODE_FREE_TRIPLES), DEFAULT_FREE_TRIPLES_PROMPT)


class FreeTriplesEngineTests(unittest.TestCase):
    def test_engine_retains_raw_result_and_never_ingests_or_canonicalizes(self):
        project, document, record = make_project()
        gateway = FakeFreeTriplesGateway({"triples": [TRIPLE, TRIPLE]})
        engine = FreeTriplesEngine(llm_gateway=gateway)
        protected = protected_snapshot(project)
        with patch.object(engine, "perform_ingest", side_effect=AssertionError("Baseline must not ingest")):
            output = engine.process_chunk(ChunkContext(
                project=project, document=document, chunk_record=record,
                provider="deepseek", api_key="dummy", model="test-model",
            ))
        self.assertEqual(protected_snapshot(project), protected)
        self.assertEqual(output.payload, gateway.payload)
        self.assertEqual(output.raw_response, gateway.raw)
        self.assertEqual(output.ingest_stats["added_nodes"], 0)
        self.assertEqual(output.ingest_stats["added_edges"], 0)
        self.assertEqual(output.ingest_stats["extracted_triples"], 2)
        self.assertEqual(output.input_tokens, 100)
        self.assertEqual(output.output_tokens, 40)
        call = gateway.calls[0]
        self.assertEqual(call["allowed_relations"], [])
        self.assertEqual(call["output_contract"], MODE_FREE_TRIPLES)
        self.assertTrue(call["open_mode"])
        for marker in ("EDC_ONLY_MARKER", "CATALOG_ONLY_MARKER", "CATALOG_TYPE_MARKER"):
            self.assertNotIn(marker, call["system_prompt"])

    def test_engine_does_not_discard_unknown_labels_or_bad_evidence(self):
        project, document, record = make_project()
        triple = {**TRIPLE, "predicate": "unknown predicate / with raw punctuation!", "evidence": "No support here"}
        gateway = FakeFreeTriplesGateway({"triples": [triple]})
        output = FreeTriplesEngine(llm_gateway=gateway).process_chunk(ChunkContext(
            project, document, record, "deepseek", "dummy", "test-model",
        ))
        self.assertEqual(output.payload["triples"], [triple])
        self.assertEqual(output.ingest_stats["evidence_mismatch"], 1)
        self.assertEqual(output.ingest_stats["invalid_triples"], 0)


class FreeTriplesApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = JsonProjectRepository(Path(self.temp.name) / "projects")
        self.coordinator = ProjectCommitCoordinator(project_store=self.repo)
        self.gateway = FakeFreeTriplesGateway()
        self.registry = EngineRegistry()
        self.registry.register(FreeTriplesEngine(llm_gateway=self.gateway))
        self.service = ExtractionApplicationService(
            engine_registry=self.registry, llm_gateway=self.gateway,
            project_store=self.repo, commit_coordinator=self.coordinator,
        )
        self.project, self.document, self.record = make_project()
        self.repo.save_project(self.project)
        self.project = self.repo.load_project(self.project["name"])

    def extract(self):
        return self.service.extract_chunk(
            self.project, self.document, self.record,
            provider="deepseek", api_key="dummy", model="test-model",
        )

    def test_registered_modes_keep_existing_engines_and_add_baseline(self):
        modes = {mode["mode_id"] for mode in self.registry.available_modes()}
        self.assertEqual(modes, {"closed", "edc", "edc_plus_r", MODE_FREE_TRIPLES})

    def test_preview_and_execution_use_the_same_request_without_schema_content(self):
        ensure_project_prompt_history(self.project)
        preview = self.service.preview_extraction_request(
            self.project, configuration_id=MODE_FREE_TRIPLES,
            doc_id=self.document["id"], chunk_number=1,
            provider="deepseek", model="test-model", max_input_tokens=12000,
        )
        output = self.extract()
        self.assertEqual(preview.request_hash, output.prepared_request_hash)
        self.assertEqual(preview.system_prompt, output.prepared_request["system_prompt"])
        self.assertEqual(preview.user_message, output.prepared_request["user_message"])
        self.assertEqual(preview.allowed_relations, [])
        self.assertEqual(preview.retrieval_summary, {})
        self.assertNotIn("dummy", json.dumps(output.prepared_request, ensure_ascii=False))

    def test_selected_baseline_preview_does_not_mutate_active_mode_or_legacy_project(self):
        self.project["extraction_mode"] = MODE_FIXED
        self.project.pop("prompt_bindings", None)
        self.project.pop("prompt_versions", None)
        self.project.pop("prompt_history_schema_version", None)
        before = copy.deepcopy(self.project)
        preview = self.service.preview_extraction_request(
            self.project, configuration_id=MODE_FREE_TRIPLES,
            doc_id=self.document["id"], provider="deepseek", model="test-model",
        )
        self.assertEqual(self.project, before)
        self.assertEqual(preview.configuration_id, MODE_FREE_TRIPLES)
        self.assertEqual(preview.allowed_relations, [])
        self.assertNotIn("CATALOG_ONLY_MARKER", preview.system_prompt)

    def test_result_persists_and_exports_without_entering_the_curated_graph(self):
        before = protected_snapshot(self.project)
        output = self.extract()
        self.assertEqual(protected_snapshot(self.project), before)
        run = self.project["runs"][-1]
        self.assertEqual(run["extraction_payload"], output.payload)
        self.assertEqual(run["extraction_mode"], MODE_FREE_TRIPLES)
        self.assertEqual(run["status"], "ok")
        self.assertTrue(run["run_id"])
        self.assertEqual(run["validation_report"]["total_triples"], 1)
        self.assertTrue(run["prepared_request_hash"])
        loaded = self.repo.load_project(self.project["name"])
        self.assertEqual(loaded["runs"][-1]["extraction_payload"], output.payload)
        self.assertEqual(protected_snapshot(loaded), before)
        self.project["runs"].append({"extraction_mode": MODE_FIXED, "raw_response": "Not baseline"})
        exported = json.loads(self.service.export_free_triples_results(self.project))
        self.assertEqual(exported["format"], "kg-studio.free-triples.v1")
        self.assertEqual(exported["extraction_mode"], MODE_FREE_TRIPLES)
        self.assertEqual(len(exported["runs"]), 1)
        self.assertEqual(exported["runs"][0]["extraction_payload"], output.payload)

    def test_raw_output_larger_than_display_limit_is_not_truncated(self):
        self.gateway.raw = " " * 100_100 + json.dumps(self.gateway.payload, ensure_ascii=False)
        output = self.extract()
        run = self.project["runs"][-1]
        self.assertEqual(run["raw_response"], output.raw_response)
        self.assertEqual(run["raw_response"], self.gateway.raw)
        self.assertFalse(run["raw_truncated"])
        self.assertEqual(self.repo.load_project(self.project["name"])["runs"][-1]["raw_response"], self.gateway.raw)

    def test_parse_failure_is_recorded_with_provenance_and_not_marked_processed(self):
        self.gateway.fail = True
        self.gateway.raw = '{"triples": ['
        before = protected_snapshot(self.project)
        processed = copy.deepcopy(self.project.get("processed_chunks", {}))
        with self.assertRaises(LLMError):
            self.extract()
        self.assertEqual(protected_snapshot(self.project), before)
        self.assertEqual(self.project.get("processed_chunks", {}), processed)
        run = self.project["runs"][-1]
        self.assertEqual(run["status"], "error")
        self.assertEqual(run["raw_response"], self.gateway.raw)
        self.assertEqual(run["input_tokens"], 23)
        self.assertEqual(run["output_tokens"], 11)
        self.assertTrue(run["prepared_request_hash"])
        self.assertEqual(self.repo.load_project(self.project["name"])["runs"][-1]["status"], "error")

    def test_missing_baseline_registration_never_falls_back_to_fixed_engine(self):
        with self.assertRaisesRegex(ValueError, "không fallback"):
            EngineRegistry().get(MODE_FREE_TRIPLES)
        service = ExtractionApplicationService(engine_registry=EngineRegistry())
        with self.assertRaisesRegex(ValueError, "không fallback"):
            service.extract_chunk(self.project, self.document, self.record,
                                  provider="deepseek", api_key="dummy", model="test-model")
        self.assertEqual(self.gateway.calls, [])

    def test_injected_gateway_registers_baseline_without_a_global_gateway(self):
        service = ExtractionApplicationService(llm_gateway=self.gateway)
        output = service.extract_chunk(self.project, self.document, self.record,
                                       provider="deepseek", api_key="dummy", model="test-model")
        self.assertEqual(output.payload, self.gateway.payload)

    def test_raw_request_and_cache_are_independent_of_project_schema(self):
        first = self.extract()
        first_cache = self.project["runs"][-1]["cache_key"]
        self.project["relations"] = ["DIFFERENT_SCHEMA_MARKER"]
        self.project["entity_types"] = []
        second = self.extract()
        self.assertEqual(first.prepared_request_hash, second.prepared_request_hash)
        self.assertEqual(first_cache, self.project["runs"][-1]["cache_key"])
        self.assertEqual(len(self.project["runs"]), 2)  # reruns remain separate attempts

    def test_parallel_runs_are_committed_once_without_secondary_project_save(self):
        before = protected_snapshot(self.project)
        records = [{**self.record, "chunk_number": index, "chunk_hash": f"chunk-{index}"} for index in range(1, 5)]
        with patch.object(self.service, "_save_project_safe", side_effect=AssertionError("No secondary save")):
            summary = self.service.extract_chunks_parallel(
                self.project, [(self.document, record) for record in records],
                provider="deepseek", api_key="dummy", model="test-model", max_workers=3,
            )
        self.assertEqual(summary["failed_count"], 0)
        self.assertEqual(summary["success_count"], 4)
        loaded = self.repo.load_project(self.project["name"])
        self.assertEqual(len(loaded["runs"]), 4)
        self.assertEqual(len({run["run_id"] for run in loaded["runs"]}), 4)
        self.assertEqual(protected_snapshot(self.project), before)
        version_ids = {v["id"] for v in loaded["prompt_versions"]}
        self.assertTrue(all(run["prompt_version_id"] in version_ids for run in loaded["runs"]))

    def test_unsaved_parallel_baseline_keeps_artifacts_in_memory_only(self):
        summary = self.service.extract_chunks_parallel(
            self.project, [(self.document, self.record)],
            provider="deepseek", api_key="dummy", model="test-model",
            max_workers=1, save_after_chunk=False,
        )
        self.assertEqual(summary["success_count"], 1)
        self.assertEqual(len(self.project["runs"]), 1)
        self.assertEqual(self.repo.load_project(self.project["name"])["runs"], [])

    def test_provider_credentials_are_redacted_from_persisted_artifacts(self):
        self.gateway.raw = "provider accidentally echoed dummy"
        # Invalid individual items are retained, so even their JSON keys must
        # be safe when a provider accidentally returns a credential there.
        self.gateway.payload["triples"].append({"dummy": "accidental echo"})
        self.extract()
        run = self.repo.load_project(self.project["name"])["runs"][-1]
        self.assertEqual(run["raw_response"], "provider accidentally echoed [REDACTED]")
        self.assertTrue(run["credentials_redacted"])
        self.assertEqual(run["extraction_payload"]["triples"][-1], {"[REDACTED]": "accidental echo"})
        self.assertNotIn("dummy", self.service.export_free_triples_results(self.project).decode("utf-8"))

    def test_commit_failure_does_not_leave_a_processed_or_partially_saved_run(self):
        runs = copy.deepcopy(self.project["runs"])
        processed = copy.deepcopy(self.project.get("processed_chunks", {}))
        with patch.object(self.repo, "save_project", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                self.extract()
        self.assertEqual(self.project["runs"], runs)
        self.assertEqual(self.project.get("processed_chunks", {}), processed)
        self.assertEqual(self.repo.load_project(self.project["name"])["runs"], runs)

    def test_baseline_ui_readiness_and_summary_do_not_require_catalogs_or_graph(self):
        from frontend.pages.p03_extraction import _extraction_result_summary
        from frontend.state.session import compute_pipeline_readiness

        self.project["relations"] = []
        self.project["entity_types"] = []
        self.project["nodes"] = []
        self.project["edges"] = []
        self.project["schema_proposals"] = []
        readiness = compute_pipeline_readiness(self.project)
        self.assertTrue(readiness["setup"]["ready"])
        output = self.extract()
        self.assertIn("Bộ ba trích xuất: 1", _extraction_result_summary(output.ingest_stats, MODE_FREE_TRIPLES))
        self.assertEqual(compute_pipeline_readiness(self.project)["overall_next"]["step_id"], "explore")


if __name__ == "__main__":
    unittest.main()
