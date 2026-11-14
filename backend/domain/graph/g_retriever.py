"""Mô-đun G-Retriever & GraphRAG (PCST Steiner Subgraph, HippoRAG PPR, Naive Top-K & Benchmark Đánh giá).

Triển khai thuật toán cốt lõi của G-Retriever (He et al., NeurIPS 2024) tối ưu hóa cho Đồ thị Tri thức tiếng Việt:
1. Chỉ mục Đồ thị Lai (Hybrid Lexical IDF + N-Gram + Exact Phrase/Relation Matcher) có bộ nhớ đệm RAM siêu tốc (< 15ms/truy vấn).
2. Gán điểm thưởng Đỉnh & Cạnh Đa Bước (Multi-Hop Node & Edge Prize Assignment) theo độ tương đồng ngữ nghĩa và đường dẫn quan hệ.
3. Thuật toán Cây khung Steiner có thưởng - phạt bậc Siêu đỉnh (Hub-Penalized Prize-Collecting Steiner Tree - PCST)
   kèm mở rộng thuộc tính lá 1 bước (1-Hop Attribute & Alias Expansion) và suy luận bắc cầu 2 bước (2-Hop Bridge).
4. Thuật toán Personalized PageRank có trọng số cạnh (HippoRAG PPR) và Baseline Naive Top-K để đối sánh.
5. Chuyển hóa Đồ thị Con thành Văn bản cấu trúc (Textualized Subgraph) kèm bằng chứng nguyên văn (Evidence Grounding)
   và gọi LLM sinh câu trả lời có trích dẫn.
6. Bộ sinh câu hỏi kiểm thử đa bước tự động (1-Hop, 2-Hop Bridge, Multi-Attribute Star) đa dạng thực thể và đánh giá định lượng.
"""
from __future__ import annotations

import collections
import copy
from dataclasses import dataclass, field
import io
import json
import math
import re
import time
from typing import Any
import zipfile

from backend.domain.graph.service import approved_graph
from backend.integrations.llm import LLMGateway, make_adapter, providers
from shared.constants import STATUS_REJECTED
from shared.text_utils import normal, tokenize_vn
from shared.schemas.graph_input import GRAPH_FORMAT, GraphSnapshotDTO, graph_fingerprint

# Các quan hệ thuộc tính lá (mốc thời gian, số đo, tên gọi khác, vị trí) được ưu tiên mở rộng 1-hop quanh thực thể hạt giống
ATTRIBUTE_RELATIONS_NORM: set[str] = {
    "con goi",
    "còn gọi",
    "co nien dai",
    "có niên đại",
    "dien ra vao",
    "diễn ra vào",
    "co dien tich",
    "có diện tích",
    "toa lac tai",
    "tọa lạc tại",
    "nam tai",
    "nằm tại",
    "xay dung vao",
    "xây dựng vào",
    "khoi cong",
    "khởi công",
    "tho phung",
    "thờ phụng",
    "cao",
    "dai",
    "dài",
    "rong",
    "rộng",
    "p1 is identified by",
    "is identified by",
    "p4 has time span",
    "has time span",
    "p7 took place at",
    "took place at",
    "p43 has dimension",
    "has dimension",
    "p53 has former or current location",
    "has former or current location",
    "p81 ongoing throughout",
    "p82 at some time within",
    "p90 has value",
    "p102 has title",
    "has title",
}

ATTRIBUTE_NODE_KINDS_NORM: set[str] = {
    "mốc thời gian",
    "số đo",
    "thời gian",
    "moc thoi gian",
    "so do",
    "thoi gian",
    "e52 time span",
    "e54 dimension",
    "e41 appellation",
}

# Chỉ lọc các hư từ câu hỏi thuần túy; GIỮ LẠI các từ quan hệ như 'thuộc', 'gồm', 'tại', 'là'
STOPWORDS_VN: set[str] = {
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
    "nào",
    "gì",
    "ai",
    "đâu",
    "khi",
    "như",
    "thế",
    "hãy",
    "cho_biết",
    "biết",
    "thông_tin",
    "thông",
    "tin",
    "liên_quan",
    "liên",
    "đối_tượng",
    "đối",
    "tượng",
    "hay",
    "đó",
    "mối",
    "quan_hệ",
    "quan",
    "hệ",
    "theo",
    "đồ_thị",
    "đồ",
    "thị",
    "tri_thức",
    "tri",
    "thức",
    "cụ_thể",
    "cụ",
    "thể",
    "mốc",
}


def _clean_phrase(text: str) -> str:
    """Chuẩn hóa chuỗi thành các từ cách nhau bởi 1 khoảng trắng, tách dấu gạch dưới/nối/dấu câu."""
    separated = re.sub(r"[_\-/]+", " ", str(text or ""))
    return " ".join(tokenize_vn(normal(separated), include_bigrams=False))


