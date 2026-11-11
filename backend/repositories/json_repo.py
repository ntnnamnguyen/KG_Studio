"""Lưu trữ dự án ra đĩa dạng JSON atomic bundle + rollback + snapshots (Độc lập 100%)."""
from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from shared.catalog_utils import (
    CATALOG_FILES,
    apply_relations,
    atomic_write,
    catalog_bytes,
    parse_catalog,
    relation_catalog,
    validate_catalog,
)
from shared.config_loader import CONFIG, default_catalogs, projects_root
from shared.constants import (
    DEFAULT_EDC_PLUS_R_SETTINGS,
    DEFAULT_EDC_PROMPT,
    MODE_FIXED,
    SCHEMA_VERSION,
    STATUS_CHECK,
)
from shared.text_utils import now_iso, scrubbed, slug, uid
from backend.domain.prompts.service import ensure_project_prompt_history

from .base import ProjectRepository

PROJECT_FILE = CONFIG["storage"]["project_file"]
MANIFEST_FILE = "project.meta.json"
SNAPSHOT_DIR = CONFIG["storage"]["snapshots_dir"]
UNKNOWN_KIND = CONFIG["knowledge"]["unknown_entity_kind"]
DEFAULT_PROMPT = CONFIG["knowledge"]["system_prompt"].strip()
JOURNAL_FILE = ".commit_journal.json"
SYNC_PENDING_FILE = ".sqlite_sync_pending.json"

# In-memory registry cache theo folder path tránh lặp I/O và parse JSON trên mỗi Streamlit rerun
_PROJECT_REGISTRY_CACHE: dict[str, dict[str, Any]] = {}


def empty_project(name: str) -> dict:
    """Tạo dự án rỗng với đầy đủ trường chuẩn của KG Studio."""
    clean_name = (name or "").strip() or CONFIG["app"]["default_project_name"]
    catalogs = default_catalogs()
    data = {
        "project_id": uid(),
        "name": clean_name,
        "documents": [],
        "nodes": [],
        "edges": [],
        "runs": [],
        "chunk_errors": {},
        "processed_chunks": {},
        "prompt": DEFAULT_PROMPT,
        "relations": [row["name"] for row in catalogs["relations"]],
        "relation_notes": {
            row["name"]: {"description": row["description"], "definition": row["definition"]}
            for row in catalogs["relations"]
        },
        "entity_types": copy.deepcopy(catalogs["entity_types"]),
        "extraction_mode": MODE_FIXED,
        "edc_prompt": DEFAULT_EDC_PROMPT,
        "edc_plus_r_settings": copy.deepcopy(DEFAULT_EDC_PLUS_R_SETTINGS),
        "schema_proposals": [],
        "schema_decisions": [],
        "schema_decision_batches": [],
        "edc_idempotency_store": {},
        "curation_history": [],
        "curation_decision_batches": [],
        "curation_idempotency_store": {},
        "entity_merges": [],
        "node_redirects": {},
        "not_duplicate_pairs": [],
        "prompt_history_schema_version": 1,
        "prompt_bindings": {},
        "prompt_versions": [],
        "created_at": now_iso(),
        "saved_at": now_iso(),
        "schema_version": SCHEMA_VERSION,
        "version": SCHEMA_VERSION,
    }
    ensure_project_prompt_history(data)
    return data


