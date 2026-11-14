"""Huấn luyện mô hình Schema Retriever (+R) trên tập dữ liệu Active Learning (sr_triplets.jsonl)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from backend.integrations.embedder_gateway import (
    BASE_VIETNAMESE_SYNONYMS,
    DEFAULT_EMBED_DIM,
    MODEL_REGISTRY_DIR,
    EmbedderGateway,
    clear_embedder_cache,
)
from shared.text_utils import normal, now_iso, slug, tokenize_vn
from .dataset_io import load_jsonl as _load_jsonl


def evaluate_retriever_recall(records: list[dict], embedder: EmbedderGateway) -> dict:
    if not records:
        return {"recall@1": 0.0, "recall@3": 0.0, "recall@5": 0.0, "mrr": 0.0, "samples": 0}

    catalog_passages: dict[str, str] = {}
    for r in records:
        if r.get("positive_name") and r.get("positive_passage"):
            catalog_passages[r["positive_name"]] = r["positive_passage"]
        if r.get("negative_name") and r.get("negative_passage"):
            catalog_passages[r["negative_name"]] = r["negative_passage"]

    names = list(catalog_passages.keys())
    passages = [catalog_passages[n] for n in names]
    if not passages:
        return {"recall@1": 0.0, "recall@3": 0.0, "recall@5": 0.0, "mrr": 0.0, "samples": 0}

    cat_vecs = embedder.encode(passages)
    hits_at_1 = 0
    hits_at_3 = 0
    hits_at_5 = 0
    rr_sum = 0.0

    for rec in records:
        q_vec = embedder.encode(rec["query_text"])
        scores = np.dot(cat_vecs, q_vec)
        ranked_idx = np.argsort(-scores)
        ranked_names = [normal(names[int(i)]) for i in ranked_idx]
        target = normal(rec["positive_name"])
        if target in ranked_names:
            rank = ranked_names.index(target) + 1
            rr_sum += 1.0 / rank
            if rank <= 1:
                hits_at_1 += 1
            if rank <= 3:
                hits_at_3 += 1
            if rank <= 5:
                hits_at_5 += 1

    n = len(records)
    return {
        "recall@1": round(hits_at_1 / n, 4),
        "recall@3": round(hits_at_3 / n, 4),
        "recall@5": round(hits_at_5 / n, 4),
        "mrr": round(rr_sum / n, 4),
        "samples": n,
    }


def train_schema_retriever_model(
    dataset_path: str | Path,
    model_name: str = "sr-vi-v1",
    *,
    registry_dir: Path | None = None,
    epochs: int = 3,
    positive_boost: float = 1.35,
    negative_decay: float = 0.78,
) -> dict:
    records = _load_jsonl(Path(dataset_path))
    target_registry = registry_dir or MODEL_REGISTRY_DIR
    target_registry.mkdir(parents=True, exist_ok=True)

    baseline_embedder = EmbedderGateway("hybrid_vn:default", registry_dir=target_registry)
    before_metrics = evaluate_retriever_recall(records, baseline_embedder)

    term_weights: dict[str, float] = {}
    synonym_map: dict[str, list[str]] = {k: list(v) for k, v in BASE_VIETNAMESE_SYNONYMS.items()}

    for _ in range(max(1, epochs)):
        for rec in records:
            q_raw = rec.get("query_text", "")
            if "\nQuery:" in q_raw:
                q_raw = q_raw.split("\nQuery:", 1)[1]
            q_tokens = set(tokenize_vn(q_raw, include_bigrams=True))
            pos_tokens = set(tokenize_vn(rec.get("positive_passage", ""), include_bigrams=True))
            neg_tokens = set(tokenize_vn(rec.get("negative_passage", ""), include_bigrams=True))

            for tok in q_tokens & pos_tokens:
                term_weights[tok] = min(5.0, term_weights.get(tok, 1.0) * positive_boost)

            for tok in (q_tokens & neg_tokens) - pos_tokens:
                term_weights[tok] = max(0.25, term_weights.get(tok, 1.0) * negative_decay)

            pos_name = normal(rec.get("positive_name", ""))
            if pos_name:
                q_bigrams = [t.replace("_", " ") for t in q_tokens if "_" in t]
                if q_bigrams:
                    existing = set(synonym_map.get(pos_name, []))
                    existing.update(q_bigrams[:4])
                    synonym_map[pos_name] = sorted(existing)

    safe_folder = slug(model_name)
    out_dir = target_registry / safe_folder
    out_dir.mkdir(parents=True, exist_ok=True)

    weights_payload = {"term_weights": term_weights, "synonym_map": synonym_map}
    (out_dir / "hybrid_weights.json").write_text(
        json.dumps(weights_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    model_id = f"registry:{safe_folder}"
    trained_embedder = EmbedderGateway(model_id, registry_dir=target_registry)
    after_metrics = evaluate_retriever_recall(records, trained_embedder)

    metadata = {
        "model_id": model_id,
        "name": f"Schema Retriever Tiếng Việt ({model_name})",
        "task": "schema_retriever",
        "backend": "hybrid_vn",
        "dim": DEFAULT_EMBED_DIM,
        "created_at": now_iso(),
        "training_samples": len(records),
        "learned_terms_count": len(term_weights),
        "baseline_metrics": before_metrics,
        "metrics": after_metrics,
        "description": f"Mô hình +R đã huấn luyện trên {len(records)} mẫu (Recall@5={after_metrics['recall@5']:.2f}, MRR={after_metrics['mrr']:.2f}).",
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    clear_embedder_cache()
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Huấn luyện mô hình Schema Retriever (+R)")
    parser.add_argument("--dataset", default="data/training_exports/sr_triplets.jsonl")
    parser.add_argument("--model-name", default="sr-vi-v1")
    args = parser.parse_args()
    report = train_schema_retriever_model(args.dataset, args.model_name)
    print(json.dumps(report, ensure_ascii=False, indent=2))

