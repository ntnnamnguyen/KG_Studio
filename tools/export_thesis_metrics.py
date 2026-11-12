"""Script tự động tổng hợp số liệu thực nghiệm đồ án (Thesis Metrics Collector).
Xuất ra bảng Markdown và số liệu thống kê cho Báo cáo Tốt nghiệp:
1. Thống kê Đồ thị (Entities, Relations, Topo, Degree, LCC).
2. Thống kê Curation & Trùng lặp (Aliases, Merged, Scoping).
3. Thống kê Lịch sử Trích xuất (Runs, Tokens, Discarded, Evidence Match).
"""
import collections
import json
import os
import sys

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from backend.bootstrap import get_container
from backend.domain.graph.service import approved_graph


def collect_project_metrics(project_id: str = "hanoi_dataset") -> dict:
    container = get_container()
    project = container.projects_service.load_project(project_id)
    if not project:
        print(f"Không tìm thấy dự án: {project_id}")
        return {}

    nodes = project.get("nodes", [])
    edges = project.get("edges", [])
    docs = project.get("documents", [])
    runs = project.get("runs", [])
    app_nodes, app_edges = approved_graph(project)

    # 1. Thống kê Corpus
    total_docs = len(docs)
    total_chunks = sum(len(d.get("chunks", [])) for d in docs)
    total_words = sum(len(d.get("text", "").split()) for d in docs)

    # 2. Thống kê Nodes & Kinds
    kind_counts = collections.Counter(str(n.get("kind") or "Chưa phân loại") for n in nodes)
    alias_count = sum(len(n.get("aliases", [])) for n in nodes)
    nodes_with_aliases = sum(1 for n in nodes if n.get("aliases"))

    # 3. Thống kê Edges & Relations & Status
    status_counts = collections.Counter(str(e.get("status") or "pending") for e in edges)
    rel_counts = collections.Counter(str(e.get("relation") or "") for e in edges)
    evidence_ok_count = sum(1 for e in edges if e.get("evidence_found"))

    # 4. Topo đồ thị
    num_nodes = len(nodes)
    num_edges = len(edges)
    avg_degree = round((2.0 * num_edges / num_nodes), 2) if num_nodes else 0.0
    density = round((2.0 * num_edges / (num_nodes * (num_nodes - 1))), 5) if num_nodes > 1 else 0.0

    # 5. Thống kê Lịch sử Runs
    run_modes = collections.Counter(r.get("extraction_mode", "closed") for r in runs)
    total_in_tokens = sum(r.get("input_tokens", 0) for r in runs)
    total_out_tokens = sum(r.get("output_tokens", 0) for r in runs)

    return {
        "project_id": project_id,
        "name": project.get("name", project_id),
        "corpus": {
            "total_docs": total_docs,
            "total_chunks": total_chunks,
            "total_words": total_words,
        },
        "graph_all": {
            "nodes": num_nodes,
            "edges": num_edges,
            "avg_degree": avg_degree,
            "density": density,
            "kind_counts": kind_counts.most_common(8),
            "top_relations": rel_counts.most_common(10),
            "status_counts": dict(status_counts),
            "evidence_ok_rate": round((evidence_ok_count / num_edges * 100), 2) if num_edges else 0.0,
            "total_aliases": alias_count,
            "nodes_with_aliases": nodes_with_aliases,
        },
        "graph_approved": {
            "nodes": len(app_nodes),
            "edges": len(app_edges),
        },
        "runs_summary": {
            "total_runs": len(runs),
            "modes": dict(run_modes),
            "total_in_tokens": total_in_tokens,
            "total_out_tokens": total_out_tokens,
        }
    }


