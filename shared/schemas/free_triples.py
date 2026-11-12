"""Structural contract for the raw, domain-schema-free extraction baseline.

Validation annotates the original payload; it never rewrites labels, merges facts,
filters unsupported predicates, or drops malformed items from experiment evidence.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

TRIPLE_FIELDS = ("subject", "predicate", "object", "evidence")
FREE_TRIPLES_SCHEMA = {
    "type": "object",
    "properties": {
        "triples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {key: {"type": "string"} for key in TRIPLE_FIELDS},
                "required": list(TRIPLE_FIELDS),
                "additionalProperties": False,
            },
        },
    },
    "required": ["triples"],
    "additionalProperties": False,
}


def free_triples_prompt(base_instructions: str) -> str:
    """Append only an output format, never a vocabulary of domain relations."""
    return (
        base_instructions.strip()
        + '\n\nCẤU TRÚC JSON (định dạng dữ liệu, không phải schema miền):\n'
        + '{"triples": [{"subject": "...", "predicate": "...", "object": "...", "evidence": "..."}]}\n'
        + 'Chỉ có trường triples; mỗi mục dùng đúng bốn chuỗi trên. Không thêm giải thích hoặc định nghĩa.'
    )


def parse_free_triples_json(raw: str) -> dict[str, Any]:
    """Parse the entire response, tolerating only a single enclosing code fence.

Invalid individual items remain in ``triples`` and receive diagnostics later.
Trailing prose/objects, NaN and duplicate JSON keys are rejected rather than repaired.
"""
    text = (raw or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1)

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Khóa JSON bị lặp: {key}")
            result[key] = value
        return result

    def invalid_number(value: str) -> None:
        raise ValueError(f"Giá trị không thuộc JSON chuẩn: {value}")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Số JSON vượt phạm vi hữu hạn; giữ raw response trong lượt lỗi")
        return number

    try:
        payload = json.loads(
            text, object_pairs_hook=unique_object, parse_constant=invalid_number,
            parse_float=finite_float,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"Baseline cần một JSON object hoàn chỉnh: {exc.msg}") from exc
    if not isinstance(payload, dict) or set(payload) != {"triples"} or not isinstance(payload["triples"], list):
        raise ValueError("Baseline cần đúng một trường triples là mảng JSON")
    return payload


def validate_free_triples(payload: dict[str, Any], chunk: str | None) -> dict[str, Any]:
    """Report structural/evidence issues against the actual text sent to the model.

``valid_triples`` means structurally valid, NOT historically/factually correct.
Evidence mismatch and duplicates remain in the original payload for fair evaluation.
``chunk=None`` means input unavailable: evidence is unknown, not a mismatch.
"""
    triples = payload["triples"]
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    valid = mismatches = duplicates = 0
    for index, triple in enumerate(triples, 1):
        issues: list[str] = []
        structurally_valid = isinstance(triple, dict)
        if not structurally_valid:
            issues.append("Triple phải là JSON object")
        else:
            if set(triple) != set(TRIPLE_FIELDS):
                issues.append("Triple cần đúng subject, predicate, object, evidence")
            for key in TRIPLE_FIELDS:
                value = triple.get(key)
                if not isinstance(value, str) or not value.strip():
                    issues.append(f"{key} phải là chuỗi không rỗng")
            structurally_valid = not issues
        evidence_found = None
        if structurally_valid:
            valid += 1
            evidence_found = triple["evidence"] in chunk if chunk is not None else None
            if evidence_found is False:
                mismatches += 1
                issues.append("Trích dẫn không xuất hiện nguyên văn trong input thực gửi")
            elif evidence_found is None:
                issues.append("Thiếu input thực gửi để kiểm tra bằng chứng")
            signature = json.dumps(triple, ensure_ascii=False, sort_keys=True)
            if signature in seen:
                duplicates += 1
                issues.append("Triple lặp nguyên bản (được giữ lại)")
            seen.add(signature)
        items.append({
            "index": index,
            "structurally_valid": structurally_valid,
            "evidence_found": evidence_found,
            "issues": issues,
        })
    return {
        "total_triples": len(triples),
        "valid_triples": valid,
        "invalid_triples": len(triples) - valid,
        "evidence_mismatch": mismatches,
        "duplicate_triples": duplicates,
        "items": items,
    }
