"""Graphviz representation shared by approved and baseline graph views."""
from __future__ import annotations

import json


def build_graph_dot(nodes: list[dict], edges: list[dict]) -> str:
    quoted = lambda text: json.dumps(str(text), ensure_ascii=False)
    lines = ["digraph KG {", 'rankdir="LR";', 'node [shape=box, style="rounded,filled", fillcolor="#eef6ff"];']
    for node in nodes:
        lines.append(f'{quoted(node["id"])} [label={quoted(node["name"])}];')
    for edge in edges:
        lines.append(f'{quoted(edge["source"])} -> {quoted(edge["target"])} [label={quoted(edge["relation"])}, id={quoted(edge["id"])}];')
    return "\n".join(lines + ["}"])
