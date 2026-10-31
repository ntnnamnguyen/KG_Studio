"""Lưu trữ và truy vấn nhanh trên cơ sở dữ liệu SQLite (data/kg_studio.db)."""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
import sqlite3
from pathlib import Path

from shared.config_loader import APP_ROOT
from shared.constants import STATUS_APPROVED
from shared.schemas.project import ProjectSummaryDTO

DEFAULT_SQLITE_PATH = APP_ROOT / "data" / "kg_studio.db"


class SQLiteProjectRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_SQLITE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(str(self.db_path))) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    extraction_mode TEXT NOT NULL DEFAULT 'closed',
                    saved_at TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (project_id, id)
                );

                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    evidence_found INTEGER NOT NULL DEFAULT 0,
                    doc_id TEXT NOT NULL DEFAULT '',
                    doc_name TEXT NOT NULL DEFAULT '',
                    chunk_number INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'Chờ duyệt',
                    extraction_mode TEXT NOT NULL DEFAULT 'closed',
                    PRIMARY KEY (project_id, id)
                );

                CREATE TABLE IF NOT EXISTS schema_proposals (
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    definition TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    canonical_name TEXT NOT NULL DEFAULT '',
                    auto_aligned INTEGER NOT NULL DEFAULT 0,
                    alignment_score REAL NOT NULL DEFAULT 0.0,
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (project_id, id)
                );

                -- CHỈ MỤC TỐI ƯU HIỆU NĂNG CHO CÁC ĐƯỜNG TRUY VẤN VÀ PHÂN TRANG (Mục 7.3)
                CREATE INDEX IF NOT EXISTS idx_edges_status_page ON edges(project_id, status, chunk_number, id);
                CREATE INDEX IF NOT EXISTS idx_edges_doc_page ON edges(project_id, doc_id, chunk_number, id);
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(project_id, source, id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(project_id, target, id);
                CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(project_id, relation, id);
                CREATE INDEX IF NOT EXISTS idx_nodes_kind_name ON nodes(project_id, kind, id);
                CREATE INDEX IF NOT EXISTS idx_proposals_kind_status ON schema_proposals(project_id, kind, status, id);
                """
            )

    def sync_from_project_dict(self, project: dict) -> None:
        project_id = str(project.get("project_id") or "")
        name = str(project.get("name") or "")
        if not project_id or not name:
            return
        mode = str(project.get("extraction_mode") or "closed")
        saved_at = str(project.get("saved_at") or "")
        raw_json = json.dumps(project, ensure_ascii=False)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (project_id, name, extraction_mode, saved_at, raw_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name = excluded.name,
                    extraction_mode = excluded.extraction_mode,
                    saved_at = excluded.saved_at,
                    raw_json = excluded.raw_json
                """,
                (project_id, name, mode, saved_at, raw_json),
            )
            conn.execute("DELETE FROM nodes WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM edges WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM schema_proposals WHERE project_id = ?", (project_id,))

            conn.executemany(
                """
                INSERT INTO nodes (id, project_id, name, kind, description, aliases_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(n.get("id", "")),
                        project_id,
                        str(n.get("name", "")),
                        str(n.get("kind", "")),
                        str(n.get("description", "")),
                        json.dumps(n.get("aliases", []), ensure_ascii=False),
                    )
                    for n in project.get("nodes", [])
                    if n.get("id")
                ],
            )
            conn.executemany(
                """
                INSERT INTO edges (
                    id, project_id, source, target, relation, evidence,
                    evidence_found, doc_id, doc_name, chunk_number, status, extraction_mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(e.get("id", "")),
                        project_id,
                        str(e.get("source", "")),
                        str(e.get("target", "")),
                        str(e.get("relation", "")),
                        str(e.get("evidence", "")),
                        1 if e.get("evidence_found") else 0,
                        str(e.get("doc_id", "")),
                        str(e.get("doc_name", "")),
                        int(e.get("chunk_number", 0) or 0),
                        str(e.get("status", "")),
                        str(e.get("extraction_mode", mode)),
                    )
                    for e in project.get("edges", [])
                    if e.get("id")
                ],
            )
            conn.executemany(
                """
                INSERT INTO schema_proposals (
                    id, project_id, kind, name, definition, status,
                    canonical_name, auto_aligned, alignment_score, candidates_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(p.get("id", "")),
                        project_id,
                        str(p.get("kind", "")),
                        str(p.get("name", "")),
                        str(p.get("definition", "")),
                        str(p.get("status", "pending")),
                        str(p.get("canonical_name", "")),
                        1 if p.get("auto_aligned") else 0,
                        float(p.get("alignment_score", 0.0) or 0.0),
                        json.dumps(p.get("alignment_candidates", []), ensure_ascii=False),
                    )
                    for p in project.get("schema_proposals", [])
                    if p.get("id")
                ],
            )

    def query_edges(self, project_id: str, *, status: str | None = None, relation: str | None = None, limit: int = 500) -> list[dict]:
        clauses = ["project_id = ?"]
        params: list = [project_id]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if relation:
            clauses.append("relation = ?")
            params.append(relation)
        params.append(limit)
        sql = f"SELECT * FROM edges WHERE {' AND '.join(clauses)} ORDER BY chunk_number ASC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def query_edges_page(
        self,
        project_id: str,
        *,
        status: str | None = None,
        doc_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Truy vấn trang cạnh quan hệ sử dụng chỉ mục idx_edges_status_page / idx_edges_doc_page."""
        clauses = ["project_id = ?"]
        params: list = [project_id]
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if doc_id and doc_id != "all":
            clauses.append("doc_id = ?")
            params.append(doc_id)

        where_clause = " AND ".join(clauses)
        page_size = max(1, min(int(page_size), 200))
        offset = (max(1, int(page)) - 1) * page_size

        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM edges WHERE {where_clause}", params).fetchone()[0]
            query_sql = f"SELECT * FROM edges WHERE {where_clause} ORDER BY chunk_number ASC, id ASC LIMIT ? OFFSET ?"
            rows = conn.execute(query_sql, params + [page_size, offset]).fetchall()
            items = [dict(r) for r in rows]

        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "items": items,
            "total_count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_project_summary(self, project: dict) -> ProjectSummaryDTO:
        edges = project.get("edges", [])
        proposals = project.get("schema_proposals", [])
        return ProjectSummaryDTO(
            project_id=str(project.get("project_id", "")),
            name=str(project.get("name", "")),
            extraction_mode=str(project.get("extraction_mode", "closed")),
            documents_count=len(project.get("documents", [])),
            nodes_count=len(project.get("nodes", [])),
            edges_count=len(edges),
            approved_edges_count=sum(1 for e in edges if e.get("status") == STATUS_APPROVED),
            pending_proposals_count=sum(1 for p in proposals if p.get("status") == "pending"),
            saved_at=str(project.get("saved_at", "")),
        )