def ensure_project_shape(project: dict, name: str = "") -> dict:
    """Bổ sung các trường còn thiếu để tương thích với cả dự án mới lẫn dự án di chuyển từ bản cũ."""
    base = empty_project(name or project.get("name", "Dự án mới"))
    for key, value in base.items():
        if key not in project:
            project[key] = copy.deepcopy(value)
    if not project.get("project_id"):
        project["project_id"] = uid()
    project["schema_version"] = SCHEMA_VERSION
    project["version"] = SCHEMA_VERSION
    if not isinstance(project.get("schema_decision_batches"), list):
        project["schema_decision_batches"] = []
    if not isinstance(project.get("edc_idempotency_store"), dict):
        project["edc_idempotency_store"] = {}
    if not isinstance(project.get("curation_history"), list):
        project["curation_history"] = []
    if not isinstance(project.get("curation_decision_batches"), list):
        project["curation_decision_batches"] = []
    if not isinstance(project.get("curation_idempotency_store"), dict):
        project["curation_idempotency_store"] = {}
    if not isinstance(project.get("entity_merges"), list):
        project["entity_merges"] = []
    if not isinstance(project.get("node_redirects"), dict):
        project["node_redirects"] = {}
    if not isinstance(project.get("not_duplicate_pairs"), list):
        project["not_duplicate_pairs"] = []

    for doc in project.get("documents", []):
        doc.setdefault("place_scope", "")
        doc.setdefault("source_label", "")
        doc.setdefault("pages", [])
        doc.setdefault("warnings", [])
        doc.setdefault("chars", len(doc.get("text", "")))
    for node in project.get("nodes", []):
        node.setdefault("aliases", [])
        node.setdefault("documents", [])
        node.setdefault("description", "")
        node.setdefault("kind", UNKNOWN_KIND)
    for edge in project.get("edges", []):
        edge.setdefault("evidence_found", False)
        edge.setdefault("status", STATUS_CHECK)
        edge.setdefault("review_note", "")
        edge.setdefault("override", False)
        edge.setdefault("chunk_hash", "")
        edge.setdefault("start_char", None)
        edge.setdefault("end_char", None)
        edge.setdefault("page", None)
    for prop in project.get("schema_proposals", []):
        prop.setdefault("description", "")
        prop.setdefault("status", "pending")
        prop.setdefault("canonical_name", "")
        prop.setdefault("auto_aligned", False)
        prop.setdefault("decision_origin", "auto_align" if prop.get("auto_aligned") else ("human" if prop.get("status") in ("approved", "merged", "rejected") else ""))
        prop.setdefault("alignment_candidates", [])
        prop.setdefault("alignment_score", 0.0)
        prop.setdefault("observations", [])

    if not isinstance(project.get("edc_plus_r_settings"), dict):
        project["edc_plus_r_settings"] = copy.deepcopy(DEFAULT_EDC_PLUS_R_SETTINGS)
    else:
        for k, v in DEFAULT_EDC_PLUS_R_SETTINGS.items():
            project["edc_plus_r_settings"].setdefault(k, v)

    apply_relations(project, relation_catalog(project))
    project["entity_types"] = validate_catalog(project["entity_types"], "entity_types")
    ensure_project_prompt_history(project)
    return project


