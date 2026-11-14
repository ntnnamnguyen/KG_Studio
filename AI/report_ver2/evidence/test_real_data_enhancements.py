"""Kiểm thử thực nghiệm trên dữ liệu thật các dự án (kg_hanoi_edc_r_a, hanoiqa6, test1)
sau khi triển khai gói tinh chỉnh:
- O1: Mở trần Top-K (Quan hệ lên 80, Loại thực thể lên 50)
- O2: Định dạng Prompt 2 tầng có [Domain -> Range] và chỉ dẫn ưu tiên nhãn chuẩn
- O3: Chuẩn hóa tên Loại thực thể (_ / - normalization)
- O4: Bổ sung Aliases vào vector passages cho Schema Index
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
from backend.repositories.json_repo import JsonProjectRepository
from backend.integrations.embedder_gateway import default_embedder, list_registered_models
from backend.repositories.vector_repo import VectorIndexRepository
from backend.domain.schema_intelligence.retriever import SchemaRetriever
from shared.text_utils import clean_entity_type_name, normal
from shared.schemas.project import EDCPlusRSettingsDTO


def run_real_data_tests() -> dict:
    repo = JsonProjectRepository(Path("data/projects"))
    projects = repo.list_projects()
    print(f"Loaded {len(projects)} real projects from data/projects/.")

    embedder = default_embedder("hybrid_vn:default")
    vector_repo = VectorIndexRepository()
    retriever = SchemaRetriever(vector_repo=vector_repo, embedder=embedder)

    results = {}

    # Test trên dự án lớn nhất: kg_hanoi_edc_r_a
    proj_name = "kg_hanoi_edc_r_a"
    proj = repo.load_project(proj_name)
    if not proj:
        proj = repo.load_project("hanoiqa6")
    edges = proj.get("edges", [])
    nodes = proj.get("nodes", [])
    docs = proj.get("documents", [])
    proposals = proj.get("schema_proposals", [])
    rels = proj.get("relations", [])
    types = proj.get("entity_types", [])

    print(f"\n--- Testing Project: {proj_name} ---")
    print(f"Documents: {len(docs)}, Nodes: {len(nodes)}, Edges: {len(edges)}, Proposals: {len(proposals)}")
    print(f"Relations catalog: {len(rels)}, Entity types catalog: {len(types)}")

    # 1. Đo lường Retrieval Recall với Top-K mở rộng
    approved_edges = [
        e for e in edges
        if e.get("status") in ("approved", "Đã duyệt") and e.get("relation") and len(e.get("evidence", "")) >= 15
    ]
    print(f"Approved edges with valid evidence: {len(approved_edges)}")

    ground_truth = []
    seen_evidence = set()
    for e in approved_edges:
        ev = e["evidence"].strip()
        rel = e["relation"].strip()
        if ev not in seen_evidence:
            seen_evidence.add(ev)
            ground_truth.append((ev, {rel}))
        else:
            for item in ground_truth:
                if item[0] == ev:
                    item[1].add(rel)
                    break
        if len(ground_truth) >= 30:
            break

    print(f"Sampled ground truth evidence texts: {len(ground_truth)}")

    k_values = [10, 15, 30, 50, len(rels)]
    recalls = {k: [] for k in k_values}

    for ev_text, gt_rels in ground_truth:
        for k in k_values:
            retrieved = retriever.retrieve_for_chunk(
                proj,
                ev_text,
                top_k_relations=k,
                top_k_entity_types=min(30, len(types)),
                embedder=embedder,
            )
            ret_names = {r["name"] for r in retrieved["relations"]}
            hits = len(gt_rels.intersection(ret_names))
            recall = hits / len(gt_rels) if gt_rels else 1.0
            recalls[k].append(recall)

    avg_recalls = {k: round(sum(v) / len(v) * 100, 2) if v else 0.0 for k, v in recalls.items()}
    print("\n[Kết quả 1: Retrieval Recall theo Top-K mở rộng]")
    for k, rec in avg_recalls.items():
        label = f"Full Catalog (Toàn bộ {len(rels)} quan hệ)" if k == len(rels) else f"Top-K={k}"
        print(f"  • {label}: Recall = {rec}%")

    results["avg_recalls"] = avg_recalls

    # 2. Kiểm tra chuẩn hóa Tên loại thực thể (Entity Types Normalization)
    print("\n[Kết quả 2: Chuẩn hóa nhãn Loại thực thể]")
    test_cases = [
        ("E21_Person", "E21 Person"),
        ("e21 person", "E21 Person"),
        ("E53-Place", "E53 Place"),
        ("e53_place", "E53 Place"),
        ("E7_Activity", "E7 Activity"),
        ("E39 Actor", "E39 Actor"),
    ]
    type_names_in_proj = {normal(t["name"]): t["name"] for t in types}
    norm_hits = 0
    for raw_input, expected_target in test_cases:
        cleaned = clean_entity_type_name(raw_input)
        matched = type_names_in_proj.get(cleaned)
        is_hit = (matched == expected_target) if expected_target in type_names_in_proj.values() else (cleaned == clean_entity_type_name(expected_target))
        if is_hit:
            norm_hits += 1
        print(f"  Input: '{raw_input}' -> Cleaned: '{cleaned}' -> Match Target: {matched or expected_target} ({'OK' if is_hit else 'FAIL'})")
    results["norm_accuracy"] = f"{norm_hits}/{len(test_cases)}"

    # 3. Kiểm tra định dạng Schema Block có Domain -> Range
    print("\n[Kết quả 3: Kiểm tra định dạng Schema Block mới]")
    sample_retrieved = retriever.retrieve_for_chunk(
        proj,
        ground_truth[0][0] if ground_truth else "Hà Nội",
        top_k_relations=5,
        top_k_entity_types=5,
        embedder=embedder,
    )
    formatted_block = retriever.format_retrieved_schema_block(sample_retrieved)
    print(formatted_block[:400] + "...\n(cắt ngắn)")
    has_priority_instruct = "Ưu tiên CHỌN NGUYÊN VĂN TÊN CHUẨN" in formatted_block
    results["has_priority_instruct"] = has_priority_instruct
    print(f"  -> Có chỉ dẫn ưu tiên nhãn chuẩn: {has_priority_instruct}")

    # 4. Kiểm tra danh mục Model Embedding
    print("\n[Kết quả 4: Danh mục Model Embedding hỗ trợ]")
    registered = list_registered_models()
    for m in registered:
        print(f"  • {m['model_id']}: {m['name']} (dim={m['dim']}, backend={m['backend']})")
    results["registered_models"] = [m["model_id"] for m in registered]

    return results


if __name__ == "__main__":
    res = run_real_data_tests()
    out_file = Path("AI/report_ver2/evidence/real_data_test_summary.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved test results to {out_file}")
