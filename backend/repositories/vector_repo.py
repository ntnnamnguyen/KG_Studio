"""Kho lưu trữ và truy vấn chỉ mục Vector (Vector Index Repository) cho EDC+R."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from backend.integrations.embedder_gateway import EmbedderGateway
from shared.config_loader import APP_ROOT
from shared.prompt_templates import format_canon_query, format_catalog_passage, format_sr_query
from shared.text_utils import sha

DEFAULT_VECTOR_DIR = APP_ROOT / "data" / "vector_indices"

# Bộ nhớ đệm vector index trong RAM: (project_id, kind, model_fingerprint, catalog_hash) -> (items, vectors)
_INDEX_MEM_CACHE: dict[tuple[str, str, str, str], tuple[list[dict], np.ndarray]] = {}


class VectorIndexRepository:
    def __init__(self, index_root: str | Path | None = None) -> None:
        self.index_root = Path(index_root) if index_root else DEFAULT_VECTOR_DIR
        self.index_root.mkdir(parents=True, exist_ok=True)

    def _catalog_hash(self, items: list[dict]) -> str:
        payload = json.dumps(items, ensure_ascii=False, sort_keys=True)
        return sha(payload)[:16]

    def _index_path(self, project_id: str, kind: str, model_fingerprint: str) -> Path:
        folder = self.index_root / (project_id or "default") / f"model_{model_fingerprint}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{kind}_index.npz"

    def invalidate_project_indices(
        self,
        project_id: str,
        *,
        kind: str | None = None,
        current_catalog_items: list[dict] | None = None,
    ) -> int:
        """Vô hiệu hóa các chỉ mục vector cũ khi danh mục thay đổi hoặc khôi phục snapshot."""
        proj_folder = self.index_root / (project_id or "default")
        if not proj_folder.exists():
            return 0
        expected_hash = self._catalog_hash(current_catalog_items) if current_catalog_items is not None else None
        kinds = [kind] if kind in ("relations", "entity_types") else ["relations", "entity_types"]
        removed = 0
        for model_dir in proj_folder.iterdir():
            if not model_dir.is_dir():
                continue
            for k in kinds:
                idx_file = model_dir / f"{k}_index.npz"
                if not idx_file.exists():
                    continue
                should_remove = True
                if expected_hash is not None:
                    try:
                        with np.load(str(idx_file), allow_pickle=False) as data:
                            if str(data["catalog_hash"]) == expected_hash:
                                should_remove = False
                    except Exception:
                        should_remove = True
                if should_remove:
                    try:
                        idx_file.unlink(missing_ok=True)
                        removed += 1
                    except Exception:
                        pass
        # Xóa các mục tương ứng trong bộ nhớ đệm RAM
        proj_str = str(project_id or "default")
        stale_keys = [k for k in _INDEX_MEM_CACHE if k[0] == proj_str and (kind is None or k[1] == kind)]
        for k in stale_keys:
            _INDEX_MEM_CACHE.pop(k, None)

        return removed

    def get_index_status(
        self,
        project_id: str,
        kind: str,
        catalog_items: list[dict],
        model_fingerprint: str = "",
    ) -> dict[str, Any]:
        """Kiểm tra trạng thái hiệu lực của chỉ mục vector hiện tại theo catalog_hash."""
        cat_hash = self._catalog_hash(catalog_items)
        proj_folder = self.index_root / (project_id or "default")
        if not proj_folder.exists():
            return {"valid": False, "reason": "no_index", "expected_catalog_hash": cat_hash}
        if model_fingerprint:
            idx_path = self._index_path(project_id, kind, model_fingerprint)
            if not idx_path.exists():
                return {"valid": False, "reason": "invalidated_or_missing", "expected_catalog_hash": cat_hash}
            try:
                with np.load(str(idx_path), allow_pickle=False) as data:
                    stored_hash = str(data["catalog_hash"])
                    return {
                        "valid": stored_hash == cat_hash,
                        "stored_catalog_hash": stored_hash,
                        "expected_catalog_hash": cat_hash,
                        "reason": "ok" if stored_hash == cat_hash else "stale_catalog_hash",
                    }
            except Exception as exc:
                return {"valid": False, "reason": str(exc), "expected_catalog_hash": cat_hash}
        for model_dir in proj_folder.iterdir():
            if not model_dir.is_dir():
                continue
            idx_path = model_dir / f"{kind}_index.npz"
            if idx_path.exists():
                try:
                    with np.load(str(idx_path), allow_pickle=False) as data:
                        stored_hash = str(data["catalog_hash"])
                        if stored_hash == cat_hash:
                            return {
                                "valid": True,
                                "stored_catalog_hash": stored_hash,
                                "expected_catalog_hash": cat_hash,
                                "reason": "ok",
                            }
                except Exception:
                    pass
        return {"valid": False, "reason": "stale_or_missing", "expected_catalog_hash": cat_hash}

    def ensure_index(
        self,
        project_id: str,
        kind: str,
        catalog_items: list[dict],
        embedder: EmbedderGateway,
    ) -> tuple[list[dict], np.ndarray]:
        if not catalog_items:
            return [], np.zeros((0, embedder.dim), dtype=np.float32)

        cat_hash = self._catalog_hash(catalog_items)
        proj_str = str(project_id or "default")
        cache_key = (proj_str, kind, str(embedder.fingerprint), cat_hash)

        # 1. Kiểm tra RAM cache trước
        if cache_key in _INDEX_MEM_CACHE:
            return _INDEX_MEM_CACHE[cache_key]

        path = self._index_path(project_id, kind, embedder.fingerprint)

        if path.exists():
            try:
                with np.load(str(path), allow_pickle=False) as data:
                    stored_hash = str(data["catalog_hash"])
                    if stored_hash == cat_hash:
                        items = json.loads(str(data["items_json"]))
                        vectors = np.asarray(data["vectors"], dtype=np.float32)
                        if len(items) == vectors.shape[0]:
                            _INDEX_MEM_CACHE[cache_key] = (items, vectors)
                            return items, vectors
            except Exception:
                pass

        passages = [
            format_catalog_passage(
                row.get("name", ""),
                row.get("definition", ""),
                row.get("description", ""),
            )
            for row in catalog_items
        ]
        vectors = embedder.encode(passages)
        np.savez_compressed(
            str(path),
            catalog_hash=np.array(cat_hash),
            items_json=np.array(json.dumps(catalog_items, ensure_ascii=False)),
            vectors=vectors,
        )
        _INDEX_MEM_CACHE[cache_key] = (catalog_items, vectors)
        return catalog_items, vectors

    def search(
        self,
        project_id: str,
        kind: str,
        catalog_items: list[dict],
        query_text: str,
        embedder: EmbedderGateway,
        *,
        mode: str = "sr",
        open_definition: str = "",
        top_k: int = 10,
    ) -> list[dict]:
        items, matrix = self.ensure_index(project_id, kind, catalog_items, embedder)
        if not items or matrix.shape[0] == 0:
            return []

        if mode == "sr":
            formatted_query = format_sr_query(query_text)
        elif mode == "canon":
            formatted_query = format_canon_query(query_text, open_definition)
        else:
            formatted_query = query_text

        query_vec = embedder.encode(formatted_query)
        scores = np.dot(matrix, query_vec)
        k = max(1, min(int(top_k), len(items)))
        ranked_indices = np.argsort(-scores)[:k]

        results: list[dict] = []
        for idx in ranked_indices:
            item = dict(items[int(idx)])
            item["score"] = round(float(scores[int(idx)]), 4)
            results.append(item)
        return results