def print_markdown_report(metrics: dict):
    if not metrics:
        return

    g = metrics["graph_all"]
    c = metrics["corpus"]
    r = metrics["runs_summary"]

    md = []
    md.append(f"# BÁO CÁO SỐ LIỆU THỰC NGHIỆM ĐỒ THỊ TRI THỨC ({metrics['name']})")
    md.append("\n## 1. THỐNG KÊ TẬP TÀI LIỆU NGUỒN (CORPUS)")
    md.append(f"- **Tổng số tài liệu văn bản ($|D|$)**: {c['total_docs']:,}")
    md.append(f"- **Tổng số đoạn văn trích xuất ($|C|$)**: {c['total_chunks']:,}")
    md.append(f"- **Tổng số từ vựng (Tokens/Words)**: {c['total_words']:,} từ")

    md.append("\n## 2. THỐNG KÊ ĐỒ THỊ TRI THỨC TOÀN PHẦN (KNOWLEDGE GRAPH)")
    md.append(f"- **Tổng số Thực thể ($|V|$)**: {g['nodes']:,}")
    md.append(f"- **Tổng số Quan hệ / Cạnh ($|E|$)**: {g['edges']:,}")
    md.append(f"- **Số cạnh đã duyệt chính thức (Approved)**: {metrics['graph_approved']['edges']:,}")
    md.append(f"- **Bậc trung bình của đỉnh (Average Degree)**: {g['avg_degree']}")
    md.append(f"- **Mật độ đồ thị (Graph Density)**: {g['density']}")
    md.append(f"- **Tỷ lệ quan hệ có bằng chứng văn bản (Evidence Grounded)**: {g['evidence_ok_rate']}%")
    md.append(f"- **Tổng số bí danh (Aliases) tích lũy**: {g['total_aliases']:,} (trên {g['nodes_with_aliases']:,} thực thể)")

    md.append("\n### Bảng Phân bố Loại Thực thể hàng đầu:")
    md.append("| Loại thực thể (`kind`) | Số lượng | Tỷ lệ (%) |")
    md.append("| :--- | :--- | :--- |")
    for kind, cnt in g["kind_counts"]:
        pct = round(cnt / g["nodes"] * 100, 1) if g["nodes"] else 0
        md.append(f"| {kind} | {cnt:,} | {pct}% |")

    md.append("\n### Bảng Phân bố Vị từ Quan hệ phổ biến nhất:")
    md.append("| Tên quan hệ (`relation`) | Số lượng | Tỷ lệ (%) |")
    md.append("| :--- | :--- | :--- |")
    for rel, cnt in g["top_relations"]:
        pct = round(cnt / g["edges"] * 100, 1) if g["edges"] else 0
        md.append(f"| {rel} | {cnt:,} | {pct}% |")

    md.append("\n### Bảng Trạng thái Duyệt Curation:")
    md.append("| Trạng thái (`status`) | Ý nghĩa | Số lượng cạnh |")
    md.append("| :--- | :--- | :--- |")
    for st, cnt in g["status_counts"].items():
        st_lower = str(st).lower()
        if st_lower in ("approved", "đã duyệt"):
            meaning = "Đã duyệt chính thức (Approved)"
        elif st_lower in ("pending", "chờ duyệt"):
            meaning = "Chờ duyệt (Pending)"
        else:
            meaning = "Cần rà soát (Check / Lệch trích dẫn / Tự trỏ)"
        md.append(f"| `{st}` | {meaning} | {cnt:,} |")

    md.append("\n## 3. THỐNG KÊ LỊCH SỬ TRÍCH XUẤT & TIÊU THỤ TOKEN")
    md.append(f"- **Tổng số lượt trích xuất (Runs)**: {r['total_runs']:,}")
    md.append(f"- **Phân bố các phương pháp trích xuất**: {r['modes']}")
    md.append(f"- **Tổng Input Tokens tiêu thụ**: {r['total_in_tokens']:,}")
    md.append(f"- **Tổng Output Tokens sinh ra**: {r['total_out_tokens']:,}")

    report_text = "\n".join(md)
    print(report_text)
    out_path = os.path.join(WORKSPACE_ROOT, "AI", "report", "thesis_empirical_metrics.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n[OK] Đã lưu báo cáo số liệu vào: {out_path}")


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "hanoi_dataset"
    metrics = collect_project_metrics(pid)
    print_markdown_report(metrics)
