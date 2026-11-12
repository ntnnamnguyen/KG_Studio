"""Ports cho phân hệ Graph QA, Subgraph Retrieval & Neo4j Export."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class BaselineRunSourcePort(Protocol):
    """Read-only source implemented by the public extraction application API."""

    def read_free_triples_runs(self, project: dict, run_ids: list[str] | None = None) -> dict:
        ...


@runtime_checkable
class Neo4jPort(Protocol):
    """Port giao tiếp Neo4j database."""

    def sync_project(self, project: dict, uri: str, user: str, password: str, database: str = "neo4j", driver: Any = None) -> dict:
        ...

    def test_connection(self, uri: str, user: str, password: str, database: str = "neo4j", driver: Any = None) -> tuple[bool, str]:
        ...
