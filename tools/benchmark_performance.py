"""Công cụ đo lường hiệu năng và bộ nhớ chuẩn (Baseline & Post-Optimization Benchmark Harness).
Không phụ thuộc LLM bên ngoài, có thể chạy độc lập để ghi nhận metrics thực tế.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Đảm bảo đường dẫn import
KG_STUDIO_ROOT = Path(__file__).resolve().parent.parent
if str(KG_STUDIO_ROOT) not in sys.path:
    sys.path.insert(0, str(KG_STUDIO_ROOT))

from backend.domain.catalogs.service import proposal_impact
try:
    from backend.domain.catalogs.service import batch_proposal_impacts
except ImportError:
    batch_proposal_impacts = None
from backend.domain.curation.service import (
    duplicate_suggestions,
    evidence_context,
    review_stats,
)
from backend.domain.documents.processor import count_chunks, document_chunks
from backend.facade import get_facade
from backend.integrations.embedder_gateway import default_embedder
from backend.repositories.json_repo import JsonProjectRepository
from backend.repositories.vector_repo import VectorIndexRepository
from shared.config_loader import projects_root
from shared.text_utils import now_iso, sha, uid


def generate_synthetic_project(scale: str = "S") -> dict:
    """Tạo fixture dữ liệu thử nghiệm chuẩn theo quy mô S (nhỏ) hoặc M (vừa)."""
    if scale == "M":
        num_docs = 20
        text_per_doc = 50000  # ~50 KB text per doc
        num_nodes = 500
        num_edges = 2000
        num_proposals = 100
    else:  # S
        num_docs = 3
        text_per_doc = 10000
        num_nodes = 60
        num_edges = 150
        num_proposals = 15

    proj_id = f"bench_proj_{scale.lower()}_{uid()[:8]}"
    project: dict[str, Any] = {
        "project_id": proj_id,
        "name": f"Benchmark Project {scale}",
        "schema_version": "2.0.0",
        "version": "2.0.0",
        "documents": [],
        "nodes": [],
        "edges": [],
        "schema_proposals": [],
        "schema_decisions": [],
        "curation_history": [],
        "entity_merges": [],
        "node_redirects": {},
        "not_duplicate_pairs": [],
        "relations": ["nằm tại", "thuộc", "thờ phụng", "xây dựng vào"],
        "entity_types": [
            {"name": "di tích", "definition": "Công trình di tích lịch sử"},
            {"name": "nhân vật", "definition": "Nhân vật lịch sử"},
            {"name": "địa danh", "definition": "Địa điểm địa lý"},
        ],
    }

    sample_quote = "Đền Bạch Mã tọa lạc tại số 76 phố Hàng Buồm, quận Hoàn Kiếm, Hà Nội, thờ thần Long Đỗ."
    filler_sentence = " Di tích có giá trị lịch sử và văn hóa lâu đời gắn liền với kinh thành Thăng Long."

    for d_idx in range(num_docs):
        doc_id = f"doc_{d_idx + 1}"
        text_body = sample_quote + (filler_sentence * (text_per_doc // len(filler_sentence)))
        project["documents"].append(
            {
                "id": doc_id,
                "name": f"Tài liệu {d_idx + 1}.txt",
                "text": text_body,
                "hash": sha(text_body),
                "chars": len(text_body),
                "pages": [],
                "warnings": [],
            }
        )

    for n_idx in range(num_nodes):
        nid = f"node_{n_idx + 1}"
        kind = "di tích" if n_idx % 3 == 0 else ("nhân vật" if n_idx % 3 == 1 else "địa danh")
        name = f"Thực thể {n_idx + 1}"
        aliases = [f"Bí danh {n_idx + 1}"] if n_idx % 4 == 0 else []
        prop_ids = [f"prop_{n_idx % num_proposals + 1}"] if n_idx % 5 == 0 else []
        project["nodes"].append(
            {
                "id": nid,
                "name": name,
                "kind": kind,
                "aliases": aliases,
                "documents": ["doc_1"],
                "schema_proposal_ids": prop_ids,
            }
        )

    for e_idx in range(num_edges):
        eid = f"edge_{e_idx + 1}"
        src_id = f"node_{(e_idx % num_nodes) + 1}"
        tgt_id = f"node_{((e_idx + 1) % num_nodes) + 1}"
        rel = "nằm tại" if e_idx % 3 == 0 else ("thờ phụng" if e_idx % 3 == 1 else "thuộc")
        status = "approved" if e_idx % 4 == 0 else ("check" if e_idx % 4 == 1 else "pending")
        prop_ids = [f"prop_{(e_idx % num_proposals) + 1}"] if e_idx % 6 == 0 else []
        project["edges"].append(
            {
                "id": eid,
                "source": src_id,
                "target": tgt_id,
                "relation": rel,
                "status": status,
                "evidence": sample_quote,
                "doc_id": "doc_1",
                "start_char": 0,
                "end_char": len(sample_quote),
                "verified_start_char": 0,
                "verified_end_char": len(sample_quote),
                "doc_fingerprint": sha(project["documents"][0]["text"])[:16],
                "schema_proposal_ids": prop_ids,
            }
        )

    for p_idx in range(num_proposals):
        pid = f"prop_{p_idx + 1}"
        kind = "entity_types" if p_idx % 2 == 0 else "relations"
        project["schema_proposals"].append(
            {
                "id": pid,
                "kind": kind,
                "name": f"Đề xuất {p_idx + 1}",
                "status": "pending",
                "observations": [],
            }
        )

    return project


def measure_block(func, repetitions: int = 5) -> dict[str, Any]:
    """Đo thời gian thực thi (p50, p95, mean) và peak memory sử dụng tracemalloc."""
    durations: list[float] = []
    tracemalloc.start()
    mem_before, _ = tracemalloc.get_traced_memory()

    result = None
    for _ in range(repetitions):
        t0 = time.perf_counter()
        result = func()
        t1 = time.perf_counter()
        durations.append(t1 - t0)

    mem_after, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    durations.sort()
    p50 = durations[len(durations) // 2]
    p95_idx = int(len(durations) * 0.95)
    p95 = durations[min(p95_idx, len(durations) - 1)]

    return {
        "repetitions": repetitions,
        "p50_seconds": round(p50, 6),
        "p95_seconds": round(p95, 6),
        "mean_seconds": round(sum(durations) / len(durations), 6),
        "peak_memory_kb": round((peak_mem - mem_before) / 1024, 2),
        "result_sample": str(type(result).__name__),
    }


def run_benchmark_suite(stage: str = "baseline", scale: str = "S") -> dict[str, Any]:
    """Chạy toàn bộ suite đo lường chuẩn."""
    print(f"\n=======================================================")
    print(f"🚀 BẮT ĐẦU CHẠY BENCHMARK [{stage.upper()}] - Quy mô: {scale}")
    print(f"=======================================================")

    repo = JsonProjectRepository()
    project = generate_synthetic_project(scale)

    metrics: dict[str, Any] = {
        "meta": {
            "stage": stage,
            "scale": scale,
            "timestamp": now_iso(),
            "python_version": sys.version,
        },
        "benchmarks": {},
    }

    # 1. Đo list_projects & find_folder
    print("1. Đo list_projects()...")
    metrics["benchmarks"]["list_projects"] = measure_block(lambda: repo.list_projects(), repetitions=10)

    # 2. Đo review_stats
    print("2. Đo review_stats(project)...")
    metrics["benchmarks"]["review_stats"] = measure_block(lambda: review_stats(project), repetitions=5)

    # 3. Đo evidence_context
    test_edge = project["edges"][0]
    print("3. Đo evidence_context()...")
    metrics["benchmarks"]["evidence_context"] = measure_block(lambda: evidence_context(project, test_edge), repetitions=20)

    # 4. Đo duplicate_suggestions
    print("4. Đo duplicate_suggestions()...")
    metrics["benchmarks"]["duplicate_suggestions"] = measure_block(lambda: duplicate_suggestions(project, fuzzy_threshold=0.82), repetitions=3)

    # 5. Đo proposal_impact (5 proposals lặp)
    print("5. Đo proposal_impact()...")
    props = [p["id"] for p in project["schema_proposals"][:10]]
    metrics["benchmarks"]["proposal_impact_10_proposals"] = measure_block(
        lambda: [proposal_impact(project, pid) for pid in props],
        repetitions=5,
    )

    # 6. Đo vector repo ensure_index / search
    print("6. Đo vector_repo ensure_index...")
    vec_repo = VectorIndexRepository()
    embedder = default_embedder("hybrid_vn:default")
    cat_items = project["entity_types"]
    metrics["benchmarks"]["vector_ensure_index"] = measure_block(
        lambda: vec_repo.ensure_index(project["project_id"], "entity_types", cat_items, embedder),
        repetitions=10,
    )

    # In kết quả tóm tắt
    print("\n📊 TỔNG HỢP KẾT QUẢ BENCHMARK:")
    for name, data in metrics["benchmarks"].items():
        print(f"  - {name:<30}: p50={data['p50_seconds']*1000:>8.2f} ms | p95={data['p95_seconds']*1000:>8.2f} ms | Peak RAM={data['peak_memory_kb']:>8.1f} KB")

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KG Studio Performance Benchmark")
    parser.add_argument("--stage", default="baseline", choices=["baseline", "stage_a", "stage_b", "final"])
    parser.add_argument("--scale", default="S", choices=["S", "M"])
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    results = run_benchmark_suite(stage=args.stage, scale=args.scale)

    out_path = Path(args.output) if args.output else (KG_STUDIO_ROOT / "AI" / "report" / f"perf-{args.stage}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Đã lưu kết quả đo vào: {out_path}")
