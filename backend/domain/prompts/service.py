"""Dịch vụ Quản lý Phiên bản Prompt theo Cấu hình & Lịch sử (Prompt Versioning Service).

Tuân thủ kiến trúc thiết kế trong KG_Studio/AI/features/prompt-versioning.md:
1. Mỗi dự án sở hữu prompt độc lập theo từng chế độ trích xuất.
2. Quản lý bất biến (immutable versions) với chuỗi số tăng dần và content hash SHA-256.
3. Không tự ý thay đổi catalog, mô hình hay dữ kiện khi lưu / khôi phục prompt.
4. Migration tự động, an toàn và lũy đẳng (idempotent).
"""
from __future__ import annotations

import difflib
import hashlib

from shared.config_loader import CONFIG
from shared.constants import (
    DEFAULT_EDC_PROMPT,
    DEFAULT_FREE_TRIPLES_PROMPT,
    EXTRACTION_MODES,
    MODE_EDC,
    MODE_EDC_PLUS_R,
    MODE_FIXED,
    MODE_FREE_TRIPLES,
)
from shared.text_utils import now_iso, uid

PROMPT_HISTORY_SCHEMA_VERSION = 1
DEFAULT_PROMPT_FIXED = CONFIG["knowledge"]["system_prompt"].strip()

DEFAULT_PROMPTS = {
    MODE_FIXED: DEFAULT_PROMPT_FIXED,
    MODE_EDC: DEFAULT_EDC_PROMPT.strip(),
    MODE_EDC_PLUS_R: DEFAULT_EDC_PROMPT.strip(),
    MODE_FREE_TRIPLES: DEFAULT_FREE_TRIPLES_PROMPT.strip(),
}


def compute_prompt_hash(content: str) -> str:
    """Tính mã băm SHA-256 đầy đủ trên nội dung văn bản chuẩn hóa newline."""
    normalized = (content or "").replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def ensure_project_prompt_history(project: dict) -> bool:
    """Đảm bảo dự án sở hữu cấu trúc schema prompt_history phiên bản 1 (Di chuyển dữ liệu an toàn & lũy đẳng)."""
    current_schema = project.get("prompt_history_schema_version", 0)
    has_bindings = isinstance(project.get("prompt_bindings"), dict)
    has_versions = isinstance(project.get("prompt_versions"), list)

    # Đã có đầy đủ schema và bindings cho các chế độ được hỗ trợ
    if (
        current_schema >= PROMPT_HISTORY_SCHEMA_VERSION
        and has_bindings
        and has_versions
        and all(m in project["prompt_bindings"] for m in EXTRACTION_MODES)
    ):
        return False

    bindings: dict[str, str] = dict(project.get("prompt_bindings") or {})
    existing_versions: list[dict] = list(project.get("prompt_versions") or [])
    new_versions: list[dict] = []
    migrated = False

    # 1. Chuyển đổi các bản ghi lịch sử legacy (nếu có)
    # Trong các phiên bản cũ, prompt_versions lưu dict gồm {at, prompt, prompt_id, relations...}
    legacy_closed_entries = []
    for entry in existing_versions:
        if isinstance(entry, dict) and "version" in entry and "content" in entry and "id" in entry:
            # Đã là định dạng version mới
            new_versions.append(entry)
        elif isinstance(entry, dict) and "prompt" in entry:
            # Bản ghi legacy từ save_prompt_settings cũ
            p_text = str(entry.get("prompt", "")).strip()
            if p_text:
                legacy_closed_entries.append((entry, p_text))

    # Đánh số lại các bản legacy thành các phiên bản closed ban đầu
    closed_seq = 1
    for leg_entry, leg_text in legacy_closed_entries:
        p_hash = compute_prompt_hash(leg_text)
        # Bỏ qua nếu nội dung trùng lặp liên tiếp
        if new_versions and new_versions[-1].get("configuration_id") == MODE_FIXED and new_versions[-1].get("content_hash") == p_hash:
            continue
        v_id = f"pv_closed_{closed_seq:02d}_{uid()[:6]}"
        new_versions.append(
            {
                "id": v_id,
                "configuration_id": MODE_FIXED,
                "mode": MODE_FIXED,
                "version": closed_seq,
                "content": leg_text,
                "content_hash": p_hash,
                "created_at": str(leg_entry.get("at") or now_iso()),
                "created_by": "migration",
                "note": "Di chuyển từ lịch sử thiết lập cũ",
                "parent_version_id": None,
                "restored_from_version_id": None,
                "origin": "migration",
            }
        )
        closed_seq += 1

    # 2. Khởi tạo phiên bản active ban đầu cho từng mode nếu chưa có binding hợp lệ
    for mode in EXTRACTION_MODES:
        active_vid = bindings.get(mode)
        mode_versions = [v for v in new_versions if v.get("configuration_id") == mode]

        # Kiểm tra xem binding có trỏ đến version tồn tại không
        valid_binding = active_vid and any(v.get("id") == active_vid for v in mode_versions)

        if not valid_binding:
            # Xác định nội dung ban đầu từ project legacy hoặc default
            if mode == MODE_FIXED:
                content = str(project.get("prompt") or DEFAULT_PROMPTS[MODE_FIXED]).strip()
            elif mode == MODE_FREE_TRIPLES:
                # Never seed the raw baseline with EDC's definition instructions.
                content = DEFAULT_PROMPTS[MODE_FREE_TRIPLES]
            else:
                content = str(project.get("edc_prompt") or DEFAULT_PROMPTS[mode]).strip()

            c_hash = compute_prompt_hash(content)

            # Nếu trong danh sách đã có version khớp nội dung này, dùng luôn
            matching = [v for v in mode_versions if v.get("content_hash") == c_hash]
            if matching:
                bindings[mode] = matching[-1]["id"]
            else:
                next_seq = max((v.get("version", 0) for v in mode_versions), default=0) + 1
                new_vid = f"pv_{mode}_{next_seq:02d}_{uid()[:6]}"
                new_ver = {
                    "id": new_vid,
                    "configuration_id": mode,
                    "mode": mode,
                    "version": next_seq,
                    "content": content,
                    "content_hash": c_hash,
                    "created_at": now_iso(),
                    "created_by": "system",
                    "note": f"Khởi tạo mặc định cho chế độ {mode}",
                    "parent_version_id": None,
                    "restored_from_version_id": None,
                    "origin": "default_seed" if content == DEFAULT_PROMPTS[mode] else "migration",
                }
                new_versions.append(new_ver)
                bindings[mode] = new_vid
            migrated = True

    project["prompt_history_schema_version"] = PROMPT_HISTORY_SCHEMA_VERSION
    project["prompt_bindings"] = bindings
    project["prompt_versions"] = new_versions
    return migrated


