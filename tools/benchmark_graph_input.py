"""Synthetic graph-input benchmark. No repositories, provider calls or project data."""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.domain.graph.g_retriever import _INDEX_CACHE, get_or_build_graph_index


def main() -> None:
    graph = {
        "project_id": "synthetic-cache-benchmark", "saved_at": "fixed",
        "nodes": [{"id": f"n{i}", "name": f"Place {i}"} for i in range(400)],
        "edges": [{"id": f"e{i}", "source": f"n{i % 400}", "target": f"n{(i + 1) % 400}",
                   "relation": "located in", "evidence": f"Place {i % 400} located in Place {(i + 1) % 400}"}
                  for i in range(800)],
    }
    _INDEX_CACHE.clear()
    tracing = "--no-trace" not in sys.argv
    if tracing:
        tracemalloc.start()
    start = time.perf_counter()
    get_or_build_graph_index(graph, approved_only=False)
    cold_ms = (time.perf_counter() - start) * 1000
    times = []
    for _ in range(41):
        start = time.perf_counter()
        get_or_build_graph_index(graph, approved_only=False)
        times.append((time.perf_counter() - start) * 1000)
    peak = tracemalloc.get_traced_memory()[1] if tracing else None
    if tracing:
        tracemalloc.stop()
    print(json.dumps({"python": sys.version.split()[0], "nodes": 400, "edges": 800,
                      "samples": len(times), "tracemalloc": tracing, "cold_ms": cold_ms,
                      "warm_median_ms": statistics.median(times),
                      "warm_p95_ms": sorted(times)[int(len(times) * .95)],
                      "peak_bytes": peak}, indent=2))


if __name__ == "__main__":
    main()
