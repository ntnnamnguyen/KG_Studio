"""Điều phối vòng đời Commit chuẩn (Project Commit Coordinator).
Hợp nhất điều phối commit cho toàn bộ hệ thống (EDC Proposals, Curation Review, Entity/Relation Merge):
1. Khóa theo project (RLock)
2. Kiểm tra Idempotency (chống nhấn đúp / retry lặp)
3. Kiểm tra Revision Conflict (bảo vệ đa phiên)
4. Thực thi Domain Mutation trên bản sao
5. Tạo Snapshot quay ngược thời gian (rollback nếu ghi đĩa thất bại)
6. Ghi nhận Idempotency vào candidate
7. Lưu Atomic JSON Bundle (project.json + catalogs)
8. Cập nhật In-memory state, đồng bộ an toàn SQLite Read Projection, vô hiệu hóa Vector Index (nếu cần).
"""
from __future__ import annotations

from collections.abc import Callable
import copy
from pathlib import Path
import threading
from typing import Any, TypeVar

from backend.domain.catalogs.service import catalog_rows, compute_catalog_hash, compute_project_revision
from backend.modules.projects.ports import ProjectStorePort, ReadProjectionPort
from shared.text_utils import now_iso

TResult = TypeVar("TResult")


class ProjectCommitCoordinator:
    def __init__(
        self,
        project_store: ProjectStorePort,
        read_projection: ReadProjectionPort | None = None,
        vector_repo: Any | None = None,
        get_lock: Callable[[str], threading.RLock] | None = None,
    ) -> None:
        self.project_store = project_store
        self.read_projection = read_projection
        self.vector_repo = vector_repo
        self._default_locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._get_lock = get_lock or self._get_internal_lock
        self._idempotency_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_committed_revision: dict[str, str] = {}
        self._last_disk_stat: dict[str, tuple[int, int]] = {}

    def get_project_lock(self, project_id: str) -> threading.RLock:
        """Trả về khóa đồng bộ tiến trình (process-wide RLock) cho dự án."""
        return self._get_lock(str(project_id or "default"))

    def _get_internal_lock(self, project_id: str) -> threading.RLock:
        pid = str(project_id or "default")
        with self._locks_guard:
            if pid not in self._default_locks:
                self._default_locks[pid] = threading.RLock()
            return self._default_locks[pid]

    def _project_file_stat(self, proj_name: str) -> tuple[int, int] | None:
        if not proj_name or not hasattr(self.project_store, "find_folder"):
            return None
        try:
            folder = self.project_store.find_folder(proj_name)
            if folder is None:
                return None
            p_file = folder / "project.json"
            if not p_file.exists():
                return None
            st = p_file.stat()
            return (st.st_mtime_ns, st.st_size)
        except Exception:
            return None

    def _record_disk_stat(self, proj_id: str, proj_name: str) -> None:
        st = self._project_file_stat(proj_name)
        if st is not None:
            self._last_disk_stat[proj_id] = st

    def _disk_changed_externally(self, proj_id: str, proj_name: str) -> bool:
        prev = self._last_disk_stat.get(proj_id)
        if prev is None:
            return False
        curr = self._project_file_stat(proj_name)
        if curr is None:
            return False
        return curr != prev

    def _can_copy_disk_snapshot(self, proj_id: str, proj_name: str, mem_revision: str) -> bool:
        if not proj_name:
            return False
        last_rev = self._last_committed_revision.get(proj_id)
        if not last_rev or last_rev != mem_revision:
            return False
        return not self._disk_changed_externally(proj_id, proj_name)

    def _check_revision_conflict(
        self,
        proj_id: str,
        proj_name: str,
        project: dict[str, Any],
        expected_revision: str,
    ) -> str:
        mem_rev = compute_project_revision(project)
        if not expected_revision:
            return mem_rev
        if expected_revision != mem_rev:
            raise ValueError(
                "Trạng thái dự án đã thay đổi kể từ lúc xem trước (revision mismatch). Vui lòng tải lại và xem trước lại."
            )
        last_committed_rev = self._last_committed_revision.get(proj_id)
        if last_committed_rev and last_committed_rev != mem_rev and expected_revision != last_committed_rev:
            raise ValueError(
                "Dự án đã được cập nhật bởi một phiên làm việc khác (revision mismatch). Vui lòng tải lại và xem trước lại."
            )
        if last_committed_rev and proj_name and self._disk_changed_externally(proj_id, proj_name):
            try:
                disk_proj = self.project_store.load_project(proj_name)
                disk_rev = compute_project_revision(disk_proj)
                if disk_rev != mem_rev:
                    raise ValueError(
                        "Dự án trên đĩa đã thay đổi bởi phiên khác kể từ lúc xem trước. Vui lòng xem trước lại."
                    )
            except ValueError:
                raise
            except Exception:
                pass
        return mem_rev

    def commit(
        self,
        project: dict[str, Any],
        *,
        request_id: str,
        request_hash: str,
        expected_revision: str,
        executor: Callable[[dict[str, Any]], tuple[dict[str, Any], Any]],
        idempotency_store_key: str = "curation_idempotency_store",
        result_dto_cls: Any | None = None,
        on_snapshot_created: Callable[[dict[str, Any], Any, str], None] | None = None,
        vector_invalidation_kind: str | None = None,
    ) -> Any:
        """Thực thi một transaction commit hoàn chỉnh cho dự án."""
        proj_id = str(project.get("project_id") or project.get("name") or "default")
        proj_name = str(project.get("name") or "")

        with self._get_lock(proj_id):
            # 1. Kiểm tra idempotency
            if request_id:
                cache_key_id = (f"{idempotency_store_key}:{proj_id}", request_id)
                cached = self._idempotency_cache.get(cache_key_id)
                if cached is None:
                    cached = project.get(idempotency_store_key, {}).get(request_id)
                if cached is None and proj_name and self._disk_changed_externally(proj_id, proj_name):
                    try:
                        disk_p = self.project_store.load_project(proj_name)
                        cached = disk_p.get(idempotency_store_key, {}).get(request_id)
                    except Exception:
                        cached = None
                if cached is not None:
                    if cached.get("request_hash") != request_hash:
                        raise ValueError(
                            f"request_id '{request_id}' đã được dùng cho một nội dung thao tác khác. Từ chối thực thi."
                        )
                    res_data = copy.deepcopy(cached["result"])
                    if result_dto_cls is not None and hasattr(result_dto_cls, "from_dict"):
                        replayed = result_dto_cls.from_dict(res_data)
                    else:
                        replayed = res_data
                    if hasattr(replayed, "idempotent_replay"):
                        replayed.idempotent_replay = True
                    return replayed

            # 2. Kiểm tra xung đột revision
            mem_rev = self._check_revision_conflict(proj_id, proj_name, project, expected_revision)

            # 3. Tính catalog hash trước mutation (nếu có yêu cầu vector invalidation)
            prev_cat_hash = ""
            if vector_invalidation_kind in ("relations", "entity_types"):
                prev_cat_hash = compute_catalog_hash(project, vector_invalidation_kind)

            # 4. Thực thi domain executor trên bản sao
            candidate, result = executor(project)

            # 5. Tạo Snapshot
            clean_disk = self._can_copy_disk_snapshot(proj_id, proj_name, mem_rev)
            if hasattr(self.project_store, "create_snapshot"):
                snap_path = self.project_store.create_snapshot(project, copy_from_disk_if_clean=clean_disk)
            else:
                raise RuntimeError(
                    f"Project store '{type(self.project_store).__name__}' does not support create_snapshot capability."
                )
            snap_str = str(snap_path)

            if hasattr(result, "snapshot_path"):
                result.snapshot_path = snap_str

            if on_snapshot_created is not None:
                on_snapshot_created(candidate, result, snap_str)

            # 6. Ghi thông tin idempotency vào candidate
            res_dict = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            idem_entry = {
                "request_id": request_id,
                "request_hash": request_hash,
                "at": now_iso(),
                "result": res_dict,
            }
            candidate[idempotency_store_key] = dict(candidate.get(idempotency_store_key) or {})
            candidate[idempotency_store_key][request_id] = idem_entry

            # 7. Lưu atomic JSON bundle (project.json + relations.json + entity_types.json)
            try:
                self.project_store.save_project(candidate)
            except Exception:
                if hasattr(self.project_store, "delete_snapshot"):
                    self.project_store.delete_snapshot(snap_path)
                elif isinstance(snap_path, Path):
                    snap_path.unlink(missing_ok=True)
                raise

            # 8. Cập nhật bộ nhớ sau khi JSON đã commit thành công
            if candidate is not project:
                project.clear()
                project.update(candidate)

            rev_after = getattr(result, "revision_after", None) or compute_project_revision(project)
            self._last_committed_revision[proj_id] = rev_after
            self._record_disk_stat(proj_id, str(project.get("name") or proj_name))

            # 9. Vô hiệu hóa vector index nếu catalog thay đổi
            if vector_invalidation_kind in ("relations", "entity_types"):
                new_cat_hash = compute_catalog_hash(project, vector_invalidation_kind)
                if new_cat_hash != prev_cat_hash:
                    if hasattr(result, "vector_index_status"):
                        result.vector_index_status = "invalidated"
                    if self.vector_repo:
                        try:
                            self.vector_repo.invalidate_project_indices(
                                proj_id,
                                kind=vector_invalidation_kind,
                                current_catalog_items=catalog_rows(project, vector_invalidation_kind),
                            )
                        except Exception:
                            pass
                else:
                    if hasattr(result, "vector_index_status"):
                        result.vector_index_status = "valid"

            # 10. Đồng bộ Read Projection SQLite an toàn
            if self.read_projection:
                try:
                    if hasattr(self.read_projection, "sync_project"):
                        self.read_projection.sync_project(project)
                    elif hasattr(self.read_projection, "sync_from_project_dict"):
                        self.read_projection.sync_from_project_dict(project)
                    if hasattr(self.project_store, "clear_sync_pending"):
                        self.project_store.clear_sync_pending(proj_name)
                    project["sync_pending"] = False
                    project["sync_error"] = ""
                    if hasattr(result, "sync_status"):
                        result.sync_status = "synced"
                        result.sync_error = ""
                except Exception as exc:
                    err_str = str(exc)
                    if hasattr(self.project_store, "mark_sync_pending"):
                        self.project_store.mark_sync_pending(proj_name, err_str)
                    project["sync_pending"] = True
                    project["sync_error"] = err_str
                    if hasattr(result, "sync_status"):
                        result.sync_status = "sync_pending"
                        result.sync_error = err_str

            # 11. Lưu vào cache idempotency
            final_dict = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            idem_entry["result"] = final_dict
            project.setdefault(idempotency_store_key, {})[request_id] = idem_entry
            self._idempotency_cache[(f"{idempotency_store_key}:{proj_id}", request_id)] = idem_entry

            return result
