"""Cổng đồng bộ đồ thị đã duyệt sang Neo4j độc lập 100%."""
from __future__ import annotations

from shared.constants import STATUS_APPROVED
from shared.text_utils import now_iso

CONSTRAINT_ENTITY_ID = (
    "CREATE CONSTRAINT kg_studio_entity_uid IF NOT EXISTS "
    "FOR (n:ThucThe) REQUIRE n.uid IS UNIQUE"
)

MERGE_NODES = """
UNWIND $nodes AS n
MERGE (e:ThucThe {uid: n.uid})
SET e.id = n.id,
    e.ma_du_an = $project_id,
    e.ten = n.ten,
    e.loai = n.loai,
    e.mo_ta = n.mo_ta,
    e.ten_khac = n.ten_khac,
    e.tai_lieu = n.tai_lieu,
    e.cap_nhat_luc = $updated_at
"""

READ_EDGES = """
MATCH (a:ThucThe)-[r:QUAN_HE {ma_du_an: $project_id}]->(b:ThucThe)
RETURN r.id AS id, a.id AS source, b.id AS target
"""

DELETE_EDGES = """
MATCH (a:ThucThe)-[r:QUAN_HE {ma_du_an: $project_id}]->(b:ThucThe)
WHERE r.id IN $ids
DELETE r
RETURN count(r) AS removed
"""

MERGE_EDGES = """
UNWIND $edges AS e
MATCH (a:ThucThe {uid: e.source_uid})
MATCH (b:ThucThe {uid: e.target_uid})
MERGE (a)-[r:QUAN_HE {id: e.id, ma_du_an: $project_id}]->(b)
SET r.ten = e.ten,
    r.bang_chung = e.bang_chung,
    r.tai_lieu = e.tai_lieu,
    r.khoi = e.khoi,
    r.trang_thai = e.trang_thai,
    r.prompt_id = e.prompt_id,
    r.mo_hinh = e.mo_hinh,
    r.cap_nhat_luc = $updated_at
RETURN count(r) AS written
"""

DELETE_ORPHAN_NODES = """
MATCH (n:ThucThe {ma_du_an: $project_id})
WHERE NOT n.id IN $keep_ids AND NOT (n)--()
DELETE n
RETURN count(n) AS removed
"""


class Neo4jSyncError(RuntimeError):
    pass


class Neo4jGateway:
    """Cổng đồng bộ và kiểm tra kết nối Neo4j độc lập."""

    @staticmethod
    def test_connection(uri: str, user: str, password: str, database: str = "neo4j", driver=None) -> tuple[bool, str]:
        created = driver is None
        client = driver
        try:
            if created:
                from neo4j import GraphDatabase

                client = GraphDatabase.driver(uri, auth=(user, password))
            client.verify_connectivity()
            with client.session(database=database) as session:
                records = session.run("RETURN 1 AS ok").single()
            ok = bool(records and records.get("ok") == 1)
            return ok, "Kết nối Neo4j thành công." if ok else "Truy vấn thử Neo4j không trả kết quả."
        except Exception as exc:
            return False, str(exc)
        finally:
            if created and client is not None:
                client.close()

    @staticmethod
    def sync_project(
        project: dict,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver=None,
    ) -> dict:
        project_id = str(project.get("project_id", "") or "")

        def _node_uid(nid: str) -> str:
            return f"{project_id}::{nid}" if project_id else str(nid)

        def _is_exportable_edge(e: dict) -> bool:
            if e.get("status") != STATUS_APPROVED:
                return False
            has_evidence = bool(str(e.get("evidence") or "").strip())
            is_override = bool(e.get("override"))
            if not has_evidence and not is_override:
                return False
            if e.get("evidence_found") is False and not is_override:
                return False
            if e.get("source") == e.get("target"):
                if not is_override and not (
                    bool(e.get("self_loop_confirmed")) and bool(str(e.get("review_note") or "").strip())
                ):
                    return False
            return True

        edges = [e for e in project.get("edges", []) if _is_exportable_edge(e)]
        node_ids = {x for e in edges for x in (e["source"], e["target"])}
        nodes = [n for n in project.get("nodes", []) if n["id"] in node_ids]
        doc_names = {d["id"]: d.get("name", "") for d in project.get("documents", [])}

        node_rows = [
            {
                "uid": _node_uid(n["id"]),
                "id": n["id"],
                "ten": n.get("name", ""),
                "loai": n.get("kind", ""),
                "mo_ta": n.get("description", ""),
                "ten_khac": list(n.get("aliases", [])),
                "tai_lieu": [doc_names.get(d, d) for d in n.get("documents", [])],
            }
            for n in nodes
        ]
        edge_rows = [
            {
                "id": e["id"],
                "source": e["source"],
                "target": e["target"],
                "source_uid": _node_uid(e["source"]),
                "target_uid": _node_uid(e["target"]),
                "ten": e.get("relation", ""),
                "bang_chung": e.get("evidence", ""),
                "tai_lieu": e.get("doc_name", ""),
                "khoi": e.get("chunk_number", 0),
                "trang_thai": e.get("status", ""),
                "prompt_id": e.get("prompt_id", ""),
                "mo_hinh": e.get("model", ""),
            }
            for e in edges
        ]

        created = driver is None
        client = driver
        try:
            if created:
                from neo4j import GraphDatabase

                client = GraphDatabase.driver(uri, auth=(user, password))
            client.verify_connectivity()
            updated_at = now_iso()
            with client.session(database=database) as session:
                session.run(CONSTRAINT_ENTITY_ID).consume()
                existing = session.execute_read(
                    lambda tx: [dict(record) for record in tx.run(READ_EDGES, project_id=project_id)]
                )
                approved_map = {e["id"]: e for e in edges}
                delete_ids = [
                    row["id"]
                    for row in existing
                    if row.get("id") not in approved_map
                    or approved_map[row["id"]]["source"] != row.get("source")
                    or approved_map[row["id"]]["target"] != row.get("target")
                ]

                def work(tx):
                    if node_rows:
                        tx.run(MERGE_NODES, nodes=node_rows, project_id=project_id, updated_at=updated_at).consume()
                    if delete_ids:
                        tx.run(DELETE_EDGES, ids=delete_ids, project_id=project_id).consume()
                    if edge_rows:
                        tx.run(MERGE_EDGES, edges=edge_rows, project_id=project_id, updated_at=updated_at).consume()
                    tx.run(DELETE_ORPHAN_NODES, project_id=project_id, keep_ids=[n["id"] for n in nodes]).consume()

                session.execute_write(work)
            return {
                "nodes_written": len(node_rows),
                "edges_written": len(edge_rows),
                "stale_edges_removed": len(delete_ids),
                "project_id": project_id,
                "database": database,
                "warnings": [],
            }
        except Exception as exc:
            raise Neo4jSyncError(str(exc)) from exc
        finally:
            if created and client is not None:
                client.close()

