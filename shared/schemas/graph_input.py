"""Detached graph contract shared by extraction, graph algorithms and UI.

These DTOs never replace or serialize an entire project bundle.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator

from shared.schemas.base import SchemaModel
from shared.text_utils import sha

BASELINE_GRAPH_POLICY = "surface-nfc-casefold-v1"
GRAPH_FORMAT = "kg-studio.graph.v1"


def graph_fingerprint(value: Any) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


class BaselineGraphRequestDTO(SchemaModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    project_id: str
    run_ids: list[str] = Field(min_length=1)
    policy: Literal["surface-nfc-casefold-v1"] = BASELINE_GRAPH_POLICY

    @model_validator(mode="after")
    def check_scope(self):
        if not self.project_id or any(not item for item in self.run_ids):
            raise ValueError("Project và run_id phải có định danh")
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("run_id bị lặp trong lựa chọn")
        return self


class GraphSnapshotDTO(SchemaModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format: Literal["kg-studio.graph.v1"] = GRAPH_FORMAT
    project_id: str
    name: str = ""
    source: Literal["approved", "baseline", "all"]
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    fingerprint: str = ""

    @model_validator(mode="after")
    def check_graph(self):
        if not self.project_id.strip():
            raise ValueError("Graph cần project/scope identity")
        node_ids: set[str] = set()
        for node in self.nodes:
            nid = node.get("id")
            if (not isinstance(nid, str) or not nid or nid in node_ids
                    or not isinstance(node.get("name"), str) or not node["name"].strip()):
                raise ValueError("Node cần id duy nhất và name dạng chuỗi")
            node_ids.add(nid)
        edge_ids: set[str] = set()
        for edge in self.edges:
            eid = edge.get("id")
            if (not isinstance(eid, str) or not eid or eid in edge_ids
                    or not isinstance(edge.get("source"), str) or not isinstance(edge.get("target"), str)
                    or edge["source"] not in node_ids or edge["target"] not in node_ids
                    or not isinstance(edge.get("relation"), str) or not edge["relation"].strip()):
                raise ValueError("Cạnh cần id duy nhất, hai đầu mút tồn tại và relation không rỗng")
            edge_ids.add(eid)
        expected = graph_fingerprint({"project_id": self.project_id, "source": self.source,
                                      "nodes": self.nodes, "edges": self.edges,
                                      "manifest": self.manifest, "diagnostics": self.diagnostics})
        if self.fingerprint and self.fingerprint != expected:
            raise ValueError("Fingerprint graph không khớp nội dung")
        self.fingerprint = expected
        return self

    @classmethod
    def from_graph_input(cls, value: dict[str, Any]) -> GraphSnapshotDTO:
        if value.get("graph_format") != GRAPH_FORMAT:
            raise ValueError("Cần graph input đã chọn nguồn tường minh")
        return cls(project_id=value["project_id"], name=value.get("name", ""),
                   source=value["graph_source"], nodes=copy.deepcopy(value["nodes"]),
                   edges=copy.deepcopy(value["edges"]), manifest=copy.deepcopy(value.get("graph_manifest", {})),
                   diagnostics=copy.deepcopy(value.get("graph_diagnostics", [])),
                   fingerprint=value.get("graph_fingerprint", ""))

    def as_project(self) -> dict[str, Any]:
        """Compatibility input for existing graph algorithms, NOT a storage project."""
        return copy.deepcopy({
            "project_id": self.project_id, "name": self.name,
            "nodes": self.nodes, "edges": self.edges, "documents": [],
            "graph_format": self.format, "graph_source": self.source,
            "graph_fingerprint": self.fingerprint, "graph_manifest": self.manifest,
            "graph_diagnostics": self.diagnostics,
        })


class GoldFactDTO(SchemaModel):
    """Accepted surface forms are supplied by annotators, never inferred here."""
    model_config = ConfigDict(extra="forbid", strict=True)
    subject: list[str] = Field(min_length=1)
    predicate: list[str] = Field(min_length=1)
    object: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def nonempty_forms(self):
        if any(not text.strip() for forms in (self.subject, self.predicate, self.object) for text in forms):
            raise ValueError("Gold fact không được có tên rỗng")
        return self


class GraphBenchmarkItemDTO(SchemaModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    gold_facts: list[GoldFactDTO] = Field(min_length=1)

    @model_validator(mode="after")
    def nonempty_question(self):
        if not self.id.strip() or not self.question.strip():
            raise ValueError("Câu hỏi và mã câu hỏi không được rỗng")
        return self
