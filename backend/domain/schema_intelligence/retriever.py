"""Bộ Truy xuất Danh mục Đích — Schema Retriever (+R) cho phiên bản EDC + R."""
from __future__ import annotations

from backend.integrations.embedder_gateway import EmbedderGateway, default_embedder
from backend.repositories.vector_repo import VectorIndexRepository
from shared.catalog_utils import relation_catalog
from shared.text_utils import normal


class SchemaRetriever:
    """Truy xuất Top-K quan hệ và loại thực thể phù hợp nhất với đoạn văn cần trích xuất."""

    def __init__(
        self,
        vector_repo: VectorIndexRepository | None = None,
        embedder: EmbedderGateway | None = None,
    ) -> None:
        self.vector_repo = vector_repo or VectorIndexRepository()
        self.embedder = embedder or default_embedder()

    def retrieve_for_chunk(
        self,
        project: dict,
        chunk_text: str,
        *,
        top_k_relations: int = 10,
        top_k_entity_types: int = 8,
        extracted_relation_hints: list[str] | None = None,
        embedder: EmbedderGateway | None = None,
    ) -> dict[str, list[dict]]:
        active_embedder = embedder or self.embedder
        project_id = str(project.get("project_id") or "default")
        rel_catalog = relation_catalog(project)
        type_catalog = project.get("entity_types", [])

        hints_str = ", ".join(h for h in (extracted_relation_hints or []) if str(h).strip())
        query = f"{chunk_text}\nQuan hệ gợi ý: {hints_str}" if hints_str else chunk_text

        rel_hits = self.vector_repo.search(
            project_id,
            "relations",
            rel_catalog,
            query,
            active_embedder,
            mode="sr",
            top_k=top_k_relations,
        )
        type_hits = self.vector_repo.search(
            project_id,
            "entity_types",
            type_catalog,
            query,
            active_embedder,
            mode="sr",
            top_k=top_k_entity_types,
        )

        if extracted_relation_hints:
            seen_names = {normal(item["name"]) for item in rel_hits}
            rel_by_norm = {normal(item["name"]): item for item in rel_catalog}
            for hint in extracted_relation_hints:
                key = normal(hint)
                if key in rel_by_norm and key not in seen_names:
                    entry = dict(rel_by_norm[key])
                    entry["score"] = 1.0
                    rel_hits.insert(0, entry)
                    seen_names.add(key)

        return {
            "relations": rel_hits[: max(1, top_k_relations)],
            "entity_types": type_hits[: max(1, top_k_entity_types)],
        }

    @staticmethod
    def format_retrieved_schema_block(
        retrieved: dict[str, list[dict]],
        *,
        entity_hints: list[str] | None = None,
    ) -> str:
        lines: list[str] = []
        relations = retrieved.get("relations", [])
        entity_types = retrieved.get("entity_types", [])

        if relations:
            lines.append("GỢI Ý QUAN HỆ CHUẨN LIÊN QUAN ĐẾN ĐOẠN VĂN (Ưu tiên dùng tên chuẩn nếu đúng nghĩa, hoặc tự đề xuất tên mới nếu chưa có):")
            for r in relations:
                defn = r.get("definition") or r.get("description") or ""
                lines.append(f"- {r['name']}: {defn}")

        if entity_types:
            lines.append("\nGỢI Ý LOẠI THỰC THỂ CHUẨN LIÊN QUAN:")
            for t in entity_types:
                defn = t.get("definition") or t.get("description") or ""
                lines.append(f"- {t['name']}: {defn}")

        if entity_hints:
            clean_hints = [str(h).strip() for h in entity_hints if str(h).strip()]
            if clean_hints:
                lines.append(
                    "\nTHỰC THỂ ĐÃ NHẬN DIỆN Ở VÒNG TRƯỚC (Hãy kiểm tra kỹ các mối quan hệ còn sót giữa chúng): "
                    + ", ".join(dict.fromkeys(clean_hints))
                )

        return "\n".join(lines).strip()