@dataclass
class SubgraphRetrievalResult:
    """Kết quả truy xuất đồ thị con của G-Retriever / HippoRAG / Naive RAG."""

    query: str
    method: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    seed_node_ids: list[str] = field(default_factory=list)
    steiner_node_ids: list[str] = field(default_factory=list)
    attribute_node_ids: list[str] = field(default_factory=list)
    node_prizes: dict[str, float] = field(default_factory=dict)
    edge_prizes: dict[str, float] = field(default_factory=dict)
    textualized_graph: str = ""
    reasoning_paths: list[str] = field(default_factory=list)
    extractive_summary: str = ""
    latency_ms: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        lcc_pct = float(self.stats.get("lcc_ratio_pct", 0.0))
        return {
            "query": self.query,
            "method": self.method,
            "nodes": self.nodes,
            "edges": self.edges,
            "subgraph_nodes": self.nodes,
            "subgraph_edges": self.edges,
            "seed_node_ids": self.seed_node_ids,
            "steiner_node_ids": self.steiner_node_ids,
            "steiner_bridge_ids": self.steiner_node_ids,
            "attribute_node_ids": self.attribute_node_ids,
            "expanded_leaf_ids": self.attribute_node_ids,
            "node_prizes": self.node_prizes,
            "edge_prizes": self.edge_prizes,
            "textualized_graph": self.textualized_graph,
            "textualized_prompt": self.textualized_graph,
            "reasoning_paths": self.reasoning_paths,
            "extractive_summary": self.extractive_summary,
            "latency_ms": self.latency_ms,
            "elapsed_ms": self.latency_ms,
            "connected_components": int(self.stats.get("connected_components", 0)),
            "largest_component_ratio": round(lcc_pct / 100.0, 4),
            "estimated_tokens": int(self.stats.get("estimated_prompt_tokens", 0)),
            "stats": self.stats,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


class GraphRAGIndex:
    """Chỉ mục Đồ thị Tri thức trong RAM phục vụ truy xuất G-Retriever (PCST) và HippoRAG (PPR) dưới 20ms."""

    def __init__(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], source_label: str = "") -> None:
        t0 = time.perf_counter()
        self.source_label = source_label
        self.nodes: list[dict[str, Any]] = copy.deepcopy(nodes)
        self.edges: list[dict[str, Any]] = copy.deepcopy(edges)

        self.nodes_by_id: dict[str, dict[str, Any]] = {}
        for n in self.nodes:
            nid = str(n.get("id", ""))
            if nid:
                self.nodes_by_id[nid] = n

        self.edges_by_id: dict[str, dict[str, Any]] = {}
        self.edge_endpoints: dict[str, tuple[str, str]] = {}
        self.adj: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
        self.out_edges: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        self.in_edges: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        self.degree: dict[str, int] = collections.Counter()

        for e in self.edges:
            eid = str(e.get("id", ""))
            u = str(e.get("source", ""))
            v = str(e.get("target", ""))
            if not eid or u not in self.nodes_by_id or v not in self.nodes_by_id:
                continue
            self.edges_by_id[eid] = e
            self.edge_endpoints[eid] = (u, v)
            self.adj[u].append((v, eid))
            if u != v:
                self.adj[v].append((u, eid))
            self.out_edges[u].append(e)
            self.in_edges[v].append(e)
            self.degree[u] += 1
            self.degree[v] += 1

        # Tiền tính văn bản chuẩn hóa & chỉ mục ngược TF-IDF cho Đỉnh và Cạnh
        self.node_name_norm: dict[str, str] = {}
        self.node_kind_norm: dict[str, str] = {}
        self.node_tokens: dict[str, set[str]] = {}
        self.token_to_nodes: dict[str, list[str]] = collections.defaultdict(list)

        for nid, n in self.nodes_by_id.items():
            name_n = _clean_phrase(str(n.get("name", "")))
            kind_n = _clean_phrase(str(n.get("kind") or n.get("type") or ""))
            desc_n = _clean_phrase(str(n.get("description", "")))
            aliases_n = " ".join(_clean_phrase(str(a)) for a in (n.get("aliases") or []))
            self.node_name_norm[nid] = name_n
            self.node_kind_norm[nid] = kind_n
            full_text = f"{name_n} {name_n} {aliases_n} {kind_n} {desc_n}".strip()
            toks = {t for t in tokenize_vn(full_text, include_bigrams=True) if t not in STOPWORDS_VN and len(t) > 1}
            self.node_tokens[nid] = toks
            for t in toks:
                self.token_to_nodes[t].append(nid)

        self.edge_rel_norm: dict[str, str] = {}
        self.rel_norm_to_edges: dict[str, list[str]] = collections.defaultdict(list)
        self.edge_tokens: dict[str, set[str]] = {}
        self.token_to_edges: dict[str, list[str]] = collections.defaultdict(list)

        for eid, e in self.edges_by_id.items():
            u, v = self.edge_endpoints[eid]
            u_name = self.node_name_norm.get(u, "")
            v_name = self.node_name_norm.get(v, "")
            rel_n = _clean_phrase(str(e.get("relation", "")))
            ev_n = _clean_phrase(str(e.get("evidence", "")))
            self.edge_rel_norm[eid] = rel_n
            if rel_n:
                self.rel_norm_to_edges[rel_n].append(eid)
            full_edge_text = f"{u_name} {rel_n} {rel_n} {v_name} {ev_n}".strip()
            toks = {t for t in tokenize_vn(full_edge_text, include_bigrams=True) if t not in STOPWORDS_VN and len(t) > 1}
            self.edge_tokens[eid] = toks
            for t in toks:
                self.token_to_edges[t].append(eid)

        n_docs = max(1, len(self.nodes_by_id) + len(self.edges_by_id))
        self.token_idf: dict[str, float] = {}
        all_vocab = set(self.token_to_nodes.keys()) | set(self.token_to_edges.keys())
        for tok in all_vocab:
            df = len(self.token_to_nodes.get(tok, ())) + len(self.token_to_edges.get(tok, ()))
            self.token_idf[tok] = math.log(1.0 + n_docs / (1.0 + df)) * (1.45 if "_" in tok else 1.0)

        self.build_ms = (time.perf_counter() - t0) * 1000.0

    def match_relations_in_query(self, query_norm: str) -> set[str]:
        """Tìm tất cả các tên quan hệ chuẩn hóa xuất hiện trong câu hỏi."""
        q_padded = f" {query_norm} "
        matched_rels: set[str] = set()
        for rel_n in self.rel_norm_to_edges:
            if len(rel_n) >= 2 and f" {rel_n} " in q_padded:
                matched_rels.add(rel_n)
        return matched_rels

    def score_query(self, query: str) -> tuple[dict[str, float], dict[str, float], set[str]]:
        """Chấm điểm tương đồng lai (Exact Phrase + IDF Token/Bigram + Specificity) cho toàn bộ Đỉnh & Cạnh."""
        q_clean = _clean_phrase(query)
        if not q_clean:
            return {}, {}, set()

        q_padded = f" {q_clean} "
        q_tokens = [t for t in tokenize_vn(q_clean, include_bigrams=True) if t not in STOPWORDS_VN and len(t) > 1]
        q_token_set = set(q_tokens)
        q_total_idf = sum(self.token_idf.get(t, 1.0) for t in q_token_set) or 1.0
        matched_rels = self.match_relations_in_query(q_clean)

        # 1. Chấm điểm Đỉnh (Node Relevance & Prize)
        cand_node_scores: dict[str, float] = collections.defaultdict(float)
        for tok in q_token_set:
            w = self.token_idf.get(tok, 1.0)
            for nid in self.token_to_nodes.get(tok, ()):
                cand_node_scores[nid] += w

        node_scores: dict[str, float] = {}
        for nid, raw_score in cand_node_scores.items():
            ntoks = self.node_tokens.get(nid, set())
            norm_overlap = raw_score / (q_total_idf * (1.0 + 0.12 * math.log(1 + len(ntoks))))
            name_n = self.node_name_norm.get(nid, "")
            phrase_boost = 0.0
            if name_n and len(name_n) >= 2 and f" {name_n} " in q_padded:
                deg = self.degree.get(nid, 1)
                specificity = 1.0 / (1.0 + 0.22 * math.log(1 + max(0, deg - 5)))
                word_cnt = len(name_n.split())
                # Ưu tiên mạnh thực thể khớp cụm từ dài nhất (Longest Entity Phrase Match)
                word_cnt_bonus = 0.60 + 0.45 * (word_cnt ** 1.25)
                phrase_boost = specificity * word_cnt_bonus
            score = norm_overlap * 0.70 + phrase_boost
            if score > 0.03:
                node_scores[nid] = score

        # 2. Chấm điểm Cạnh trực tiếp (Direct Edge Relevance)
        cand_edge_scores: dict[str, float] = collections.defaultdict(float)
        for tok in q_token_set:
            w = self.token_idf.get(tok, 1.0)
            # Bỏ qua token quá phổ biến (> 2500 cạnh) để tăng tốc độ chấm điểm < 10ms
            e_list = self.token_to_edges.get(tok, ())
            if len(e_list) <= 2500:
                for eid in e_list:
                    cand_edge_scores[eid] += w

        # Đảm bảo mọi cạnh kề với Top-15 đỉnh hạt giống luôn được xét điểm
        for s_nid, _ in sorted(node_scores.items(), key=lambda x: -x[1])[:15]:
            for _, eid in self.adj.get(s_nid, ()):
                if eid not in cand_edge_scores:
                    cand_edge_scores[eid] += 0.01

        edge_scores: dict[str, float] = {}
        for eid, raw_score in cand_edge_scores.items():
            u, v = self.edge_endpoints[eid]
            etoks = self.edge_tokens.get(eid, set())
            norm_overlap = raw_score / (q_total_idf * (1.0 + 0.10 * math.log(1 + len(etoks))))
            rel_n = self.edge_rel_norm.get(eid, "")
            rel_boost = 0.35 if rel_n in matched_rels else 0.0
            u_score = node_scores.get(u, 0.0)
            v_score = node_scores.get(v, 0.0)
            endpoint_boost = 0.40 * max(u_score, v_score) + 0.25 * min(u_score, v_score)
            score = norm_overlap * 0.55 + rel_boost + endpoint_boost
            if score > 0.04:
                edge_scores[eid] = score

        return node_scores, edge_scores, matched_rels


