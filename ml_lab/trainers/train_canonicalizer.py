"""Huấn luyện mô hình Target Alignment (Schema Canonicalizer) trên tập dữ liệu canonicalization_pairs.jsonl."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.integrations.embedder_gateway import (
    BASE_VIETNAMESE_SYNONYMS,
    DEFAULT_EMBED_DIM,
    MODEL_REGISTRY_DIR,
    EmbedderGateway,
    clear_embedder_cache,
)
from shared.text_utils import normal, now_iso, slug, tokenize_vn
from .dataset_io import load_jsonl as _load_jsonl


def train_canonicalizer_model(
    dataset_path: str | Path,
    model_name: str = "aligner-vi-v1",
    *,
    registry_dir: Path | None = None,
) -> dict:
    records = _load_jsonl(Path(dataset_path))
    target_registry = registry_dir or MODEL_REGISTRY_DIR
    target_registry.mkdir(parents=True, exist_ok=True)

    term_weights: dict[str, float] = {}
    synonym_map: dict[str, list[str]] = {k: list(v) for k, v in BASE_VIETNAMESE_SYNONYMS.items()}

    for rec in records:
        open_name = normal(rec.get("open_name", ""))
        canon_name = normal(rec.get("canonical_name", ""))
        if open_name and canon_name and open_name != canon_name:
            s_open = set(synonym_map.get(open_name, []))
            s_open.add(canon_name)
            synonym_map[open_name] = sorted(s_open)

            s_canon = set(synonym_map.get(canon_name, []))
            s_canon.add(open_name)
            synonym_map[canon_name] = sorted(s_canon)

        q_tokens = set(tokenize_vn(rec.get("open_definition", ""), include_bigrams=True))
        c_tokens = set(tokenize_vn(rec.get("canonical_passage", ""), include_bigrams=True))
        for tok in q_tokens & c_tokens:
            term_weights[tok] = min(5.0, term_weights.get(tok, 1.0) * 1.45)

    safe_folder = slug(model_name)
    out_dir = target_registry / safe_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    weights_payload = {"term_weights": term_weights, "synonym_map": synonym_map}
    (out_dir / "hybrid_weights.json").write_text(
        json.dumps(weights_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    model_id = f"registry:{safe_folder}"
    embedder = EmbedderGateway(model_id, registry_dir=target_registry)

    correct = 0
    for rec in records:
        q_vec = embedder.encode(rec["query_text"])
        pos_vec = embedder.encode(rec["canonical_passage"])
        pos_score = float((q_vec * pos_vec).sum())
        neg_scores = [float((q_vec * embedder.encode(neg)).sum()) for neg in rec.get("negative_passages", [])]
        if not neg_scores or pos_score >= max(neg_scores):
            correct += 1

    acc = round(correct / len(records), 4) if records else 1.0
    metadata = {
        "model_id": model_id,
        "name": f"Target Aligner Tiếng Việt ({model_name})",
        "task": "target_alignment",
        "backend": "hybrid_vn",
        "dim": DEFAULT_EMBED_DIM,
        "created_at": now_iso(),
        "training_samples": len(records),
        "learned_synonyms_count": len(synonym_map),
        "metrics": {"alignment_accuracy@1": acc, "samples": len(records)},
        "description": f"Mô hình chuẩn hóa Target Alignment đã học {len(records)} cặp đồng nghĩa (Acc@1={acc:.2f}).",
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    clear_embedder_cache()
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Huấn luyện mô hình Target Alignment")
    parser.add_argument("--dataset", default="data/training_exports/canonicalization_pairs.jsonl")
    parser.add_argument("--model-name", default="aligner-vi-v1")
    args = parser.parse_args()
    report = train_canonicalizer_model(args.dataset, args.model_name)
    print(json.dumps(report, ensure_ascii=False, indent=2))