class JsonProjectRepository(ProjectRepository):
    """Lưu trữ dự án trong ``data/projects/<slug>/`` hoàn toàn độc lập với cơ chế rollback bộ file."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        writer_fn: Callable[[Path, bytes], None] | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else projects_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._writer_fn: Callable[[Path, bytes], None] = writer_fn or atomic_write

    def _get_manifest(self, folder: Path) -> dict[str, Any] | None:
        """Đọc hoặc tạo metadata manifest nhỏ (project.meta.json) cho thư mục dự án."""
        data_file = folder / PROJECT_FILE
        if not data_file.exists():
            return None
        try:
            stat_res = data_file.stat()
            mtime_ns = stat_res.st_mtime_ns
            file_size = stat_res.st_size
        except OSError:
            return None

        folder_key = str(folder.resolve())
        cached = _PROJECT_REGISTRY_CACHE.get(folder_key)
        if cached and cached.get("mtime_ns") == mtime_ns and cached.get("size") == file_size:
            return cached

        meta_file = folder / MANIFEST_FILE
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if isinstance(meta, dict) and meta.get("mtime_ns") == mtime_ns and meta.get("name"):
                    _PROJECT_REGISTRY_CACHE[folder_key] = meta
                    return meta
            except (OSError, json.JSONDecodeError):
                pass

        # Bootstrap manifest bằng một lần đọc có kiểm soát
        try:
            data = json.loads(data_file.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                return None
            meta = {
                "project_id": str(data.get("project_id") or ""),
                "name": str(data.get("name") or folder.name),
                "folder": folder.name,
                "schema_version": str(data.get("schema_version") or data.get("version") or "2.0.0"),
                "saved_at": str(data.get("saved_at") or ""),
                "documents_count": len(data.get("documents", [])),
                "nodes_count": len(data.get("nodes", [])),
                "edges_count": len(data.get("edges", [])),
                "mtime_ns": mtime_ns,
                "size": file_size,
            }
            try:
                atomic_write(meta_file, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
            except Exception:
                pass
            _PROJECT_REGISTRY_CACHE[folder_key] = meta
            return meta
        except (OSError, json.JSONDecodeError):
            return None

    def _folder_name_of(self, folder: Path) -> str:
        meta = self._get_manifest(folder)
        return str(meta.get("name") or "") if meta else ""

    def list_project_headers(self) -> list[dict[str, Any]]:
        """Trả về danh sách metadata tóm tắt của các dự án (không parse full project.json)."""
        if not self.root.is_dir():
            return []
        headers: list[dict[str, Any]] = []
        for folder in sorted(self.root.iterdir()):
            if folder.is_dir():
                meta = self._get_manifest(folder)
                if meta and meta.get("name"):
                    headers.append(meta)
        return headers

    def find_folder(self, name: str) -> Path | None:
        preferred = self.root / slug(name)
        if preferred.is_dir() and self._folder_name_of(preferred) == name:
            return preferred
        if not self.root.is_dir():
            return None
        for folder in sorted(self.root.iterdir()):
            if folder.is_dir() and self._folder_name_of(folder) == name:
                return folder
        return None

    def project_dir(self, name: str) -> Path:
        found = self.find_folder(name)
        return found if found else (self.root / slug(name))

    def project_exists(self, name: str) -> bool:
        return self.find_folder(name) is not None

    def list_projects(self) -> list[str]:
        if not self.root.is_dir():
            return []
        names: list[str] = []
        for folder in sorted(self.root.iterdir()):
            if folder.is_dir():
                name = self._folder_name_of(folder)
                if name and name not in names:
                    names.append(name)
        return names

    def _recover_journal_if_needed(self, folder: Path) -> None:
        journal_path = folder / JOURNAL_FILE
        if not journal_path.exists():
            return
        bak_files_to_clean: list[Path] = []
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            files_backup = journal.get("files", {})
            for filename, entry in files_backup.items():
                target = folder / filename
                if isinstance(entry, dict):
                    bak_name = str(entry.get("bak") or "")
                    bak_path = folder / bak_name if bak_name else None
                    if bak_path is not None:
                        bak_files_to_clean.append(bak_path)
                    if not entry.get("existed"):
                        target.unlink(missing_ok=True)
                    elif bak_path is not None and bak_path.exists():
                        bak_path.replace(target)
                elif entry is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write(target, str(entry).encode("utf-8"))
        except Exception:
            pass
        finally:
            journal_path.unlink(missing_ok=True)
            for bp in bak_files_to_clean:
                bp.unlink(missing_ok=True)
            for leftover in folder.glob(".*.journal.bak"):
                leftover.unlink(missing_ok=True)

    def load_project(self, name: str) -> dict:
        folder = self.project_dir(name)
        self._recover_journal_if_needed(folder)
        path = folder / PROJECT_FILE
        if not path.exists():
            return empty_project(name)
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(obj, dict):
            raise ValueError("project.json không phải JSON object")
        if name:
            obj["name"] = name
        for key, filename in CATALOG_FILES.items():
            cat_file = folder / filename
            if cat_file.exists():
                rows = parse_catalog(cat_file.read_bytes(), key)
                if key == "relations":
                    apply_relations(obj, rows)
                else:
                    obj[key] = rows
        pending_info = self.get_sync_pending(name or obj.get("name", ""))
        obj["sync_pending"] = bool(pending_info)
        obj["sync_error"] = str(pending_info.get("error", "")) if pending_info else ""
        return ensure_project_shape(obj, name or obj.get("name", "Dự án mới"))

    def save_project(self, project: dict) -> Path:
        name = project["name"]
        folder = self.find_folder(name)
        if folder is None:
            base = slug(name)
            folder = self.root / base
            if folder.exists() and self._folder_name_of(folder) not in ("", name):
                for idx in range(2, 1000):
                    candidate_dir = self.root / f"{base}_{idx}"
                    if not candidate_dir.exists():
                        folder = candidate_dir
                        break

        folder.mkdir(parents=True, exist_ok=True)
        catalogs = {
            "relations": validate_catalog(relation_catalog(project), "relations"),
            "entity_types": validate_catalog(project.get("entity_types", []), "entity_types"),
        }
        candidate = dict(project)
        apply_relations(candidate, catalogs["relations"])
        candidate["entity_types"] = catalogs["entity_types"]
        candidate["saved_at"] = now_iso()
        candidate["schema_version"] = SCHEMA_VERSION

        bundle_targets: list[tuple[str, Path, bytes]] = [
            (
                PROJECT_FILE,
                folder / PROJECT_FILE,
                json.dumps(scrubbed(candidate), ensure_ascii=False).encode("utf-8"),
            ),
            (
                CATALOG_FILES["relations"],
                folder / CATALOG_FILES["relations"],
                catalog_bytes(catalogs["relations"], "relations"),
            ),
            (
                CATALOG_FILES["entity_types"],
                folder / CATALOG_FILES["entity_types"],
                catalog_bytes(catalogs["entity_types"], "entity_types"),
            ),
        ]

        journal_files: dict[str, dict[str, Any]] = {}
        bak_paths: list[Path] = []
        for filename, target_path, _ in bundle_targets:
            bak_path = folder / f".{filename}.journal.bak"
            bak_paths.append(bak_path)
            if target_path.exists():
                shutil.copyfile(target_path, bak_path)
                journal_files[filename] = {"existed": True, "bak": bak_path.name}
            else:
                bak_path.unlink(missing_ok=True)
                journal_files[filename] = {"existed": False, "bak": ""}

        journal_path = folder / JOURNAL_FILE
        atomic_write(
            journal_path,
            json.dumps({"version": 2, "at": now_iso(), "files": journal_files}, ensure_ascii=False).encode("utf-8"),
        )

        try:
            for _, target_path, payload_bytes in bundle_targets:
                self._writer_fn(target_path, payload_bytes)
        except Exception:
            for filename, target_path, _ in bundle_targets:
                info = journal_files.get(filename, {})
                try:
                    if not info.get("existed"):
                        target_path.unlink(missing_ok=True)
                    else:
                        bak_p = folder / str(info.get("bak") or "")
                        if bak_p.exists():
                            bak_p.replace(target_path)
                except Exception:
                    pass
            journal_path.unlink(missing_ok=True)
            for bp in bak_paths:
                bp.unlink(missing_ok=True)
            raise

        journal_path.unlink(missing_ok=True)
        for bp in bak_paths:
            bp.unlink(missing_ok=True)

        # Cập nhật manifest metadata và in-memory registry cache sau khi ghi thành công
        try:
            target_data_file = folder / PROJECT_FILE
            stat_res = target_data_file.stat()
            meta = {
                "project_id": str(candidate.get("project_id") or ""),
                "name": str(candidate.get("name") or folder.name),
                "folder": folder.name,
                "schema_version": str(candidate.get("schema_version") or "2.0.0"),
                "saved_at": str(candidate.get("saved_at") or now_iso()),
                "documents_count": len(candidate.get("documents", [])),
                "nodes_count": len(candidate.get("nodes", [])),
                "edges_count": len(candidate.get("edges", [])),
                "mtime_ns": stat_res.st_mtime_ns,
                "size": stat_res.st_size,
            }
            atomic_write(folder / MANIFEST_FILE, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
            _PROJECT_REGISTRY_CACHE[str(folder.resolve())] = meta
        except Exception:
            pass

        if candidate is not project:
            project["relations"] = candidate["relations"]
            project["relation_notes"] = candidate["relation_notes"]
            project["entity_types"] = candidate["entity_types"]
            project["saved_at"] = candidate["saved_at"]
            project["schema_version"] = candidate["schema_version"]
        return folder / PROJECT_FILE

    def mark_sync_pending(self, project_name: str, error_msg: str) -> None:
        folder = self.project_dir(project_name)
        folder.mkdir(parents=True, exist_ok=True)
        payload = {"at": now_iso(), "project_name": project_name, "error": str(error_msg)}
        atomic_write(folder / SYNC_PENDING_FILE, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))

    def clear_sync_pending(self, project_name: str) -> None:
        folder = self.project_dir(project_name)
        (folder / SYNC_PENDING_FILE).unlink(missing_ok=True)

    def get_sync_pending(self, project_name: str) -> dict | None:
        folder = self.project_dir(project_name)
        marker = folder / SYNC_PENDING_FILE
        if not marker.exists():
            return None
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            return {"at": "", "project_name": project_name, "error": "Pending SQLite sync"}

    def create_snapshot(self, project: dict, *, copy_from_disk_if_clean: bool = False) -> Path:
        folder = self.project_dir(project["name"])
        project_file_path = folder / PROJECT_FILE
        if not project_file_path.exists():
            self.save_project(project)
        snap_dir = folder / SNAPSHOT_DIR
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_path = snap_dir / f'{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")}.json'
        if copy_from_disk_if_clean and project_file_path.exists():
            shutil.copy2(project_file_path, snap_path)
            return snap_path
        atomic_write(snap_path, json.dumps(scrubbed(project), ensure_ascii=False).encode("utf-8"))
        return snap_path

    def list_snapshots(self, project: dict) -> list[Path]:
        snap_dir = self.project_dir(project["name"]) / SNAPSHOT_DIR
        return sorted(snap_dir.glob("*.json"), reverse=True) if snap_dir.exists() else []

    def restore_snapshot(self, project: dict, path: Path) -> dict:
        old = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        old["name"] = project["name"]
        old["project_id"] = project.get("project_id") or old.get("project_id") or uid()
        old = ensure_project_shape(old, project["name"])
        self.save_project(old)
        if old is not project:
            project.clear()
            project.update(old)
        return old