def get_active_prompt_version(project: dict, configuration_id: str | None = None) -> dict | None:
    """Lấy bản ghi phiên bản prompt đang áp dụng cho cấu hình/chế độ chỉ định."""
    ensure_project_prompt_history(project)
    cfg_id = configuration_id or project.get("extraction_mode", MODE_FIXED)
    if cfg_id not in EXTRACTION_MODES:
        cfg_id = MODE_FIXED

    binding_id = project.get("prompt_bindings", {}).get(cfg_id)
    if not binding_id:
        return None

    for v in project.get("prompt_versions", []):
        if v.get("id") == binding_id:
            return v
    return None


def get_active_prompt_content(project: dict, configuration_id: str | None = None) -> str:
    """Lấy nội dung hướng dẫn prompt đang áp dụng."""
    ver = get_active_prompt_version(project, configuration_id)
    if ver and ver.get("content"):
        return ver["content"]
    cfg_id = configuration_id or project.get("extraction_mode", MODE_FIXED)
    return DEFAULT_PROMPTS.get(cfg_id, DEFAULT_PROMPT_FIXED)


def list_prompt_versions(project: dict, configuration_id: str | None = None) -> list[dict]:
    """Danh sách các phiên bản prompt đã lưu, sắp xếp theo phiên bản mới nhất lên đầu."""
    ensure_project_prompt_history(project)
    versions = project.get("prompt_versions", [])
    if configuration_id:
        versions = [v for v in versions if v.get("configuration_id") == configuration_id]
    return sorted(versions, key=lambda v: (v.get("configuration_id", ""), v.get("version", 0)), reverse=True)


def get_prompt_version(project: dict, version_id: str) -> dict | None:
    """Tra cứu một phiên bản prompt cụ thể theo ID."""
    ensure_project_prompt_history(project)
    for v in project.get("prompt_versions", []):
        if v.get("id") == version_id:
            return v
    return None


