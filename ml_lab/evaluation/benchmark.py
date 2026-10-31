"""Đánh giá và so sánh các mô hình Embedding trong Model Registry (Recall@K, MRR)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.integrations.embedder_gateway import MODEL_REGISTRY_DIR, EmbedderGateway, list_registered_models
from ml_lab.trainers.train_schema_retriever import _load_jsonl, evaluate_retriever_recall


def run_retriever_benchmark(
    dataset_path: str | Path,
    *,
    registry_dir: Path | None = None,
) -> list[dict]:
    target_registry = registry_dir or MODEL_REGISTRY_DIR
    records = _load_jsonl(Path(dataset_path))
    models = list_registered_models(target_registry)

    leaderboard: list[dict] = []
    for m in models:
        embedder = EmbedderGateway(m["model_id"], registry_dir=target_registry)
        metrics = evaluate_retriever_recall(records, embedder)
        leaderboard.append(
            {
                "model_id": m["model_id"],
                "name": m["name"],
                "trained": m.get("trained", False),
                "recall@1": metrics["recall@1"],
                "recall@3": metrics["recall@3"],
                "recall@5": metrics["recall@5"],
                "mrr": metrics["mrr"],
                "samples": metrics["samples"],
            }
        )
    leaderboard.sort(key=lambda x: (-x["mrr"], -x["recall@5"]))
    return leaderboard


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Đánh giá Benchmark các mô hình trong Model Registry")
    parser.add_argument("--dataset", default="data/training_exports/sr_triplets.jsonl")
    args = parser.parse_args()
    board = run_retriever_benchmark(args.dataset)
    print(json.dumps(board, ensure_ascii=False, indent=2))

