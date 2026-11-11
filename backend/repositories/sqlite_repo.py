"""Lưu trữ và truy vấn nhanh trên cơ sở dữ liệu SQLite (data/kg_studio.db).

Hỗ trợ đồng bộ gia tăng (Incremental Upsert) và đóng vai trò Single Source of Truth (SSOT)
cho các truy vấn đọc, phân trang, tìm kiếm và tóm tắt thống kê.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Any

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
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
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

                -- CHỈ MỤC TỐI ƯU HIỆU NĂNG CHO CÁC ĐƯỜNG TRUY VẤN VÀ PHÂN TRANG
                CREATE INDEX IF NOT EXISTS idx_edges_status_page ON edges(project_id, status, chunk_number, id);
                CREATE INDEX IF NOT EXISTS idx_edges_doc_page ON edges(project_id, doc_id, chunk_number, id);
                CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(project_id, source, id);
                CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(project_id, target, id);
                CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(project_id, relation, id);
                CREATE INDEX IF NOT EXISTS idx_nodes_kind_name ON nodes(project_id, kind, id);
                CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(project_id, name, id);
                CREATE INDEX IF NOT EXISTS idx_proposals_kind_status ON schema_proposals(project_id, kind, status, id);
                """
            )

    # =========================================================================
    # BƯỚC 1: ĐỒNG BỘ GIA TĂNG (INCREMENTAL UPSERT) & CẬP NHẬT CỤC BỘ
    # =========================================================================

    def sync_from_project_dict(self, project: dict) -> None:
        """Đồng bộ gia tăng thông minh: Upsert dữ liệu thay đổi, chỉ xóa các ID đã bị loại bỏ."""
        project_id = str(project.get("project_id") or "")
        name = str(project.get("name") or "")
        if not project_id or not name:
            return
        mode = str(project.get("extraction_mode") or "closed")
        saved_at = str(project.get("saved_at") or "")
        excluded_heavy_keys = {
            "documents",
            "nodes",
            "edges",
            "schema_proposals",
            "curation_history",
            "schema_decisions",
        }
        header_meta = {k: v for k, v in project.items() if k not in excluded_heavy_keys}
        header_meta["documents_count"] = len(project.get("documents", []))
        raw_json = json.dumps(header_meta, ensure_ascii=False)

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

            # 1. Incremental Sync cho NODES
            curr_node_ids = {str(n.get("id")) for n in project.get("nodes", []) if n.get("id")}
            db_node_ids = {row[0] for row in conn.execute("SELECT id FROM nodes WHERE project_id = ?", (project_id,)).fetchall()}
            deleted_nodes = db_node_ids - curr_node_ids
            if deleted_nodes:
                conn.executemany("DELETE FROM nodes WHERE project_id = ? AND id = ?", [(project_id, nid) for nid in deleted_nodes])

            nodes_data = [
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
            ]
            if nodes_data:
                conn.executemany(
                    """
                    INSERT INTO nodes (id, project_id, name, kind, description, aliases_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, id) DO UPDATE SET
                        name = excluded.name,
                        kind = excluded.kind,
                        description = excluded.description,
                        aliases_json = excluded.aliases_json
                    """,
                    nodes_data,
                )

            # 2. Incremental Sync cho EDGES
            curr_edge_ids = {str(e.get("id")) for e in project.get("edges", []) if e.get("id")}
            db_edge_ids = {row[0] for row in conn.execute("SELECT id FROM edges WHERE project_id = ?", (project_id,)).fetchall()}
            deleted_edges = db_edge_ids - curr_edge_ids
            if deleted_edges:
                conn.executemany("DELETE FROM edges WHERE project_id = ? AND id = ?", [(project_id, eid) for eid in deleted_edges])

            edges_data = [
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
            ]
            if edges_data:
                conn.executemany(
                    """
                    INSERT INTO edges (
                        id, project_id, source, target, relation, evidence,
                        evidence_found, doc_id, doc_name, chunk_number, status, extraction_mode
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, id) DO UPDATE SET
                        source = excluded.source,
                        target = excluded.target,
                        relation = excluded.relation,
                        evidence = excluded.evidence,
                        evidence_found = excluded.evidence_found,
                        doc_id = excluded.doc_id,
                        doc_name = excluded.doc_name,
                        chunk_number = excluded.chunk_number,
                        status = excluded.status,
                        extraction_mode = excluded.extraction_mode
                    """,
                    edges_data,
                )

            # 3. Incremental Sync cho SCHEMA PROPOSALS
            curr_prop_ids = {str(p.get("id")) for p in project.get("schema_proposals", []) if p.get("id")}
            db_prop_ids = {row[0] for row in conn.execute("SELECT id FROM schema_proposals WHERE project_id = ?", (project_id,)).fetchall()}
            deleted_props = db_prop_ids - curr_prop_ids
            if deleted_props:
                conn.executemany("DELETE FROM schema_proposals WHERE project_id = ? AND id = ?", [(project_id, pid) for pid in deleted_props])

            props_data = [
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
            ]
            if props_data:
                conn.executemany(
                    """
                    INSERT INTO schema_proposals (
                        id, project_id, kind, name, definition, status,
                        canonical_name, auto_aligned, alignment_score, candidates_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id, id) DO UPDATE SET
                        kind = excluded.kind,
                        name = excluded.name,
                        definition = excluded.definition,
                        status = excluded.status,
                        canonical_name = excluded.canonical_name,
                        auto_aligned = excluded.auto_aligned,
                        alignment_score = excluded.alignment_score,
                        candidates_json = excluded.candidates_json
                    """,
                    props_data,
                )

    def update_edge_status(self, project_id: str, edge_id: str, status: str) -> bool:
        """Cập nhật trạng thái một cạnh trong SQLite tức thì O(1)."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE edges SET status = ? WHERE project_id = ? AND id = ?",
                (status, project_id, edge_id),
            )
            return cur.rowcount > 0

    def update_edges_status(self, project_id: str, edge_ids: list[str], status: str) -> int:
        """Cập nhật trạng thái hàng loạt cạnh trong 1 transaction duy nhất."""
        if not edge_ids:
            return 0
        with self._connect() as conn:
            cur = conn.executemany(
                "UPDATE edges SET status = ? WHERE project_id = ? AND id = ?",
                [(status, project_id, eid) for eid in edge_ids],
            )
            return cur.rowcount

    def update_node_profile(
        self,
        project_id: str,
        node_id: str,
        *,
        name: str | None = None,
        kind: str | None = None,
        description: str | None = None,
        aliases: list[str] | None = None,
    ) -> bool:
        """Cập nhật thông tin hồ sơ một thực thể trong SQLite."""
        updates = []
        params = []
        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if kind is not None:
            updates.append("kind = ?")
            params.append(kind)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if aliases is not None:
            updates.append("aliases_json = ?")
            params.append(json.dumps(aliases, ensure_ascii=False))

        if not updates:
            return False

        params.extend([project_id, node_id])
        sql = f"UPDATE nodes SET {', '.join(updates)} WHERE project_id = ? AND id = ?"
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return cur.rowcount > 0

    def update_proposal_status(
        self,
        project_id: str,
        proposal_id: str,
        status: str,
        canonical_name: str = "",
    ) -> bool:
        """Cập nhật trạng thái quyết định của một đề xuất schema."""
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE schema_proposals
                SET status = ?, canonical_name = CASE WHEN ? != '' THEN ? ELSE canonical_name END
                WHERE project_id = ? AND id = ?
                """,
                (status, canonical_name, canonical_name, project_id, proposal_id),
            )
            return cur.rowcount > 0

    def delete_nodes(self, project_id: str, node_ids: list[str]) -> int:
        """Xóa các thực thể đã gộp trong SQLite."""
        if not node_ids:
            return 0
        with self._connect() as conn:
            cur = conn.executemany(
                "DELETE FROM nodes WHERE project_id = ? AND id = ?",
                [(project_id, nid) for nid in node_ids],
            )
            return cur.rowcount

    def delete_edges(self, project_id: str, edge_ids: list[str]) -> int:
        """Xóa các cạnh trùng lặp trong SQLite."""
        if not edge_ids:
            return 0
        with self._connect() as conn:
            cur = conn.executemany(
                "DELETE FROM edges WHERE project_id = ? AND id = ?",
                [(project_id, eid) for eid in edge_ids],
            )
            return cur.rowcount

    # =========================================================================
    # BƯỚC 2: SINGLE SOURCE OF TRUTH (SSOT) - TRUY VẤN, PHÂN TRANG VÀ TÓM TẮT
    # =========================================================================

    def get_project_summary(self, project_or_id: dict | str) -> ProjectSummaryDTO:
        """Lấy tóm tắt dự án siêu tốc: Đọc trực tiếp từ SQLite aggregations nếu có."""
        if isinstance(project_or_id, str):
            pid_or_name = project_or_id.strip()
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT
                        p.project_id,
                        p.name,
                        p.extraction_mode,
                        p.saved_at,
                        p.raw_json,
                        (SELECT COUNT(*) FROM nodes WHERE project_id = p.project_id) AS nodes_count,
                        (SELECT COUNT(*) FROM edges WHERE project_id = p.project_id) AS edges_count,
                        (SELECT COUNT(*) FROM edges WHERE project_id = p.project_id AND status = ?) AS approved_edges_count,
                        (SELECT COUNT(*) FROM schema_proposals WHERE project_id = p.project_id AND status = 'pending') AS pending_proposals_count
                    FROM projects p
                    WHERE p.project_id = ? OR p.name = ?
                    """,
                    (STATUS_APPROVED, pid_or_name, pid_or_name),
                ).fetchone()

                if row:
                    docs_count = 0
                    try:
                        meta = json.loads(row["raw_json"])
                        docs_count = int(meta.get("documents_count", 0) or 0)
                    except Exception:
                        pass
                    return ProjectSummaryDTO(
                        project_id=str(row["project_id"]),
                        name=str(row["name"]),
                        extraction_mode=str(row["extraction_mode"]),
                        documents_count=docs_count,
                        nodes_count=int(row["nodes_count"]),
                        edges_count=int(row["edges_count"]),
                        approved_edges_count=int(row["approved_edges_count"]),
                        pending_proposals_count=int(row["pending_proposals_count"]),
                        saved_at=str(row["saved_at"]),
                    )

        # Fallback nếu truyền dict
        project = project_or_id if isinstance(project_or_id, dict) else {}
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

    def query_edges(
        self,
        project_id: str,
        *,
        status: str | None = None,
        relation: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
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
        relation: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Truy vấn trang cạnh quan hệ sử dụng chỉ mục SQLite tối ưu."""
        clauses = ["project_id = ?"]
        params: list = [project_id]
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if doc_id and doc_id != "all":
            clauses.append("doc_id = ?")
            params.append(doc_id)
        if relation and relation != "all":
            clauses.append("relation = ?")
            params.append(relation)
        if search and search.strip():
            clauses.append("(source LIKE ? OR target LIKE ? OR relation LIKE ? OR evidence LIKE ?)")
            q = f"%{search.strip()}%"
            params.extend([q, q, q, q])

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

    def query_nodes_page(
        self,
        project_id: str,
        *,
        kind: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Truy vấn trang danh sách thực thể có phân trang trên SQLite."""
        clauses = ["project_id = ?"]
        params: list = [project_id]
        if kind and kind != "all":
            clauses.append("kind = ?")
            params.append(kind)
        if search and search.strip():
            clauses.append("(name LIKE ? OR aliases_json LIKE ? OR description LIKE ?)")
            q = f"%{search.strip()}%"
            params.extend([q, q, q])

        where_clause = " AND ".join(clauses)
        page_size = max(1, min(int(page_size), 200))
        offset = (max(1, int(page)) - 1) * page_size

        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM nodes WHERE {where_clause}", params).fetchone()[0]
            query_sql = f"SELECT * FROM nodes WHERE {where_clause} ORDER BY kind ASC, name ASC LIMIT ? OFFSET ?"
            rows = conn.execute(query_sql, params + [page_size, offset]).fetchall()
            items = []
            for r in rows:
                d = dict(r)
                d["aliases"] = json.loads(d.get("aliases_json") or "[]")
                items.append(d)

        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "items": items,
            "total_count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def query_proposals_page(
        self,
        project_id: str,
        *,
        kind: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """Truy vấn trang danh sách đề xuất schema (EDC proposals)."""
        clauses = ["project_id = ?"]
        params: list = [project_id]
        if kind and kind != "all":
            clauses.append("kind = ?")
            params.append(kind)
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(clauses)
        page_size = max(1, min(int(page_size), 200))
        offset = (max(1, int(page)) - 1) * page_size

        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM schema_proposals WHERE {where_clause}", params).fetchone()[0]
            query_sql = f"SELECT * FROM schema_proposals WHERE {where_clause} ORDER BY id ASC LIMIT ? OFFSET ?"
            rows = conn.execute(query_sql, params + [page_size, offset]).fetchall()
            items = []
            for r in rows:
                d = dict(r)
                d["alignment_candidates"] = json.loads(d.get("candidates_json") or "[]")
                items.append(d)

        total_pages = max(1, (total + page_size - 1) // page_size)
        return {
            "items": items,
            "total_count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_node_by_id(self, project_id: str, node_id: str) -> dict | None:
        """Tra cứu nhanh một thực thể theo ID trực tiếp từ SQLite."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM nodes WHERE project_id = ? AND id = ?",
                (project_id, node_id),
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["aliases"] = json.loads(res.get("aliases_json") or "[]")
            return res

    def get_edge_by_id(self, project_id: str, edge_id: str) -> dict | None:
        """Tra cứu nhanh một cạnh theo ID trực tiếp từ SQLite."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM edges WHERE project_id = ? AND id = ?",
                (project_id, edge_id),
            ).fetchone()
            return dict(row) if row else None
