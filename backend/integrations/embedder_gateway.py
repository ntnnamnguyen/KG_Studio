"""Cổng kết nối mô hình Nhúng (Embedding Gateway) cho Schema Retriever (+R) và Target Alignment."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from shared.config_loader import APP_ROOT
from shared.text_utils import normal, sha, tokenize_vn

MODEL_REGISTRY_DIR = APP_ROOT / "data" / "model_registry"
DEFAULT_EMBED_DIM = 1024

BASE_VIETNAMESE_SYNONYMS: dict[str, list[str]] = {
    "tọa lạc": ["nằm tại", "vị trí", "địa điểm", "ở tại", "thuộc địa phận"],
    "nằm ở": ["nằm tại", "tọa lạc", "vị trí", "thuộc"],
    "nằm tại": ["tọa lạc", "nằm ở", "vị trí", "đặt tại", "địa chỉ"],
    "đặt tại": ["nằm tại", "tọa lạc", "vị trí"],
    "thờ": ["thờ phụng", "phối thờ", "tưởng niệm", "tôn thờ", "thờ cúng"],
    "thờ phụng": ["thờ", "phối thờ", "tôn thờ"],
    "xây dựng": ["khởi công", "kiến tạo", "dựng năm", "xây năm", "thành lập"],
    "trùng tu": ["tu bổ", "tôn tạo", "sửa chữa", "cải tạo", "phục dựng"],
    "tu bổ": ["trùng tu", "tôn tạo", "sửa chữa"],
    "công nhận": ["xếp hạng", "danh hiệu", "di tích quốc gia"],
    "xếp hạng": ["công nhận", "di tích", "cấp quốc gia"],
    "giáp": ["tiếp giáp", "giáp ranh", "kề bên", "gần"],
    "thuộc": ["trực thuộc", "nằm trong", "là một phần của", "bao gồm"],
}


def list_registered_models(registry_dir: Path | None = None) -> list[dict]:
    folder = registry_dir or MODEL_REGISTRY_DIR
    models = [
        {
            "model_id": "hybrid_vn:default",
            "name": "Hybrid Vietnamese Semantic N-Gram (Offline mặc định)",
            "backend": "hybrid_vn",
            "dim": DEFAULT_EMBED_DIM,
            "trained": False,
            "description": "Bộ nhúng ngữ nghĩa & từ vựng tiếng Việt tốc độ cao, không cần GPU.",
        },
        {
            "model_id": "ollama:bge-m3",
            "name": "BAAI BGE-M3 (Ollama Multilingual SOTA)",
            "backend": "openai_compatible",
            "dim": 1024,
            "trained": True,
            "description": "Mô hình nhúng đa ngôn ngữ BAAI BGE-M3 chạy qua Ollama (yêu cầu 'ollama pull bge-m3').",
        },
    ]
    if folder.is_dir():
        for child in sorted(folder.iterdir()):
            if not child.is_dir():
                continue
            meta_file = child / "metadata.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    models.append(
                        {
                            "model_id": meta.get("model_id", f"registry:{child.name}"),
                            "name": meta.get("name", child.name),
                            "backend": meta.get("backend", "hybrid_vn"),
                            "path": str(child),
                            "dim": int(meta.get("dim", DEFAULT_EMBED_DIM)),
                            "trained": True,
                            "metrics": meta.get("metrics", {}),
                            "created_at": meta.get("created_at", ""),
                            "description": meta.get("description", f"Mô hình đã huấn luyện tại {child.name}"),
                        }
                    )
                except (OSError, ValueError):
                    continue
    return models


class EmbedderGateway:
    """Cổng tính toán vector embedding thống nhất cho văn bản và định nghĩa danh mục."""

    def __init__(
        self,
        model_id: str = "hybrid_vn:default",
        *,
        backend: str = "auto",
        dim: int = DEFAULT_EMBED_DIM,
        api_key: str = "",
        base_url: str = "",
        registry_dir: Path | None = None,
    ) -> None:
        self.model_id = (model_id or "hybrid_vn:default").strip()
        self.registry_dir = registry_dir or MODEL_REGISTRY_DIR
        if self.model_id.startswith("ollama:bge-m3") and dim == DEFAULT_EMBED_DIM:
            self.dim = 1024
        else:
            self.dim = dim
        self.api_key = api_key
        if self.model_id.startswith("ollama:") and not base_url:
            self.base_url = "http://localhost:11434/v1"
        else:
            self.base_url = base_url
        self.term_weights: dict[str, float] = {}
        self.synonym_map: dict[str, list[str]] = {k: list(v) for k, v in BASE_VIETNAMESE_SYNONYMS.items()}
        self._st_model = None

        if backend == "auto":
            if self.model_id.startswith("hybrid_vn:") or self.model_id.startswith("registry:"):
                self.backend = "hybrid_vn"
            elif self.model_id.startswith("openai:") or self.model_id.startswith("ollama:"):
                self.backend = "openai_compatible"
            else:
                self.backend = "sentence_transformers"
        else:
            self.backend = backend

        self._load_registry_artifact_if_present()

    def _load_registry_artifact_if_present(self) -> None:
        folder_name = self.model_id.split(":", 1)[-1]
        candidate_dir = self.registry_dir / folder_name
        if not candidate_dir.is_dir():
            return
        meta_file = candidate_dir / "metadata.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                self.dim = int(meta.get("dim", self.dim))
                if meta.get("backend") == "sentence_transformers" and (candidate_dir / "config.json").exists():
                    self.backend = "sentence_transformers"
                    self.model_id = str(candidate_dir)
                    return
            except (OSError, ValueError):
                pass
        weights_file = candidate_dir / "hybrid_weights.json"
        if weights_file.exists():
            try:
                payload = json.loads(weights_file.read_text(encoding="utf-8"))
                if isinstance(payload.get("term_weights"), dict):
                    self.term_weights = {str(k): float(v) for k, v in payload["term_weights"].items()}
                if isinstance(payload.get("synonym_map"), dict):
                    for key, values in payload["synonym_map"].items():
                        existing = set(self.synonym_map.get(key, []))
                        existing.update(str(v) for v in values)
                        self.synonym_map[str(key)] = sorted(existing)
            except (OSError, ValueError):
                pass

    @property
    def fingerprint(self) -> str:
        weight_sig = sha(
            json.dumps(
                {"w": self.term_weights, "s": self.synonym_map},
                ensure_ascii=False,
                sort_keys=True,
            )
        )[:10]
        return sha(f"{self.backend}|{self.model_id}|{self.dim}|{weight_sig}")[:16]

    def _strip_instruct(self, text: str) -> str:
        if "\nQuery:" in text:
            return text.split("\nQuery:", 1)[1].strip()
        return text.strip()

    def _encode_hybrid_single(self, raw_text: str) -> np.ndarray:
        stripped = self._strip_instruct(raw_text)
        clean = normal(stripped)
        if not clean:
            return np.zeros(self.dim, dtype=np.float32)

        head_text = ""
        if ":" in stripped:
            candidate_head = normal(stripped.split(":", 1)[0])
            if 0 < len(candidate_head.split()) <= 6:
                head_text = candidate_head

        base_tokens = tokenize_vn(clean, include_bigrams=True)
        base_token_set = set(base_tokens)
        padded_words = " " + " ".join(tokenize_vn(clean, include_bigrams=False)) + " "

        expanded_parts = [clean]
        if head_text:
            expanded_parts.append(head_text)
            expanded_parts.append(head_text)

        for phrase, synonyms in self.synonym_map.items():
            norm_phrase = normal(phrase)
            phrase_key = "_".join(norm_phrase.split())
            if phrase_key in base_token_set or f" {norm_phrase} " in padded_words:
                expanded_parts.extend(synonyms)
                expanded_parts.extend(synonyms)
        full_text = " ".join(expanded_parts)

        stopwords = {
            "của",
            "và",
            "các",
            "những",
            "một",
            "được",
            "trong",
            "cho",
            "với",
            "hoặc",
            "là",
            "có",
            "tại",
            "vào",
            "thuộc",
            "thực",
            "thể",
            "thực_thể",
            "nguồn",
            "đích",
        }

        word_vec = np.zeros(self.dim, dtype=np.float32)
        tokens = tokenize_vn(full_text, include_bigrams=True)
        for token in tokens:
            if token in stopwords:
                continue
            is_bigram = "_" in token
            base_weight = 2.8 if is_bigram else 1.4
            learned_mult = self.term_weights.get(token, 1.0)
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            word_vec[idx] += sign * base_weight * learned_mult

        word_norm = float(np.linalg.norm(word_vec))
        if word_norm > 1e-8:
            word_vec /= word_norm

        char_vec = np.zeros(self.dim, dtype=np.float32)
        padded = f" {clean} "
        for n in (3, 4):
            if len(padded) >= n:
                for i in range(len(padded) - n + 1):
                    gram = f"c{n}:{padded[i : i + n]}"
                    digest = hashlib.md5(gram.encode("utf-8")).digest()
                    idx = int.from_bytes(digest[:4], "little") % self.dim
                    sign = 1.0 if (digest[4] & 1) == 0 else -1.0
                    char_vec[idx] += sign * 1.0

        char_norm = float(np.linalg.norm(char_vec))
        if char_norm > 1e-8:
            char_vec /= char_norm

        vec = 0.88 * word_vec + 0.12 * char_vec
        norm = float(np.linalg.norm(vec))
        if norm > 1e-8:
            vec /= norm
        return vec

    def encode(self, texts: str | Sequence[str]) -> np.ndarray:
        single = isinstance(texts, str)
        items = [texts] if single else list(texts)
        if not items:
            return np.zeros((0, self.dim), dtype=np.float32)

        if self.backend == "hybrid_vn":
            matrix = np.stack([self._encode_hybrid_single(t) for t in items], axis=0)
            return matrix[0] if single else matrix

        if self.backend == "sentence_transformers":
            if self._st_model is None:
                model_name = self.model_id.removeprefix("st:")
                with _EMBEDDER_CACHE_LOCK:
                    if model_name not in _ST_MODEL_CACHE:
                        from sentence_transformers import SentenceTransformer

                        _ST_MODEL_CACHE[model_name] = SentenceTransformer(model_name, trust_remote_code=True)
                    self._st_model = _ST_MODEL_CACHE[model_name]
            embeddings = self._st_model.encode(items, normalize_embeddings=True, convert_to_numpy=True)
            matrix = np.asarray(embeddings, dtype=np.float32)
            if matrix.ndim == 2 and matrix.shape[1] > 0:
                self.dim = int(matrix.shape[1])
            return matrix[0] if single else matrix

        if self.backend == "openai_compatible":
            from openai import OpenAI

            model_name = self.model_id.split(":", 1)[-1]
            client = OpenAI(
                api_key=self.api_key or "ollama",
                base_url=self.base_url or None,
                timeout=30.0,
            )
            rows: list[np.ndarray] = []
            batch_size = 64
            for start in range(0, len(items), batch_size):
                batch = items[start : start + batch_size]
                response = client.embeddings.create(model=model_name, input=batch)
                data_rows = list(getattr(response, "data", None) or [])
                if len(data_rows) != len(batch):
                    raise RuntimeError(
                        f"Model nhúng '{self.model_id}' trả về {len(data_rows)}/{len(batch)} vector."
                    )
                rows.extend(np.asarray(item.embedding, dtype=np.float32) for item in data_rows)
            matrix = np.stack(rows, axis=0)
            if matrix.ndim != 2 or matrix.shape[1] == 0:
                raise RuntimeError(f"Vector nhúng từ '{self.model_id}' có kích thước không hợp lệ: {matrix.shape}.")
            self.dim = int(matrix.shape[1])
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms = np.where(norms > 1e-8, norms, 1.0)
            matrix = matrix / norms
            return matrix[0] if single else matrix

        raise ValueError(f"Backend embedding không được hỗ trợ: {self.backend}")


# Bộ nhớ đệm chia sẻ các mô hình SentenceTransformer và Gateway instance
_EMBEDDER_CACHE_LOCK = threading.RLock()
_ST_MODEL_CACHE: dict[str, Any] = {}
_DEFAULT_EMBEDDER_CACHE: dict[tuple[str, str], EmbedderGateway] = {}


def clear_embedder_cache() -> None:
    """Xóa cache EmbedderGateway để nạp lại trọng số mới ngay sau khi huấn luyện."""
    with _EMBEDDER_CACHE_LOCK:
        _DEFAULT_EMBEDDER_CACHE.clear()


def default_embedder(model_id: str = "hybrid_vn:default", registry_dir: Path | None = None) -> EmbedderGateway:
    cache_key = (str(model_id), str(registry_dir or ""))
    with _EMBEDDER_CACHE_LOCK:
        if cache_key not in _DEFAULT_EMBEDDER_CACHE:
            _DEFAULT_EMBEDDER_CACHE[cache_key] = EmbedderGateway(model_id=model_id, registry_dir=registry_dir)
        return _DEFAULT_EMBEDDER_CACHE[cache_key]