_INDEX_CACHE: dict[str, GraphRAGIndex] = {}


def get_or_build_graph_index(
    project: dict[str, Any],
    *,
    approved_only: bool = True,
) -> GraphRAGIndex:
    """Cache GraphRAGIndex theo nội dung graph đã chọn; snapshot không lọc approved lần nữa."""
    proj_id = str(project.get("project_id") or project.get("name") or "default")
    all_nodes = project.get("nodes", [])
    all_edges = project.get("edges", [])
    if project.get("graph_format") == GRAPH_FORMAT:
        # A validated application snapshot already selected its source. Do not
        # relabel unreviewed baseline facts as approved or silently change source.
        mode_tag = project.get("graph_source")
        if mode_tag not in ("approved", "baseline", "all"):
            raise ValueError("Nguồn graph snapshot không hợp lệ")
        nodes, edges = all_nodes, all_edges
    elif approved_only:
        nodes, edges = approved_graph(project)
        mode_tag = "approved"
    else:
        nodes = [n for n in all_nodes if n.get("status") != STATUS_REJECTED]
        edges = [e for e in all_edges if e.get("status") != STATUS_REJECTED]
        mode_tag = "all"

    # Counts/saved_at cannot distinguish methods, edits or approval changes.
    # Hash the actual selected input, even when callers mutate a dict in place.
    fast_cache_key = graph_fingerprint([proj_id, mode_tag, nodes, edges])
    cached = _INDEX_CACHE.get(fast_cache_key)
    if cached is not None:
        return cached
    idx = GraphRAGIndex(nodes, edges, source_label=f"{project.get('name', proj_id)} ({mode_tag})")
    if len(_INDEX_CACHE) >= 8:
        _INDEX_CACHE.clear()
    _INDEX_CACHE[fast_cache_key] = idx
    return idx


