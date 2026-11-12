"""Offline provider contracts for the schema-free triple extraction baseline."""
from __future__ import annotations

import json
from types import SimpleNamespace
import unittest

from backend.integrations.llm.errors import LLMError
from backend.integrations.llm.gateway import LLMGateway
from backend.integrations.llm.providers import PROVIDER_ANTHROPIC, PROVIDER_DEEPSEEK, PROVIDER_OPENAI
from shared.constants import MODE_FREE_TRIPLES
from shared.schemas.free_triples import FREE_TRIPLES_SCHEMA, free_triples_prompt


class _FakeOpenAI:
    def __init__(
        self,
        content: str,
        *,
        finish: str = "stop",
        reject_format: bool = False,
        error: str = "",
    ) -> None:
        self.calls: list[dict] = []
        self.content = content
        self.finish = finish
        self.reject_format = reject_format
        self.error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise RuntimeError(self.error)
        if self.reject_format and "response_format" in kwargs:
            raise RuntimeError("response_format json_schema is not supported")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content), finish_reason=self.finish)],
            usage=SimpleNamespace(prompt_tokens=23, completion_tokens=17),
        )


class _FakeAnthropic:
    def __init__(self, content: str, *, stop_reason: str = "end_turn") -> None:
        self.calls: list[dict] = []
        self.content = content
        self.stop_reason = stop_reason
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.content)],
            usage=SimpleNamespace(input_tokens=19, output_tokens=13),
            stop_reason=self.stop_reason,
        )