def save_prompt_version(
    project: dict,
    configuration_id: str,
    content: str,
    *,
    note: str = "",
    created_by: str = "local_user",
    origin: str = "human",
    expected_revision: str | None = None,
) -> tuple[dict, bool]:
    """Lưu một phiên bản prompt mới cho cấu hình.
    
    Quy tắc nghiệp vụ:
    - Nếu nội dung rỗng: báo lỗi ValueError.
    - Nếu nội dung giống hệt phiên bản đang áp dụng: no-op (không sinh version rác).
    - Tạo phiên bản mới bất biến, tăng số thứ tự version và cập nhật binding.
    - Cập nhật trường legacy để đảm bảo tương thích ngược.
    """
    ensure_project_prompt_history(project)

    if expected_revision:
        from backend.domain.catalogs.core import compute_project_revision

        current_rev = compute_project_revision(project)
        if expected_revision != current_rev:
            raise ValueError(
                f"Xung đột phiên bản dự án khi lưu prompt (expected={expected_revision}, actual={current_rev})."
            )

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Nội dung prompt không được để trống.")

    if configuration_id not in EXTRACTION_MODES:
        raise ValueError(f"Cấu hình '{configuration_id}' không hợp lệ. Phải là một trong: {EXTRACTION_MODES}")

    clean_content = content.replace("\r\n", "\n").strip()
    c_hash = compute_prompt_hash(clean_content)

    active = get_active_prompt_version(project, configuration_id)
    if active and active.get("content_hash") == c_hash:
        # Nội dung không đổi: no-op
        return active, False

    # Tính version kế tiếp
    existing_for_cfg = [v for v in project.get("prompt_versions", []) if v.get("configuration_id") == configuration_id]
    next_seq = max((v.get("version", 0) for v in existing_for_cfg), default=0) + 1

    version_id = f"pv_{configuration_id}_{next_seq:02d}_{uid()[:6]}"
    new_version_record = {
        "id": version_id,
        "configuration_id": configuration_id,
        "mode": configuration_id,
        "version": next_seq,
        "content": clean_content,
        "content_hash": c_hash,
        "created_at": now_iso(),
        "created_by": created_by or "local_user",
        "note": note.strip(),
        "parent_version_id": active.get("id") if active else None,
        "restored_from_version_id": None,
        "origin": origin,
    }

    project.setdefault("prompt_versions", []).append(new_version_record)
    project.setdefault("prompt_bindings", {})[configuration_id] = version_id

    # Duy trì tương thích trường legacy
    if configuration_id == MODE_FIXED:
        project["prompt"] = clean_content
    elif configuration_id in (MODE_EDC, MODE_EDC_PLUS_R):
        if project.get("extraction_mode") == configuration_id:
            project["edc_prompt"] = clean_content

    return new_version_record, True


def restore_prompt_version(
    project: dict,
    target_version_id: str,
    *,
    note: str = "",
    created_by: str = "local_user",
) -> tuple[dict, bool]:
    """Khôi phục một phiên bản prompt cũ.
    
    Quy tắc nghiệp vụ:
    - Không sửa đổi hoặc xóa phiên bản cũ.
    - Tạo một phiên bản MỚI kế thừa nội dung của phiên bản cũ, ghi nhận restored_from_version_id.
    - Nếu nội dung phiên bản cũ giống hệt phiên bản đang dùng: no-op.
    - Tuyệt đối không thay đổi catalog, token hay dữ kiện khác trong dự án.
    """
    ensure_project_prompt_history(project)

    target = get_prompt_version(project, target_version_id)
    if not target:
        raise ValueError(f"Không tìm thấy phiên bản prompt với ID: '{target_version_id}'")

    cfg_id = target.get("configuration_id")
    active = get_active_prompt_version(project, cfg_id)

    if active and active.get("content_hash") == target.get("content_hash"):
        # Đang áp dụng chính nội dung này: no-op
        return active, False

    existing_for_cfg = [v for v in project.get("prompt_versions", []) if v.get("configuration_id") == cfg_id]
    next_seq = max((v.get("version", 0) for v in existing_for_cfg), default=0) + 1

    version_id = f"pv_{cfg_id}_{next_seq:02d}_{uid()[:6]}"
    restored_note = note.strip() or f"Khôi phục từ v{target.get('version')} ({target.get('id')})"

    new_version_record = {
        "id": version_id,
        "configuration_id": cfg_id,
        "mode": cfg_id,
        "version": next_seq,
        "content": target["content"],
        "content_hash": target["content_hash"],
        "created_at": now_iso(),
        "created_by": created_by or "local_user",
        "note": restored_note,
        "parent_version_id": active.get("id") if active else None,
        "restored_from_version_id": target["id"],
        "origin": "human",
    }

    project.setdefault("prompt_versions", []).append(new_version_record)
    project.setdefault("prompt_bindings", {})[cfg_id] = version_id

    # Duy trì tương thích trường legacy
    if cfg_id == MODE_FIXED:
        project["prompt"] = target["content"]
    elif cfg_id in (MODE_EDC, MODE_EDC_PLUS_R):
        if project.get("extraction_mode") == cfg_id:
            project["edc_prompt"] = target["content"]

    return new_version_record, True


def diff_prompt_versions(v1_content: str, v2_content: str, v1_name: str = "Bản cũ", v2_name: str = "Bản mới") -> str:
    """So sánh văn bản 2 phiên bản prompt bằng difflib chuẩn Python."""
    lines1 = (v1_content or "").replace("\r\n", "\n").splitlines(keepends=True)
    lines2 = (v2_content or "").replace("\r\n", "\n").splitlines(keepends=True)
    diff = difflib.unified_diff(lines1, lines2, fromfile=v1_name, tofile=v2_name, lineterm="")
    return "\n".join(diff)

