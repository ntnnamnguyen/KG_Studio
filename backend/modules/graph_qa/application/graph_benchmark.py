"""Run the existing retrieval algorithms against one independent fact benchmark."""
from __future__ import annotations

from itertools import product

from backend.domain.graph.g_retriever import retrieve_subgraph
from shared.schemas.graph_input import GraphBenchmarkItemDTO, GraphSnapshotDTO, graph_fingerprint
from shared.text_utils import normal


def evaluate_graph_benchmark(graph: GraphSnapshotDTO, items: list[dict], *, max_edges: int = 15) -> dict:
    if not items or type(max_edges) is not int or max_edges < 1:
        raise ValueError("Cần tập câu hỏi độc lập không rỗng và ngân sách cạnh dương")
    dataset = [GraphBenchmarkItemDTO.model_validate(item) for item in items]
    if len({item.id for item in dataset}) != len(dataset):
        raise ValueError("Mã câu hỏi bị trùng")
    nodes = {node["id"]: node for node in graph.nodes}
    facts: dict[tuple, set[str]] = {}
    for edge in graph.edges:
        key = (normal(nodes[edge["source"]]["name"]), normal(edge["relation"]), normal(nodes[edge["target"]]["name"]))
        facts.setdefault(key, set()).add(edge["id"])
    matches = {}
    for item in dataset:
        signatures = [set(product(*(map(normal, forms) for forms in (fact.subject, fact.predicate, fact.object))))
                      for fact in item.gold_facts]
        if any(left & right for index, left in enumerate(signatures) for right in signatures[index + 1:]):
            raise ValueError("Các gold facts trong một câu hỏi bị trùng hoặc chồng lấn variants")
        matches[item.id] = [set().union(*(facts.get(key, set()) for key in forms)) for forms in signatures]
    graph_input = graph.as_project()
    rows, details = [], []
    for method in ("naive_topk", "ppr", "pcst"):
        recalls, coverages, times, tokens = [], [], [], []
        for item in dataset:
            result = retrieve_subgraph(graph_input, item.question, method=method, max_edges=max_edges,
                                       approved_only=False)
            retrieved = {edge["id"] for edge in result.edges}
            groups = matches[item.id]
            recall = sum(bool(group & retrieved) for group in groups) / len(groups)
            coverage = sum(bool(group) for group in groups) / len(groups)
            recalls.append(recall)
            coverages.append(coverage)
            times.append(result.latency_ms)
            tokens.append(result.stats.get("estimated_prompt_tokens", 0))
            details.append({"question_id": item.id, "question": item.question, "method": method,
                            "gold_fact_count": len(groups), "retrieved_fact_recall": recall,
                            "graph_fact_coverage": coverage, "retrieved_edge_ids": sorted(retrieved)})
        rows.append({"Phương pháp": method, "Số câu hỏi": len(dataset),
                     "Thu hồi facts chuẩn (%)": round(sum(recalls) / len(dataset) * 100, 2),
                     "Facts có trong graph (%)": round(sum(coverages) / len(dataset) * 100, 2),
                     "Thời gian Truy xuất TB (ms)": round(sum(times) / len(dataset), 3),
                     "Token Ngữ cảnh TB": round(sum(tokens) / len(dataset), 2)})
    return {"format": "kg-studio.graph-benchmark.v1", "graph_fingerprint": graph.fingerprint,
            "graph_source": graph.source, "dataset_fingerprint": graph_fingerprint(items),
            "max_edges": max_edges, "matching": "annotator-supplied-variants + normal-v1",
            "metric": "macro question-level gold-fact retrieval recall; not extraction precision",
            "summary_table": rows, "per_question": details}