class FreeTriplesGatewayTests(unittest.TestCase):
    def _extract(self, client, *, provider=PROVIDER_OPENAI, model="test-model", **kwargs):
        return LLMGateway.extract(
            provider,
            "dummy-not-a-real-secret",
            model,
            free_triples_prompt("Extract only statements supported by the supplied text."),
            "Công trình A được ông B phục dựng.",
            [],
            client=client,
            output_contract=MODE_FREE_TRIPLES,
            **kwargs,
        )

    def test_verbatim_predicates_and_duplicates_are_preserved(self) -> None:
        triple = {
            "subject": " Công trình A ",
            "predicate": "được_ông_B_phục_dựng!",
            "object": "ông B",
            "evidence": "Công trình A được ông B phục dựng.",
        }
        payload = {"triples": [triple, dict(triple)]}
        raw = json.dumps(payload, ensure_ascii=False)
        fake = _FakeOpenAI(raw)
        result = self._extract(fake)

        self.assertEqual(result.data, payload)
        self.assertEqual(result.raw, raw)
        self.assertEqual((result.input_tokens, result.output_tokens), (23, 17))
        prep = result.prepared_request
        self.assertEqual(prep.mode, MODE_FREE_TRIPLES)
        self.assertEqual(prep.allowed_relations, [])
        self.assertEqual(prep.retrieval_summary, {})
        self.assertNotIn("DANH SÁCH TÊN QUAN HỆ ĐƯỢC PHÉP", prep.user_message)
        self.assertNotIn("dinh_nghia_quan_he", prep.system_prompt)
        self.assertNotIn("dinh_nghia_loai", prep.system_prompt)
        self.assertEqual(prep.response_format["json_schema"]["schema"], FREE_TRIPLES_SCHEMA)
        self.assertNotIn("dummy-not-a-real-secret", json.dumps(prep.to_dict(), ensure_ascii=False))

    def test_preparation_matches_execution_and_records_fitted_input(self) -> None:
        prompt = free_triples_prompt("Extract statements.")
        chunk = "Đoạn văn bản. " * 2000
        kwargs = dict(
            max_input_tokens=512,
            max_tokens=512,
            configuration_id=MODE_FREE_TRIPLES,
            prompt_version_id="free-v1",
            prompt_content_hash="prompt-hash",
            output_contract=MODE_FREE_TRIPLES,
        )
        preview = LLMGateway.prepare_extraction_request(
            PROVIDER_OPENAI, "test-model", prompt, chunk, [], **kwargs,
        )
        fake = _FakeOpenAI('{"triples": []}')
        result = LLMGateway.extract(
            PROVIDER_OPENAI, "dummy", "test-model", prompt, chunk, [], client=fake, **kwargs,
        )

        self.assertLess(len(preview.fitted_chunk_text), len(chunk))
        self.assertEqual(preview.raw_chunk_text, chunk)
        self.assertTrue(preview.warnings)
        self.assertEqual(preview.request_hash, result.prepared_request.request_hash)
        self.assertEqual(preview.to_dict(), result.prepared_request.to_dict())
        self.assertIn(preview.fitted_chunk_text, fake.calls[0]["messages"][1]["content"])

    def test_domain_allowlist_is_rejected_before_any_provider_call(self) -> None:
        fake = _FakeOpenAI('{"triples": []}')
        with self.assertRaisesRegex(ValueError, "danh mục"):
            LLMGateway.extract(
                PROVIDER_OPENAI, "dummy", "test-model", "SYS", "Document", ["nằm tại"],
                client=fake, output_contract=MODE_FREE_TRIPLES,
            )
        self.assertEqual(fake.calls, [])

    def test_unknown_output_contract_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "Hợp đồng"):
            LLMGateway.prepare_extraction_request(
                PROVIDER_OPENAI, "test-model", "SYS", "Document", [], output_contract="typo",
            )

    def test_deepseek_uses_json_object_without_edc_definitions(self) -> None:
        fake = _FakeOpenAI('{"triples": []}')
        result = self._extract(fake, provider=PROVIDER_DEEPSEEK, model="deepseek-chat")
        self.assertEqual(result.data, {"triples": []})
        self.assertEqual(fake.calls[0]["response_format"], {"type": "json_object"})
        self.assertEqual(fake.calls[0]["extra_body"], {"thinking": {"type": "disabled"}})

    def test_anthropic_uses_same_free_payload_without_response_format_kwarg(self) -> None:
        fake = _FakeAnthropic('```json\n{"triples": []}\n```')
        result = self._extract(fake, provider=PROVIDER_ANTHROPIC, model="claude-test")
        self.assertEqual(result.data, {"triples": []})
        self.assertEqual(result.raw, fake.content)
        self.assertEqual((result.input_tokens, result.output_tokens), (19, 13))
        self.assertNotIn("response_format", fake.calls[0])

    def test_unsupported_format_fallback_retains_raw_and_warning(self) -> None:
        raw = '{"triples": []}'
        fake = _FakeOpenAI(raw, reject_format=True)
        result = self._extract(fake)
        self.assertEqual(result.raw, raw)
        self.assertEqual(result.data, {"triples": []})
        self.assertEqual(len(fake.calls), 2)
        self.assertIn("response_format", fake.calls[0])
        self.assertNotIn("response_format", fake.calls[1])
        self.assertTrue(any("response_format" in warning for warning in result.warnings))

    def test_invalid_top_level_retains_raw_tokens_and_prepared_request(self) -> None:
        for raw in ('{"thuc_the": [], "quan_he": []}', '{"triples": {}}', '{"triples": ['):
            with self.subTest(raw=raw), self.assertRaises(LLMError) as caught:
                self._extract(_FakeOpenAI(raw))
            error = caught.exception
            self.assertEqual(error.kind, "json")
            self.assertEqual(error.raw, raw)
            self.assertEqual((error.input_tokens, error.output_tokens), (23, 17))
            self.assertEqual(error.prepared_request.mode, MODE_FREE_TRIPLES)
            self.assertTrue(error.prepared_request.request_hash)

    def test_invalid_individual_triples_are_retained_for_engine_diagnostics(self) -> None:
        payload = {"triples": [None, {"subject": "A"}, {"subject": "A", "predicate": 1, "object": "B"}]}
        result = self._extract(_FakeOpenAI(json.dumps(payload)))
        self.assertEqual(result.data, payload)

    def test_openai_and_anthropic_truncation_retain_error_provenance(self) -> None:
        cases = (
            (PROVIDER_OPENAI, _FakeOpenAI('{"triples": []}', finish="length"), (23, 17)),
            (PROVIDER_ANTHROPIC, _FakeAnthropic('{"triples": []}', stop_reason="max_tokens"), (19, 13)),
        )
        for provider, fake, tokens in cases:
            with self.subTest(provider=provider), self.assertRaises(LLMError) as caught:
                self._extract(fake, provider=provider)
            self.assertEqual(caught.exception.kind, "token_limit")
            self.assertEqual(caught.exception.raw, '{"triples": []}')
            self.assertEqual((caught.exception.input_tokens, caught.exception.output_tokens), tokens)
            self.assertEqual(caught.exception.prepared_request.mode, MODE_FREE_TRIPLES)

    def test_provider_error_retains_prepared_request_without_credentials(self) -> None:
        with self.assertRaises(LLMError) as caught:
            self._extract(_FakeOpenAI("", error="429 rate limit"))
        error = caught.exception
        self.assertEqual(error.kind, "rate_limit")
        self.assertEqual(error.prepared_request.mode, MODE_FREE_TRIPLES)
        self.assertNotIn("dummy-not-a-real-secret", json.dumps(error.prepared_request.to_dict()))

    def test_missing_credentials_fail_without_network_and_keep_preparation(self) -> None:
        with self.assertRaises(LLMError) as caught:
            LLMGateway.extract(
                PROVIDER_OPENAI, "", "test-model", "SYS", "Document", [],
                output_contract=MODE_FREE_TRIPLES,
            )
        self.assertEqual(caught.exception.kind, "auth")
        self.assertEqual(caught.exception.prepared_request.fitted_chunk_text, "Document")

    def test_legacy_fixed_and_edc_contracts_are_unchanged(self) -> None:
        fixed = {"thuc_the": [], "quan_he": []}
        fake_fixed = _FakeOpenAI(json.dumps(fixed))
        result_fixed = LLMGateway.extract(
            PROVIDER_OPENAI, "dummy", "test-model", "SYS", "Document", ["nằm tại"], client=fake_fixed,
        )
        self.assertEqual(result_fixed.data, fixed)
        self.assertIn("nằm tại", result_fixed.prepared_request.user_message)
        self.assertEqual(result_fixed.prepared_request.mode, "closed")
        self.assertEqual(result_fixed.prepared_request.response_format, {"type": "json_object"})

        edc = {**fixed, "dinh_nghia_quan_he": [], "dinh_nghia_loai": []}
        result_edc = LLMGateway.extract(
            PROVIDER_OPENAI, "dummy", "test-model", "SYS", "Document", [],
            client=_FakeOpenAI(json.dumps(edc)), open_mode=True,
        )
        self.assertEqual(result_edc.data, edc)
        self.assertEqual(result_edc.prepared_request.mode, "edc")
        self.assertEqual(result_edc.prepared_request.response_format["json_schema"]["name"], "edc_extraction")


if __name__ == "__main__":
    unittest.main()
