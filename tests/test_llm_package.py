"""Kiểm thử gói backend.integrations.llm sau tái cấu trúc (không gọi mạng)."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from backend.integrations.llm import (
    PROVIDER_ANTHROPIC,
    PROVIDER_DEEPSEEK,
    PROVIDER_OLLAMA,
    LLMError,
    LLMGateway,
    classify_error,
    clean_llm_json,
)
from backend.integrations.llm.parsing import pick_choice_letter
from backend.integrations.llm.token_budget import clamp_output_tokens, fit_chunk_to_input_budget


def _openai_answer(content: str, finish: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
    )


class _FakeOpenAI:
    def __init__(self, content: str, *, finish: str = "stop", reject_format: bool = False) -> None:
        self.calls: list[dict] = []
        self._content = content
        self._finish = finish
        self._reject = reject_format
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._reject and "response_format" in kwargs:
            raise RuntimeError("response_format json_schema is not supported")
        return _openai_answer(self._content, self._finish)


class _FakeAnthropic:
    def __init__(self, content: str) -> None:
        self.calls: list[dict] = []
        self._content = content
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._content)],
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
            stop_reason="end_turn",
        )


EMPTY = json.dumps({"thuc_the": [], "quan_he": []})


class LLMPackageTests(unittest.TestCase):
    def test_parsing_and_error_classification(self) -> None:
        self.assertEqual(clean_llm_json("```json\n" + EMPTY + "\n```"), {"thuc_the": [], "quan_he": []})
        self.assertEqual(clean_llm_json("Kết quả: " + EMPTY + " xong"), {"thuc_the": [], "quan_he": []})
        with self.assertRaises(ValueError):
            clean_llm_json('{"a": 1}')
        self.assertEqual(classify_error(RuntimeError("401 Unauthorized")).kind, "auth")
        self.assertEqual(classify_error(RuntimeError("model foo does not exist")).kind, "model")
        self.assertEqual(classify_error(RuntimeError("429 rate limit")).kind, "rate_limit")
        self.assertEqual(pick_choice_letter("Đáp án: B", ["A", "B"]), "B")
        self.assertIsNone(pick_choice_letter("không rõ", ["A", "B"]))

    def test_token_budget_helpers(self) -> None:
        chunk, warn = fit_chunk_to_input_budget("x" * 10000, "", 1024)
        self.assertLess(len(chunk), 10000)
        self.assertIsNotNone(warn)
        self.assertEqual(fit_chunk_to_input_budget("abc", "", 0), ("abc", None))
        value, warn = clamp_output_tokens(PROVIDER_DEEPSEEK, "deepseek-chat", 32000)
        self.assertEqual(value, 16384)
        self.assertIsNotNone(warn)

    def test_extract_deepseek_disables_thinking_and_sanitizes_base_url(self) -> None:
        fake = _FakeOpenAI(EMPTY)
        res = LLMGateway.extract(
            PROVIDER_DEEPSEEK, "key123", "deepseek-flash", "SYS", "Đoạn", [],
            base_url="https://api.deepseek.com/chat/completions", client=fake, max_tokens=1024
        )
        self.assertEqual(res.data, {"thuc_the": [], "quan_he": []})
        self.assertEqual(fake.calls[0]["reasoning_effort"], "none")
        self.assertEqual(fake.calls[0]["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertEqual(fake.calls[0]["messages"][0], {"role": "system", "content": "SYS"})

    def test_extract_openai_compatible_with_format_fallback_and_ollama_reasoning(self) -> None:
        fake = _FakeOpenAI(EMPTY, reject_format=True)
        res = LLMGateway.extract(PROVIDER_OLLAMA, "", "qwen3.5:latest", "SYS", "Đoạn", [], client=fake, max_tokens=512)
        self.assertEqual(res.data, {"thuc_the": [], "quan_he": []})
        self.assertEqual((res.input_tokens, res.output_tokens), (11, 7))
        self.assertTrue(any("response_format" in w for w in res.warnings))
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0]["reasoning_effort"], "none")
        self.assertEqual(fake.calls[0]["messages"][0], {"role": "system", "content": "SYS"})

    def test_extract_truncated_and_missing_key(self) -> None:
        with self.assertRaises(LLMError) as ctx:
            LLMGateway.extract(PROVIDER_DEEPSEEK, "k", "deepseek-chat", "S", "c", [], client=_FakeOpenAI("{", finish="length"))
        self.assertEqual(ctx.exception.kind, "token_limit")
        with self.assertRaises(LLMError) as ctx2:
            LLMGateway.extract(PROVIDER_DEEPSEEK, "", "deepseek-chat", "S", "c", [])
        self.assertEqual(ctx2.exception.kind, "auth")

    def test_extract_anthropic_and_verify_choice(self) -> None:
        fake = _FakeAnthropic(EMPTY)
        res = LLMGateway.extract(PROVIDER_ANTHROPIC, "k", "claude-3-5-sonnet-latest", "SYS", "c", ["nằm tại"], client=fake)
        self.assertEqual(res.output_tokens, 3)
        self.assertEqual(fake.calls[0]["system"], "SYS")
        self.assertNotIn("response_format", fake.calls[0])

        letter = LLMGateway.verify_alignment_choice(
            PROVIDER_DEEPSEEK, "k", "deepseek-chat", "Chọn A hoặc B", ["A", "B"], client=_FakeOpenAI("A")
        )
        self.assertEqual(letter, "A")


if __name__ == "__main__":
    unittest.main()

