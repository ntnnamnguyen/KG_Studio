"""Application Service cho phân hệ Graph QA, Subgraph Retrieval & Export."""
from __future__ import annotations

import copy
import json
from typing import Any

from backend.domain.graph.g_retriever import (
    SubgraphRetrievalResult,
    answer_question_with_graph,
    evaluate_retrieval_methods,
    load_project_from_export_bytes,
    retrieve_subgraph,
)
from backend.domain.graph.qa_generator import (
    generate_qa_benchmark,
    generate_training_qa_dataset,
    paraphrase_qa_questions_with_llm,
)
from backend.domain.graph.service import (
    approved_graph,
    approved_json_bytes,
    csv_bytes,
    export_zip,
    validate_integrity,
)
from ..domain.baseline_graph import build_baseline_graph
from ..ports import BaselineRunSourcePort, Neo4jPort
from shared.schemas.graph_input import BaselineGraphRequestDTO, GraphSnapshotDTO, graph_fingerprint
from shared.secrets_manager import get_api_key


class GraphQAApplicationService:
    """Dịch vụ ứng dụng quản lý Đồ thị tri thức, G-Retriever Subgraph, QA Generator và Xuất Neo4j/Files."""

    def __init__(self, *, neo4j_gateway: Neo4jPort | None = None,
                 baseline_source: BaselineRunSourcePort | None = None) -> None:
        self.neo4j_gateway = neo4j_gateway
        self.baseline_source = baseline_source

    def baseline_run_options(self, project: dict) -> list[dict]:
        if self.baseline_source is None:
            raise RuntimeError("Baseline run source chưa được inject tại composition root")
        bundle = self.baseline_source.read_free_triples_runs(project)
        return [{key: run.get(key) for key in ("run_id", "doc_id", "doc_name", "chunk_number", "chunk_hash", "status", "at")}
                for run in bundle["runs"]]

    def build_baseline_graph(self, project: dict, request: BaselineGraphRequestDTO | dict) -> GraphSnapshotDTO:
        req = BaselineGraphRequestDTO.from_dict(request)
        pid = str(project.get("project_id") or project.get("name") or "")
        if req.project_id != pid:
            raise ValueError("Yêu cầu dựng graph không thuộc project hiện tại")
        if self.baseline_source is None:
            raise RuntimeError("Baseline run source chưa được inject tại composition root")
        bundle = self.baseline_source.read_free_triples_runs(project, req.run_ids)
        if bundle["project_id"] != pid or {run["run_id"] for run in bundle["runs"]} != set(req.run_ids):
            raise ValueError("Nguồn baseline trả sai project")
        return build_baseline_graph(bundle)

    def graph_snapshot(self, project: dict, *, source: str = "approved") -> GraphSnapshotDTO:
        """Select a graph explicitly; approved never falls back to all edges."""
        if source == "approved":
            nodes, edges = approved_graph(project)
        elif source == "all":
            nodes, edges = project.get("nodes", []), project.get("edges", [])
        else:
            raise ValueError("Dùng build_baseline_graph cho nguồn baseline")
        return GraphSnapshotDTO(
            project_id=str(project.get("project_id") or project.get("name") or ("graph_" + graph_fingerprint([nodes, edges]))),
            name=str(project.get("name", "")), source=source,
            nodes=copy.deepcopy(nodes), edges=copy.deepcopy(edges),
            manifest={"selection": source, "extraction_mode": project.get("extraction_mode", "unknown")},
        )

    def export_graph_json(self, graph: GraphSnapshotDTO | dict) -> bytes:
        snapshot = GraphSnapshotDTO.model_validate(graph.to_dict() if isinstance(graph, GraphSnapshotDTO) else graph)
        return json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")

    def import_graph_json(self, raw: bytes) -> GraphSnapshotDTO:
        return GraphSnapshotDTO.from_dict(json.loads(raw.decode("utf-8-sig")))

    def evaluate_graph_benchmark(self, graph: GraphSnapshotDTO | dict, items: list[dict], *, max_edges: int = 15) -> dict:
        from .graph_benchmark import evaluate_graph_benchmark
        snapshot = GraphSnapshotDTO.model_validate(graph.to_dict()) if isinstance(graph, GraphSnapshotDTO) else GraphSnapshotDTO.from_graph_input(graph)
        return evaluate_graph_benchmark(snapshot, items, max_edges=max_edges)

    # --- Graph Integrity & Export ---

    def validate_integrity(self, project: dict) -> list[str]:
        return validate_integrity(project)

    def approved_graph(self, project: dict) -> tuple[list[dict], list[dict]]:
        return approved_graph(project)

    def approved_json_bytes(self, project: dict) -> bytes:
        return approved_json_bytes(project)

    def csv_bytes(self, records: list[dict], headers: list[str], list_fields: tuple[str, ...] = ()) -> bytes:
        return csv_bytes(records, headers, list_fields)

    def export_zip(self, project: dict, *, qa_max_samples: int = 2000) -> bytes:
        return export_zip(project, qa_max_samples=qa_max_samples)

    def sync_neo4j(
        self,
        project: dict,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver: Any = None,
    ) -> dict:
        if self.neo4j_gateway is None:
            raise RuntimeError("Neo4j Gateway chưa được inject vào GraphQAApplicationService")
        sync_payload = project
        if project.get("documents"):
            nodes, edges = approved_graph(project)
            sync_payload = {
                **project,
                "nodes": nodes,
                "edges": edges,
            }
        return self.neo4j_gateway.sync_project(sync_payload, uri, user, password, database, driver=driver)

    def test_neo4j(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver: Any = None,
    ) -> tuple[bool, str]:
        if self.neo4j_gateway is None:
            raise RuntimeError("Neo4j Gateway chưa được inject vào GraphQAApplicationService")
        return self.neo4j_gateway.test_connection(uri, user, password, database, driver=driver)

    # --- G-Retriever & Question Answering ---

    def retrieve_subgraph(
        self,
        project: dict,
        query: str,
        *,
        method: str = "pcst",
        max_edges: int = 20,
        approved_only: bool = True,
        base_edge_cost: float = 0.35,
        hub_penalty_alpha: float = 0.45,
        expand_leaf_attributes: bool = True,
    ) -> SubgraphRetrievalResult:
        return retrieve_subgraph(
            project,
            query,
            method=method,
            max_edges=max_edges,
            approved_only=approved_only,
            base_edge_cost=base_edge_cost,
            hub_penalty_alpha=hub_penalty_alpha,
            expand_leaf_attributes=expand_leaf_attributes,
        )

    def answer_question_with_graph(
        self,
        subgraph_or_project: SubgraphRetrievalResult | dict[str, Any],
        query: str = "",
        *,
        method: str = "pcst",
        approved_only: bool = True,
        max_edges: int = 18,
        provider: str = "DeepSeek",
        api_key: str = "",
        model: str = "deepseek-chat",
        base_url: str = "",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        max_input_tokens: int = 16000,
        max_output_tokens: int = 2048,
        client: Any = None,
        llm_client: Any = None,
        domain_topic: str = "",
    ) -> dict[str, Any]:
        effective_key = (api_key or "").strip() or get_api_key(provider)
        return answer_question_with_graph(
            subgraph_or_project,
            query,
            method=method,
            approved_only=approved_only,
            max_edges=max_edges,
            provider=provider,
            api_key=effective_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            client=client,
            llm_client=llm_client,
            domain_topic=domain_topic,
        )

    def generate_qa_benchmark(
        self,
        project: dict,
        *,
        num_questions: int = 18,
        approved_only: bool = True,
    ) -> list[dict[str, Any]]:
        return generate_qa_benchmark(project, num_questions=num_questions, approved_only=approved_only)

    def generate_training_qa_dataset(
        self,
        project: dict,
        *,
        max_samples: int = 2000,
        train_ratio: float = 0.80,
        val_ratio: float = 0.10,
        approved_only: bool = True,
        disjoint_split: bool = True,
    ) -> dict[str, Any]:
        return generate_training_qa_dataset(
            project,
            max_samples=max_samples,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            approved_only=approved_only,
            disjoint_split=disjoint_split,
        )

    def paraphrase_qa_questions_with_llm(
        self,
        items: list[dict[str, Any]],
        *,
        provider: str = "DeepSeek",
        api_key: str = "",
        model: str = "deepseek-chat",
        base_url: str = "",
        client: Any = None,
        batch_size: int = 10,
    ) -> list[dict[str, Any]]:
        effective_key = (api_key or "").strip() or get_api_key(provider)
        return paraphrase_qa_questions_with_llm(
            items,
            provider=provider,
            api_key=effective_key,
            model=model,
            base_url=base_url,
            client=client,
            batch_size=batch_size,
        )

    def evaluate_retrieval_methods(
        self,
        project: dict,
        benchmark_items: list[dict[str, Any]] | None = None,
        *,
        max_edges: int = 15,
        approved_only: bool = True,
    ) -> dict[str, Any]:
        return evaluate_retrieval_methods(
            project,
            benchmark_items=benchmark_items,
            max_edges=max_edges,
            approved_only=approved_only,
        )

    def load_project_from_export_bytes(self, raw_bytes: bytes, filename: str = "") -> dict[str, Any]:
        return load_project_from_export_bytes(raw_bytes, filename=filename)

    def build_kgqa_training_bundle(
        self,
        project: dict,
        *,
        approved_only: bool = True,
        max_samples: int = 500,
    ) -> dict[str, Any]:
        """Sinh Bộ dữ liệu Huấn luyện Chuẩn G-Retriever 5 tệp (nodes/edges/evidence/questions/schema_contract)."""
        from backend.domain.graph.kgqa_bundle import build_kgqa_training_bundle

        return build_kgqa_training_bundle(
            project,
            approved_only=approved_only,
            max_samples=max_samples,
        )

    def paraphrase_kgqa_training_bundle(
        self,
        bundle: dict[str, Any],
        *,
        provider: str = "DeepSeek",
        api_key: str = "",
        model: str = "deepseek-chat",
        base_url: str = "",
        client: Any = None,
        batch_size: int = 10,
        max_items: int | None = None,
        only_unparaphrased: bool = True,
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Paraphrase các câu hỏi trong bộ dữ liệu G-Retriever bằng LLM với hậu kiểm giữ thực thể & chống lộ đáp án."""
        from backend.domain.graph.kgqa_bundle import apply_paraphrased_kgqa_results

        records = list(bundle.get("question_records") or [])
        candidates = [
            {
                "id": rec["question_id"],
                "question": rec["question"],
                "original_question": rec.get("original_question") or rec["question"],
            }
            for rec in records
            if not only_unparaphrased or str(rec.get("review_status", "")) != "llm_paraphrased"
        ]
        if max_items is not None and int(max_items) >= 0:
            candidates = candidates[: int(max_items)]

        if not candidates:
            return bundle, {
                "attempted": 0,
                "accepted": 0,
                "rejected_entity_drop": 0,
                "rejected_answer_leak": 0,
                "rejected_robotic": 0,
                "rejected_unchanged": 0,
                "rejected_duplicate": 0,
            }

        paraphrased_items = paraphrase_qa_questions_with_llm(
            candidates,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
            client=client,
            batch_size=batch_size,
        )
        return apply_paraphrased_kgqa_results(bundle, paraphrased_items)