def load_project_from_export_bytes(raw_bytes: bytes, filename: str = "") -> dict[str, Any]:
    """Đọc dữ liệu dự án từ gói .zip xuất ra (ưu tiên do_thi_da_duyet.json, fallback du_an_day_du.json) hoặc file .json."""
    fname_lower = (filename or "").lower()
    if fname_lower.endswith(".zip") or raw_bytes[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
            names = set(zf.namelist())
            approved_obj: dict[str, Any] | None = None
            full_obj: dict[str, Any] | None = None
            if "do_thi_da_duyet.json" in names:
                approved_obj = json.loads(zf.read("do_thi_da_duyet.json").decode("utf-8-sig"))
            if "du_an_day_du.json" in names:
                full_obj = json.loads(zf.read("du_an_day_du.json").decode("utf-8-sig"))

            if approved_obj and approved_obj.get("quan_he"):
                base = full_obj if isinstance(full_obj, dict) else {}
                return {
                    "project_id": approved_obj.get("project_id") or base.get("project_id") or "zip_export",
                    "name": approved_obj.get("ten_du_an") or base.get("name") or filename or "Đồ thị từ gói ZIP",
                    "nodes": approved_obj.get("thuc_the", []),
                    "edges": approved_obj.get("quan_he", []),
                    "documents": base.get("documents", []),
                    "entity_types": base.get("entity_types", []),
                    "relations": base.get("relations", []),
                }
            if isinstance(full_obj, dict):
                return full_obj
            raise ValueError("Gói ZIP không chứa tệp 'do_thi_da_duyet.json' hoặc 'du_an_day_du.json' hợp lệ.")

    obj = json.loads(raw_bytes.decode("utf-8-sig"))
    if not isinstance(obj, dict):
        raise ValueError("Tệp JSON tải lên không phải là đối tượng hợp lệ.")
    if obj.get("format") == GRAPH_FORMAT:
        return GraphSnapshotDTO.from_dict(obj).as_project()
    if obj.get("format") == "kg-studio.free-triples.v1":
        raise ValueError("Đây là raw runs; hãy dựng và xuất KG baseline ở nguồn Baseline B trước khi nạp graph")
    if "thuc_the" in obj and "quan_he" in obj:
        return {
            "project_id": obj.get("project_id") or "json_export",
            "name": obj.get("ten_du_an") or filename or "Đồ thị đã duyệt",
            "nodes": obj.get("thuc_the", []),
            "edges": obj.get("quan_he", []),
            "documents": [],
        }
    return obj


def _assign_prizes(
    node_scores: dict[str, float],
    edge_scores: dict[str, float],
    *,
    top_k_nodes: int = 12,
    top_k_edges: int = 25,
) -> tuple[dict[str, float], dict[str, float]]:
    """Gán giải thưởng (Node Prizes & Edge Prizes) theo đúng chuẩn bài báo G-Retriever."""
    ranked_nodes = sorted(node_scores.items(), key=lambda x: (-x[1], x[0]))[:top_k_nodes]
    node_prizes: dict[str, float] = {}
    k_v = max(1, len(ranked_nodes))
    for rank, (nid, sc) in enumerate(ranked_nodes):
        decay = 1.0 - (rank / (2.0 * k_v))
        node_prizes[nid] = round(float(sc * decay * 2.0), 4)

    ranked_edges = sorted(edge_scores.items(), key=lambda x: (-x[1], x[0]))[:top_k_edges]
    edge_prizes: dict[str, float] = {}
    k_e = max(1, len(ranked_edges))
    for rank, (eid, sc) in enumerate(ranked_edges):
        decay = 1.0 - (rank / (2.0 * k_e))
        edge_prizes[eid] = round(float(sc * decay * 1.5), 4)

    return node_prizes, edge_prizes


def _retrieve_pcst_subgraph(
    index: GraphRAGIndex,
    query: str,
    node_scores: dict[str, float],
    edge_scores: dict[str, float],
    matched_rels: set[str],
    *,
    max_edges: int = 20,
    base_edge_cost: float = 0.35,
    hub_penalty_alpha: float = 0.45,
    expand_leaf_attributes: bool = True,
) -> tuple[list[str], list[str], list[str], list[str], dict[str, float], dict[str, float]]:
    """Thuật toán Prize-Collecting Steiner Tree (PCST) có phạt bậc Siêu đỉnh + Lan truyền giải thưởng 2-hop."""
    q_norm = f" {_clean_phrase(query)} "
    node_prizes, edge_prizes = _assign_prizes(
        node_scores,
        edge_scores,
        top_k_nodes=min(15, max(6, max_edges // 2 + 2)),
        top_k_edges=min(40, max_edges * 2),
    )

    # 1. Chọn tập đỉnh hạt giống (Terminals) có giải thưởng cao nhất
    sorted_seeds = [nid for nid, _ in sorted(node_prizes.items(), key=lambda x: (-x[1], x[0]))[:8]]
    seed_set = set(sorted_seeds)
    steiner_nodes: set[str] = set()

    # 2. LAN TRUYỀN GIẢI THƯỞNG 2-HOP STEINER (Multi-Hop Steiner Prize Propagation):
    # Khi câu hỏi nhắc đến thực thể hạt giống u và chuỗi quan hệ r1 -> r2 (nhưng ẩn tên đỉnh trung gian B),
    # PCST gán giải thưởng cầu nối cho B và cạnh bước 2 (B --[r2]--> C) để cây Steiner nối trọn vẹn u -> B -> C!
    two_hop_bonus_edges: list[tuple[float, str, str, str]] = []
    for s_nid in sorted_seeds[:6]:
        s_prize = node_prizes.get(s_nid, 0.0)
        if s_prize < 0.35:
            continue
        for b_nid, eid1 in index.adj.get(s_nid, ()):
            if b_nid == s_nid:
                continue
            b_deg = index.degree.get(b_nid, 1)
            rel1 = index.edge_rel_norm.get(eid1, "")
            b_kind = index.node_kind_norm.get(b_nid, "")
            r1_match = 1.2 if (rel1 in matched_rels) else 0.0
            kind_match = 0.6 if (b_kind and len(b_kind) >= 3 and b_kind in q_norm) else 0.0
            e1_sc = edge_scores.get(eid1, 0.0)
            # Bỏ qua siêu đỉnh khổng lồ nếu không khớp quan hệ lẫn điểm cạnh đáng kể; dùng phạt mượt thay cho cutoff cứng
            if b_deg > 250 and r1_match <= 0.0 and e1_sc < 0.40:
                continue
            hub_damp = 1.0 / (1.0 + 0.65 * max(0.0, math.log(b_deg / 15.0))) if b_deg > 15 else 1.0

            if r1_match > 0 or kind_match > 0 or e1_sc >= 0.35:
                bridge_strength = s_prize * hub_damp * (0.45 + 0.65 * r1_match + 0.35 * kind_match + 0.25 * e1_sc)
                # Kiểm tra các cạnh bước 2 đi ra từ đỉnh trung gian B
                for c_nid, eid2 in index.adj.get(b_nid, ()):
                    if eid2 == eid1 or c_nid == s_nid:
                        continue
                    rel2 = index.edge_rel_norm.get(eid2, "")
                    r2_match = 1.5 if (rel2 in matched_rels and rel2 != rel1) else (0.7 if rel2 in matched_rels else 0.0)
                    e2_sc = edge_scores.get(eid2, 0.0) + 0.5 * node_scores.get(c_nid, 0.0)
                    if r2_match > 0 or e2_sc > 0.25:
                        dual_rel_bonus = 2.0 if (r1_match > 0 and r2_match > 0) else 1.0
                        chain_prize = bridge_strength * (0.50 + r2_match + 0.35 * e2_sc) * dual_rel_bonus
                        two_hop_bonus_edges.append((chain_prize, eid1, eid2, b_nid))
                        edge_prizes[eid1] = max(edge_prizes.get(eid1, 0.0), round(chain_prize * 0.9, 4))
                        edge_prizes[eid2] = max(edge_prizes.get(eid2, 0.0), round(chain_prize, 4))
                        if b_nid not in seed_set:
                            node_prizes[b_nid] = max(node_prizes.get(b_nid, 0.0), round(bridge_strength * 0.85, 4))

    def _edge_cost(eid: str) -> float:
        u, v = index.edge_endpoints[eid]
        max_deg = max(index.degree.get(u, 1), index.degree.get(v, 1))
        hub_mult = 1.0 + hub_penalty_alpha * max(0.0, math.log(max_deg / 15.0)) if max_deg > 15 else 1.0
        prize_discount = 0.65 * edge_prizes.get(eid, 0.0)
        return max(0.02, base_edge_cost * hub_mult - prize_discount)

    selected_edge_ids: list[str] = []
    selected_edge_set: set[str] = set()

    # 3. Đưa các nhánh Steiner 2-hop có lợi ích ròng dương cao nhất vào cây khung trước
    two_hop_bonus_edges.sort(key=lambda x: -x[0])
    for chain_prize, eid1, eid2, b_nid in two_hop_bonus_edges[: max(4, max_edges // 3)]:
        if chain_prize - (_edge_cost(eid1) + _edge_cost(eid2)) > 0.0:
            for eid in (eid1, eid2):
                if eid not in selected_edge_set and len(selected_edge_ids) < max_edges:
                    selected_edge_set.add(eid)
                    selected_edge_ids.append(eid)
            if b_nid not in seed_set:
                steiner_nodes.add(b_nid)

    # 4. Nối các đỉnh hạt giống rời nhau bằng đường đi ngắn nhất có thưởng-phạt bậc (Bounded Steiner Paths <= 3 bước)
    if len(sorted_seeds) >= 2:
        anchor_set: set[str] = {sorted_seeds[0]} | steiner_nodes
        remaining_seeds = [s for s in sorted_seeds[1:] if s not in anchor_set]

        while remaining_seeds and len(selected_edge_ids) < max_edges:
            best_target: str | None = None
            best_net_gain = -1e9
            best_path_edges: list[str] = []
            best_path_nodes: list[str] = []

            for target_seed in remaining_seeds:
                dist: dict[str, float] = {target_seed: 0.0}
                parent: dict[str, tuple[str, str]] = {}
                hops: dict[str, int] = {target_seed: 0}
                frontier: list[tuple[float, str]] = [(0.0, target_seed)]

                found_anchor: str | None = None
                while frontier:
                    frontier.sort(key=lambda x: x[0])
                    d_u, u = frontier.pop(0)
                    if d_u > dist.get(u, 1e9):
                        continue
                    if u in anchor_set:
                        found_anchor = u
                        break
                    if hops[u] >= 3:
                        continue
                    for v, eid in index.adj.get(u, ()):
                        step_cost = max(0.01, _edge_cost(eid) - 0.25 * node_prizes.get(v, 0.0))
                        nd = d_u + step_cost
                        if nd < dist.get(v, 1e9):
                            dist[v] = nd
                            hops[v] = hops[u] + 1
                            parent[v] = (u, eid)
                            frontier.append((nd, v))

                if found_anchor is not None:
                    cur = found_anchor
                    p_edges: list[str] = []
                    p_nodes: list[str] = [cur]
                    while cur != target_seed:
                        prev_node, via_eid = parent[cur]
                        p_edges.append(via_eid)
                        p_nodes.append(prev_node)
                        cur = prev_node
                    path_cost = sum(_edge_cost(eid) for eid in p_edges)
                    path_prize = node_prizes.get(target_seed, 0.0) + sum(
                        node_prizes.get(x, 0.0) for x in p_nodes if x not in anchor_set and x != target_seed
                    ) + sum(edge_prizes.get(eid, 0.0) for eid in p_edges)
                    net_gain = path_prize - 0.5 * path_cost
                    if net_gain > best_net_gain:
                        best_net_gain = net_gain
                        best_target = target_seed
                        best_path_edges = p_edges
                        best_path_nodes = p_nodes

            if best_target is not None and best_net_gain > 0.0:
                remaining_seeds.remove(best_target)
                for n_in_p in best_path_nodes:
                    anchor_set.add(n_in_p)
                    if n_in_p not in seed_set:
                        steiner_nodes.add(n_in_p)
                for eid in best_path_edges:
                    if eid not in selected_edge_set and len(selected_edge_ids) < max_edges:
                        selected_edge_set.add(eid)
                        selected_edge_ids.append(eid)
            else:
                nxt = remaining_seeds.pop(0)
                anchor_set.add(nxt)

    # 5. Thu thập các cạnh có giải thưởng dương cao nhất gắn với hạt giống / đỉnh Steiner (PCST Edge Collection)
    active_nodes = set(seed_set) | steiner_nodes
    candidate_eids = list(edge_prizes.keys())
    for u in list(active_nodes):
        for _, eid in index.adj.get(u, ()):
            if eid not in edge_prizes:
                candidate_eids.append(eid)

    scored_candidates: list[tuple[float, str]] = []
    for eid in dict.fromkeys(candidate_eids):
        if eid in selected_edge_set:
            continue
        u, v = index.edge_endpoints[eid]
        ep = edge_prizes.get(eid, edge_scores.get(eid, 0.0))
        np_bonus = 0.45 * (node_prizes.get(u, 0.0) + node_prizes.get(v, 0.0))
        conn_bonus = 0.35 if (u in active_nodes or v in active_nodes) else 0.0
        net = ep + np_bonus + conn_bonus - 0.35 * _edge_cost(eid)
        scored_candidates.append((net, eid))

    scored_candidates.sort(key=lambda x: (-x[0], x[1]))
    core_budget = max(1, int(max_edges * 0.80)) if expand_leaf_attributes else max_edges
    for _, eid in scored_candidates:
        if len(selected_edge_ids) >= core_budget:
            break
        selected_edge_set.add(eid)
        selected_edge_ids.append(eid)
        u, v = index.edge_endpoints[eid]
        active_nodes.add(u)
        active_nodes.add(v)

    # 6. Mở rộng 1-hop cho các cạnh thuộc tính lá (mốc thời gian, số đo, tên gọi khác)
    attribute_nodes: set[str] = set()
    if expand_leaf_attributes and len(selected_edge_ids) < max_edges:
        expansion_pool: list[tuple[float, str]] = []
        top_seeds_for_exp = sorted_seeds[:3] if sorted_seeds else list(active_nodes)[:3]
        for s_nid in top_seeds_for_exp:
            for v, eid in index.adj.get(s_nid, ()):
                if eid in selected_edge_set:
                    continue
                rel_n = index.edge_rel_norm.get(eid, "")
                v_kind = index.node_kind_norm.get(v, "")
                if (rel_n in ATTRIBUTE_RELATIONS_NORM) or (v_kind in ATTRIBUTE_NODE_KINDS_NORM):
                    prio = 0.80 + edge_scores.get(eid, 0.0) + (0.35 if rel_n in matched_rels else 0.0)
                    expansion_pool.append((prio, eid))

        expansion_pool.sort(key=lambda x: (-x[0], x[1]))
        for _, eid in expansion_pool:
            if len(selected_edge_ids) >= max_edges:
                break
            if eid not in selected_edge_set:
                selected_edge_set.add(eid)
                selected_edge_ids.append(eid)
                for endpoint in index.edge_endpoints[eid]:
                    if endpoint not in seed_set and endpoint not in steiner_nodes:
                        attribute_nodes.add(endpoint)

    for _, eid in scored_candidates:
        if len(selected_edge_ids) >= max_edges:
            break
        if eid not in selected_edge_set:
            selected_edge_set.add(eid)
            selected_edge_ids.append(eid)

    return (
        selected_edge_ids,
        sorted_seeds,
        sorted(steiner_nodes - seed_set),
        sorted(attribute_nodes - seed_set - steiner_nodes),
        node_prizes,
        edge_prizes,
    )


def _retrieve_ppr_subgraph(
    index: GraphRAGIndex,
    node_scores: dict[str, float],
    edge_scores: dict[str, float],
    matched_rels: set[str],
    *,
    max_edges: int = 20,
    damping: float = 0.55,
    iterations: int = 10,
) -> tuple[list[str], list[str], list[str], list[str], dict[str, float], dict[str, float]]:
    """Thuật toán HippoRAG — Personalized PageRank (PPR) tự động chuẩn hóa theo bậc đỉnh và khớp quan hệ."""
    node_prizes, edge_prizes = _assign_prizes(node_scores, edge_scores, top_k_nodes=6, top_k_edges=30)
    seed_nodes = [nid for nid, _ in sorted(node_prizes.items(), key=lambda x: (-x[1], x[0]))[:3]]
    if not seed_nodes and edge_prizes:
        top_eid = next(iter(edge_prizes.keys()))
        u0, v0 = index.edge_endpoints[top_eid]
        seed_nodes = [u0, v0]

    total_p0 = sum(node_prizes.get(nid, 0.1) ** 3 for nid in seed_nodes) or 1.0
    p0: dict[str, float] = {nid: (node_prizes.get(nid, 0.1) ** 3) / total_p0 for nid in seed_nodes}
    pi: dict[str, float] = dict(p0)

    for _ in range(iterations):
        nxt: dict[str, float] = {nid: (1.0 - damping) * val for nid, val in p0.items()}
        dangling_mass = 0.0
        active_items = sorted(
            ((u, prob_u) for u, prob_u in pi.items() if prob_u >= 1e-6),
            key=lambda x: (-x[1], x[0]),
        )
        for u, prob_u in active_items:
            neighbors = index.adj.get(u, ())
            if not neighbors:
                dangling_mass += damping * prob_u
                continue
            weights: list[tuple[str, float]] = []
            w_sum = 0.0
            for v, eid in neighbors:
                rel_match = index.edge_rel_norm.get(eid, "") in matched_rels
                rel_w = 18.0 if rel_match else 0.05
                deg_v = index.degree.get(v, 1)
                w = (rel_w + 5.0 * edge_scores.get(eid, 0.0)) / (1.0 + 0.25 * deg_v)
                weights.append((v, w))
                w_sum += w
            if w_sum > 0:
                scale = damping * prob_u / w_sum
                for v, w in weights:
                    nxt[v] = nxt.get(v, 0.0) + scale * w
            else:
                dangling_mass += damping * prob_u
        if dangling_mass > 0.0 and p0:
            for nid, val in p0.items():
                nxt[nid] = nxt.get(nid, 0.0) + dangling_mass * val
        total_pi = sum(nxt.values())
        pi = {nid: val / total_pi for nid, val in nxt.items()} if total_pi > 0.0 else nxt

    ppr_edge_scores: list[tuple[float, str]] = []
    candidate_edges: set[str] = set(edge_scores.keys())
    for u, _ in sorted(pi.items(), key=lambda x: (-x[1], x[0]))[: max(120, max_edges * 8)]:
        for _, eid in index.adj.get(u, ()):
            candidate_edges.add(eid)

    seed_set = set(seed_nodes)
    for eid in candidate_edges:
        u, v = index.edge_endpoints[eid]
        is_rel_match = index.edge_rel_norm.get(eid, "") in matched_rels
        rel_mult = 4.5 if is_rel_match else 0.35
        # Cạnh ở bước nhảy thứ 2 (nối từ đỉnh trung gian B đã nhận xác suất PPR sang đích C khớp quan hệ)
        bridge_walk_bonus = 1.8 if (is_rel_match and (u not in seed_set and v not in seed_set)) else 0.0
        ppr_mass = (pi.get(u, 0.0) ** 0.45) + (pi.get(v, 0.0) ** 0.45)
        sc = ppr_mass * rel_mult * (1.0 + 2.0 * edge_scores.get(eid, 0.0) + bridge_walk_bonus) + 0.5 * edge_scores.get(eid, 0.0)
        ppr_edge_scores.append((sc, eid))

    ppr_edge_scores.sort(key=lambda x: (-x[0], x[1]))
    selected_edge_ids = [eid for _, eid in ppr_edge_scores[:max_edges]]
    walked_nodes = {
        ep
        for eid in selected_edge_ids
        for ep in index.edge_endpoints[eid]
    } - seed_set

    ppr_prizes = {nid: round(float(val), 4) for nid, val in sorted(pi.items(), key=lambda x: -x[1])[:30]}
    return (
        selected_edge_ids,
        seed_nodes,
        sorted(walked_nodes),
        [],
        ppr_prizes,
        edge_prizes,
    )


def _retrieve_naive_topk(
    index: GraphRAGIndex,
    node_scores: dict[str, float],
    edge_scores: dict[str, float],
    *,
    max_edges: int = 20,
) -> tuple[list[str], list[str], list[str], list[str], dict[str, float], dict[str, float]]:
    """Baseline Naive Top-K: chỉ lấy Top-K cạnh rời rạc theo điểm khớp văn bản trực tiếp (không có cấu trúc đồ thị)."""
    # Trong Naive Vector/Lexical RAG, mỗi bộ ba được nhúng độc lập nên không có lan truyền điểm từ lân cận
    ranked = sorted(edge_scores.items(), key=lambda x: (-x[1], x[0]))[:max_edges]
    selected_edge_ids = [eid for eid, _ in ranked]
    seed_nodes = [nid for nid, _ in sorted(node_scores.items(), key=lambda x: (-x[1], x[0]))[:5]]
    edge_prizes = {eid: round(float(sc), 4) for eid, sc in ranked}
    node_prizes = {nid: round(float(node_scores[nid]), 4) for nid in seed_nodes if nid in node_scores}
    return selected_edge_ids, seed_nodes, [], [], node_prizes, edge_prizes


def _count_connected_components(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> tuple[int, float]:
    """Đếm số thành phần liên thông và tỷ lệ đỉnh nằm trong thành phần liên thông lớn nhất (Largest Connected Component %)."""
    if not nodes:
        return 0, 0.0
    node_ids = {str(n["id"]) for n in nodes}
    adj: dict[str, set[str]] = {nid: set() for nid in node_ids}
    for e in edges:
        u, v = str(e.get("source", "")), str(e.get("target", ""))
        if u in adj and v in adj and u != v:
            adj[u].add(v)
            adj[v].add(u)

    visited: set[str] = set()
    comp_sizes: list[int] = []
    for nid in node_ids:
        if nid in visited:
            continue
        q = collections.deque([nid])
        visited.add(nid)
        sz = 0
        while q:
            cur = q.popleft()
            sz += 1
            for nxt in adj[cur]:
                if nxt not in visited:
                    visited.add(nxt)
                    q.append(nxt)
        comp_sizes.append(sz)

    largest = max(comp_sizes) if comp_sizes else 0
    lcc_ratio = round((largest / len(node_ids)) * 100.0, 1) if node_ids else 0.0
    return len(comp_sizes), lcc_ratio


def _build_textualized_graph_and_paths(
    index: GraphRAGIndex,
    sub_nodes: list[dict[str, Any]],
    sub_edges: list[dict[str, Any]],
    seed_set: set[str],
    steiner_set: set[str],
) -> tuple[str, list[str], str]:
    """Chuyển hóa đồ thị con thành bảng văn bản chuẩn G-Retriever + trích xuất các chuỗi suy luận đa bước."""
    node_lines = [
        "=== BẢNG THỰC THỂ TRONG ĐỒ THỊ CON (NODES) ===",
        "node_id | ten_thuc_the | loai_thuc_the | vai_tro_do_thi | mo_ta",
    ]
    for n in sub_nodes:
        nid = str(n.get("id", ""))
        role = (
            "Hạt giống (Seed)"
            if nid in seed_set
            else ("Cầu nối Steiner (Bridge)" if nid in steiner_set else "Thuộc tính / Mở rộng (Leaf)")
        )
        desc = str(n.get("description") or "").strip()
        if len(desc) > 120:
            desc = desc[:117] + "..."
        kind = str(n.get("kind") or n.get("type") or "Chưa phân loại")
        node_lines.append(f"{nid} | {n.get('name', '')} | {kind} | {role} | {desc}")

    edge_lines = [
        "",
        "=== BẢNG QUAN HỆ & BẰNG CHỨNG NGUYÊN VĂN (EDGES) ===",
        "edge_id | thuc_the_nguon | quan_he | thuc_the_dich | bang_chung_nguyen_van | tai_lieu_nguon",
    ]
    reasoning_paths: list[str] = []
    out_by_node: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for e in sub_edges:
        eid = str(e.get("id", ""))
        u = str(e.get("source", ""))
        v = str(e.get("target", ""))
        u_node = index.nodes_by_id.get(u, {})
        v_node = index.nodes_by_id.get(v, {})
        u_name = str(u_node.get("name", u))
        v_name = str(v_node.get("name", v))
        rel = str(e.get("relation", ""))
        ev = str(e.get("evidence") or "").strip().replace("\n", " ")
        doc_ref = str(e.get("doc_name") or e.get("doc_id") or "Tài liệu gốc")
        if e.get("chunk_number") is not None:
            doc_ref += f" (Đoạn {e['chunk_number']})"
        edge_lines.append(f"{eid} | {u_name} | {rel} | {v_name} | \"{ev}\" | {doc_ref}")
        out_by_node[u].append(e)

    # Phát hiện chuỗi suy luận 2 bước (2-hop chains: A -> B -> C) trong đồ thị con
    seen_paths: set[str] = set()
    for e1 in sub_edges:
        u = str(e1.get("source", ""))
        b = str(e1.get("target", ""))
        for e2 in out_by_node.get(b, ()):
            c = str(e2.get("target", ""))
            if c == u:
                continue
            u_name = index.nodes_by_id.get(u, {}).get("name", u)
            b_name = index.nodes_by_id.get(b, {}).get("name", b)
            c_name = index.nodes_by_id.get(c, {}).get("name", c)
            p_str = f"**{u_name}** ──[{e1.get('relation', '')}]──► **{b_name}** ──[{e2.get('relation', '')}]──► **{c_name}**"
            if p_str not in seen_paths:
                seen_paths.add(p_str)
                reasoning_paths.append(p_str)
            if len(reasoning_paths) >= 8:
                break
        if len(reasoning_paths) >= 8:
            break

    if not reasoning_paths:
        for e in sub_edges[:6]:
            u_name = index.nodes_by_id.get(str(e.get("source", "")), {}).get("name", "")
            v_name = index.nodes_by_id.get(str(e.get("target", "")), {}).get("name", "")
            reasoning_paths.append(f"**{u_name}** ──[{e.get('relation', '')}]──► **{v_name}**")

    summary_bullets: list[str] = []
    for e in sub_edges[:8]:
        u_name = index.nodes_by_id.get(str(e.get("source", "")), {}).get("name", "")
        v_name = index.nodes_by_id.get(str(e.get("target", "")), {}).get("name", "")
        rel = str(e.get("relation", ""))
        ev = str(e.get("evidence") or "").strip()
        doc_ref = str(e.get("doc_name") or e.get("doc_id") or "")
        summary_bullets.append(
            f"- **{u_name}** *{rel}* **{v_name}** — Bằng chứng: *\"{ev}\"* (`{e.get('id', '')}` · {doc_ref})"
        )
    extractive_summary = "\n".join(summary_bullets) if summary_bullets else "Không tìm thấy cạnh phù hợp trong đồ thị."

    textualized = "\n".join(node_lines + edge_lines)
    return textualized, reasoning_paths, extractive_summary


def retrieve_subgraph(
    project: dict[str, Any],
    query: str,
    *,
    method: str = "pcst",
    max_edges: int = 20,
    approved_only: bool = True,
    base_edge_cost: float = 0.35,
    hub_penalty_alpha: float = 0.45,
    expand_leaf_attributes: bool = True,
) -> SubgraphRetrievalResult:
    """Truy xuất đồ thị con theo phương pháp chọn lọc: 'pcst' (G-Retriever), 'ppr' (HippoRAG), hoặc 'naive_topk'."""
    t0 = time.perf_counter()
    index = get_or_build_graph_index(project, approved_only=approved_only)
    node_scores, edge_scores, matched_rels = index.score_query(query)

    if method == "ppr":
        sel_eids, seeds, steiners, attrs, n_prizes, e_prizes = _retrieve_ppr_subgraph(
            index, node_scores, edge_scores, matched_rels, max_edges=max_edges
        )
    elif method == "naive_topk":
        sel_eids, seeds, steiners, attrs, n_prizes, e_prizes = _retrieve_naive_topk(
            index, node_scores, edge_scores, max_edges=max_edges
        )
    else:
        sel_eids, seeds, steiners, attrs, n_prizes, e_prizes = _retrieve_pcst_subgraph(
            index,
            query,
            node_scores,
            edge_scores,
            matched_rels,
            max_edges=max_edges,
            base_edge_cost=base_edge_cost,
            hub_penalty_alpha=hub_penalty_alpha,
            expand_leaf_attributes=expand_leaf_attributes,
        )

    sub_edges = [index.edges_by_id[eid] for eid in sel_eids if eid in index.edges_by_id]
    sub_node_ids = list(
        dict.fromkeys(
            ep
            for eid in sel_eids
            if eid in index.edge_endpoints
            for ep in index.edge_endpoints[eid]
            if ep in index.nodes_by_id
        )
    )
    for s_id in seeds:
        if s_id in index.nodes_by_id and s_id not in sub_node_ids:
            sub_node_ids.insert(0, s_id)

    sub_nodes = [index.nodes_by_id[nid] for nid in sub_node_ids]
    seed_set = set(seeds)
    steiner_set = set(steiners)

    textualized, paths, extractive = _build_textualized_graph_and_paths(
        index, sub_nodes, sub_edges, seed_set, steiner_set
    )
    num_comps, lcc_pct = _count_connected_components(sub_nodes, sub_edges)
    dt_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    return SubgraphRetrievalResult(
        query=query,
        method=method,
        nodes=sub_nodes,
        edges=sub_edges,
        seed_node_ids=[nid for nid in seeds if nid in sub_node_ids],
        steiner_node_ids=[nid for nid in steiners if nid in sub_node_ids],
        attribute_node_ids=[nid for nid in attrs if nid in sub_node_ids],
        node_prizes=n_prizes,
        edge_prizes=e_prizes,
        textualized_graph=textualized,
        reasoning_paths=paths,
        extractive_summary=extractive,
        latency_ms=dt_ms,
        stats={
            "total_graph_nodes": len(index.nodes_by_id),
            "total_graph_edges": len(index.edges_by_id),
            "subgraph_nodes": len(sub_nodes),
            "subgraph_edges": len(sub_edges),
            "connected_components": num_comps,
            "lcc_ratio_pct": lcc_pct,
            "estimated_prompt_tokens": len(textualized) // 3,
        },
    )


def answer_question_with_graph(
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
    """Gửi Textualized Subgraph + Câu hỏi vào LLM (DeepSeek / OpenAI / Qwen) để sinh câu trả lời có trích dẫn nguồn."""
    if isinstance(subgraph_or_project, SubgraphRetrievalResult):
        subgraph_res = subgraph_or_project
    else:
        subgraph_res = retrieve_subgraph(
            subgraph_or_project,
            query,
            method=method,
            max_edges=max_edges,
            approved_only=approved_only,
        )

    effective_client = llm_client or client
    effective_max_out = max_output_tokens or max_tokens

    topic_clause = f" chuyên sâu về {domain_topic.strip()}" if domain_topic and domain_topic.strip() else ""
    system_prompt = (
        f"Bạn là hệ thống hỏi đáp Đồ thị Tri thức G-Retriever{topic_clause}. "
        "Nhiệm vụ của bạn là trả lời câu hỏi của người dùng CHỈ dựa trên 'ĐỒ THỊ CON TRUY XUẤT (NODES & EDGES)' "
        "và 'BẰNG CHỨNG NGUYÊN VĂN' được cung cấp bên dưới.\n"
        "Quy tắc bắt buộc:\n"
        "1. Trả lời trực diện, đầy đủ, mạch lạc bằng tiếng Việt.\n"
        "2. Nêu rõ chuỗi suy luận trên đồ thị (ví dụ: Thực thể A -> [quan hệ] -> Thực thể B -> [quan hệ] -> Thực thể C).\n"
        "3. Mọi thông tin, số liệu, mốc thời gian đưa ra PHẢI trích dẫn mã cạnh [E#] hoặc tên tài liệu nguồn ở cuối câu.\n"
        "4. Tuyệt đối không tự bịa đặt thông tin nằm ngoài đồ thị con được cung cấp."
    )
    graph_context = str(subgraph_res.textualized_graph or "")
    if max_input_tokens > 0:
        max_graph_chars = max(600, int(max_input_tokens) * 3 - len(system_prompt) - len(subgraph_res.query) - 320)
        if len(graph_context) > max_graph_chars:
            lines = graph_context[:max_graph_chars].splitlines()
            if len(lines) > 1:
                lines = lines[:-1]
            graph_context = "\n".join(lines) + "\n... [Đã rút gọn ngữ cảnh đồ thị theo giới hạn max_input_tokens]"

    user_prompt = (
        f"CÂU HỎI NGƯỜI DÙNG:\n{subgraph_res.query}\n\n"
        f"PHƯƠNG PHÁP TRUY XUẤT ĐỒ THỊ CON: {subgraph_res.method.upper()}\n\n"
        f"{graph_context}\n\n"
        "Hãy phân tích các đỉnh/cạnh liên quan, chỉ rõ đường đi suy luận và trả lời câu hỏi kèm trích dẫn nguồn."
    )

    if effective_client is not None and hasattr(effective_client, "chat_text"):
        t0 = time.perf_counter()
        ans_text = str(
            effective_client.chat_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=effective_max_out,
            )
        ).strip()
        llm_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "retrieval": subgraph_res.to_dict(),
            "answer": ans_text,
            "used_llm": True,
            "llm_error": "",
            "input_tokens": len(user_prompt) // 3,
            "output_tokens": len(ans_text) // 3,
            "llm_latency_ms": llm_ms,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }

    spec = providers.provider_spec(provider)
    try:
        LLMGateway._validate_credentials(spec, api_key, model, effective_client)
    except Exception as exc:
        return {
            "retrieval": subgraph_res.to_dict(),
            "answer": subgraph_res.extractive_summary,
            "used_llm": False,
            "llm_error": str(exc),
            "input_tokens": 0,
            "output_tokens": 0,
            "llm_latency_ms": 0.0,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }

    t0 = time.perf_counter()
    try:
        adapter = make_adapter(
            spec,
            api_key,
            providers.resolve_base_url(provider, base_url),
            client=effective_client,
            timeout=90.0,
        )
        resp = adapter.chat(
            model=model,
            system=system_prompt,
            user=user_prompt,
            temperature=temperature,
            max_tokens=effective_max_out,
        )
        llm_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return {
            "retrieval": subgraph_res.to_dict(),
            "answer": resp.content.strip(),
            "used_llm": True,
            "llm_error": "",
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "llm_latency_ms": llm_ms,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
    except Exception as exc:
        return {
            "retrieval": subgraph_res.to_dict(),
            "answer": subgraph_res.extractive_summary,
            "used_llm": False,
            "llm_error": str(exc),
            "input_tokens": 0,
            "output_tokens": 0,
            "llm_latency_ms": round((time.perf_counter() - t0) * 1000.0, 1),
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }


from backend.domain.graph.qa_generator import (
    generate_qa_benchmark,
    generate_training_qa_dataset,
    paraphrase_qa_questions_with_llm,
)


def evaluate_retrieval_methods(
    project: dict[str, Any],
    benchmark_items: list[dict[str, Any]] | None = None,
    *,
    max_edges: int = 15,
    approved_only: bool = True,
) -> dict[str, Any]:
    """Chạy thực nghiệm đối sánh tự động 3 phương pháp: Naive Top-K vs HippoRAG (PPR) vs G-Retriever (PCST)."""
    items = benchmark_items if benchmark_items is not None else generate_qa_benchmark(project, num_questions=18, approved_only=approved_only)
    methods = [
        ("naive_topk", "1. Baseline (Naive Top-K Triples)"),
        ("ppr", "2. HippoRAG (Personalized PageRank)"),
        ("pcst", "3. G-Retriever (Hub-Penalized PCST + 1-Hop)"),
    ]

    summary_rows: list[dict[str, Any]] = []
    detailed_rows: list[dict[str, Any]] = []

    for m_code, m_label in methods:
        target_hits = 0
        edge_recall_sum = 0.0
        two_hop_total = 0
        two_hop_full_hits = 0
        lcc_sum = 0.0
        latency_sum = 0.0
        tokens_sum = 0

        for item in items:
            res = retrieve_subgraph(
                project,
                item["question"],
                method=m_code,
                max_edges=max_edges,
                approved_only=approved_only,
            )
            ret_nids = {str(n["id"]) for n in res.nodes}
            ret_eids = {str(e["id"]) for e in res.edges}
            gold_eids = set(item.get("gold_edge_ids") or [])
            target_id = str(item.get("target_entity_id") or "")

            hit_target = 1 if (target_id and target_id in ret_nids) else 0
            target_hits += hit_target

            e_rec = (len(gold_eids & ret_eids) / len(gold_eids)) if gold_eids else 1.0
            edge_recall_sum += e_rec

            is_2hop = "2-Hop" in str(item.get("type", ""))
            if is_2hop:
                two_hop_total += 1
                if gold_eids.issubset(ret_eids):
                    two_hop_full_hits += 1

            lcc_sum += float(res.stats.get("lcc_ratio_pct", 0.0))
            latency_sum += res.latency_ms
            tokens_sum += int(res.stats.get("estimated_prompt_tokens", 0))

            detailed_rows.append(
                {
                    "Mã câu hỏi": item["id"],
                    "Loại câu hỏi": item["type"],
                    "Phương pháp": m_label,
                    "Câu hỏi": item["question"],
                    "Đáp án chuẩn (Đường đi)": item["gold_answer"],
                    "Thu hồi Cạnh chuẩn (%)": round(e_rec * 100.0, 1),
                    "Tìm trúng Đích": "✅ Có" if hit_target else "❌ Không",
                    "Liên thông LCC (%)": res.stats.get("lcc_ratio_pct", 0.0),
                    "Thời gian (ms)": res.latency_ms,
                }
            )

        n_q = max(1, len(items))
        summary_rows.append(
            {
                "Phương pháp": m_label,
                "Mã": m_code,
                "Số câu hỏi": len(items),
                "Thu hồi Đáp án Đích (%)": round((target_hits / n_q) * 100.0, 1),
                "Thu hồi Cạnh Chuẩn (%)": round((edge_recall_sum / n_q) * 100.0, 1),
                "Nối mạch 2-Hop Bridge (%)": round((two_hop_full_hits / max(1, two_hop_total)) * 100.0, 1),
                "Độ liên thông Đồ thị con (%)": round(lcc_sum / n_q, 1),
                "Token Ngữ cảnh TB": round(tokens_sum / n_q),
                "Thời gian Truy xuất TB (ms)": round(latency_sum / n_q, 2),
            }
        )

    return {
        "benchmark_items": items,
        "summary_table": summary_rows,
        "detailed_results": detailed_rows,
        "per_question": detailed_rows,
    }
