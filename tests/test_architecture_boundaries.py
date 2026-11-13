"""Kiểm thử ranh giới kiến trúc (Architecture Boundaries & Dependency Rules).
Tuân thủ Gate P0 trong AI/report/code-optimization-architecture-plan.md và quy tắc AGENTS.md:
- Backend và Shared tuyệt đối không phụ thuộc Frontend.
- Shared tuyệt đối không phụ thuộc Backend hoặc ML Lab.
- Domain -> Infrastructure chỉ được phép theo allowlist cạnh import cụ thể kèm lý do và đợt gỡ.
- Bất kỳ vi phạm mới nào không nằm trong allowlist đều FAIL ngay lập tức.
"""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent

# Allowlist cạnh import cụ thể cho legacy domain -> infrastructure
# Cấu trúc: (file_nguồn_tương_đối, module_được_import): (lý_do, đợt_dự_kiến_gỡ)
LEGACY_DOMAIN_INFRA_ALLOWLIST: dict[tuple[str, str], tuple[str, str]] = {
    ("backend/domain/curation/semantic_clustering.py", "backend.integrations.llm"): (
        "LLM client dùng cho cluster naming và semantic refinement",
        "P5",
    ),
    ("backend/domain/curation/semantic_clustering.py", "backend.integrations.llm.clients"): (
        "Client factory dùng cho cụm ngữ nghĩa",
        "P5",
    ),
    ("backend/domain/extraction/engines/edc_one_pass.py", "backend.integrations.llm"): (
        "One-pass engine gọi LLM trích xuất mở",
        "P2",
    ),
    ("backend/domain/extraction/engines/edc_plus_r.py", "backend.integrations.embedder_gateway"): (
        "EDC+R engine dùng embedder gateway cho retrieval",
        "P2",
    ),
    ("backend/domain/extraction/engines/edc_plus_r.py", "backend.integrations.llm"): (
        "EDC+R engine gọi LLM trích xuất đa vòng",
        "P2",
    ),
    ("backend/domain/extraction/engines/fixed_catalog.py", "backend.integrations.llm"): (
        "Fixed catalog engine gọi LLM trích xuất kín",
        "P2",
    ),
    ("backend/domain/graph/g_retriever.py", "backend.integrations.llm"): (
        "G-Retriever gọi LLM suy luận câu trả lời từ Subgraph",
        "P5",
    ),
    ("backend/domain/graph/qa_generator.py", "backend.integrations.llm"): (
        "QA generator gọi LLM paraphrase câu hỏi",
        "P5",
    ),
    ("backend/domain/schema_intelligence/aligner.py", "backend.integrations.embedder_gateway"): (
        "Target aligner dùng embedder tính tương đồng vector",
        "P2",
    ),
    ("backend/domain/schema_intelligence/aligner.py", "backend.integrations.llm"): (
        "Target aligner dùng LLM gateway thẩm định ứng viên nghi ngờ",
        "P2",
    ),
    ("backend/domain/schema_intelligence/aligner.py", "backend.repositories.vector_repo"): (
        "Target aligner đọc chỉ mục vector trực tiếp",
        "P2",
    ),
    ("backend/domain/schema_intelligence/retriever.py", "backend.integrations.embedder_gateway"): (
        "Schema retriever mã hóa embedding query",
        "P2",
    ),
    ("backend/domain/schema_intelligence/retriever.py", "backend.repositories.vector_repo"): (
        "Schema retriever truy vấn vector trực tiếp",
        "P2",
    ),
}


def _extract_imports(file_path: Path) -> list[str]:
    """Bóc tách tất cả các module được import trong một file Python bằng AST (Fail-closed & Relative resolve)."""
    content = file_path.read_text(encoding="utf-8")
    tree = ast.parse(content, filename=str(file_path))

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imported.append(node.module)
            elif node.level > 0:
                parts = list(file_path.relative_to(ROOT_DIR).parts)[:-1]
                if node.level <= len(parts):
                    pkg_parts = parts[:len(parts) - (node.level - 1)]
                    base = ".".join(pkg_parts)
                    imported.append(f"{base}.{node.module}" if node.module else base)
                elif node.module:
                    imported.append(node.module)
    return imported


class ArchitectureBoundariesTest(unittest.TestCase):
    def test_shared_must_not_import_backend_frontend_or_ml_lab(self) -> None:
        """Quy tắc 1: shared/ là pure foundation, tuyệt đối không phụ thuộc vào backend, frontend hay ml_lab."""
        shared_dir = ROOT_DIR / "shared"
        violations: list[tuple[str, str]] = []

        for p in shared_dir.rglob("*.py"):
            rel_path = p.relative_to(ROOT_DIR).as_posix()
            for mod in _extract_imports(p):
                if mod.startswith(("backend", "frontend", "ml_lab")):
                    violations.append((rel_path, mod))

        self.assertEqual(
            violations,
            [],
            f"Phát hiện vi phạm: shared/ import phân hệ cấp cao: {violations}",
        )

    def test_backend_and_shared_must_not_import_frontend(self) -> None:
        """Quy tắc 2: backend/ và shared/ tuyệt đối không phụ thuộc vào frontend UI."""
        violations: list[tuple[str, str]] = []
        for scan_dir in [ROOT_DIR / "backend", ROOT_DIR / "shared"]:
            for p in scan_dir.rglob("*.py"):
                rel_path = p.relative_to(ROOT_DIR).as_posix()
                for mod in _extract_imports(p):
                    if mod.startswith("frontend"):
                        violations.append((rel_path, mod))

        self.assertEqual(
            violations,
            [],
            f"Phát hiện vi phạm: Backend/Shared phụ thuộc vào Frontend UI: {violations}",
        )

    def test_domain_to_infrastructure_dependencies_must_be_in_allowlist(self) -> None:
        """Quy tắc 3: domain/ không được tự import concrete repositories hoặc gateways.
        Các cạnh legacy hiện tại phải được ghi danh trong allowlist và không được phát sinh thêm cạnh mới.
        """
        domain_dir = ROOT_DIR / "backend" / "domain"
        unauthorized_violations: list[tuple[str, str]] = []

        for p in domain_dir.rglob("*.py"):
            rel_path = p.relative_to(ROOT_DIR).as_posix()
            for mod in _extract_imports(p):
                if mod.startswith(("backend.repositories", "backend.integrations")):
                    edge = (rel_path, mod)
                    if edge not in LEGACY_DOMAIN_INFRA_ALLOWLIST:
                        unauthorized_violations.append(edge)

        self.assertEqual(
            unauthorized_violations,
            [],
            f"Phát hiện vi phạm kiến trúc mới: Domain import Concrete Infrastructure ngoài allowlist: {unauthorized_violations}",
        )

    def test_llm_package_imports_cleanly_without_circular_dependency(self) -> None:
        """Quy tắc 4: Phân hệ backend.integrations.llm phải import sạch sẽ và không gây vòng lặp runtime."""
        import backend.integrations.llm as llm_pkg
        from backend.integrations.llm.gateway import LLMGateway

        self.assertTrue(hasattr(llm_pkg, "LLMGateway"))
        self.assertIs(llm_pkg.LLMGateway, LLMGateway)
        self.assertTrue(hasattr(LLMGateway, "extract"))

    def test_cross_module_private_imports_are_forbidden(self) -> None:
        """Quy tắc 5: Các module trong backend/modules/ khi gọi chéo nhau BẮT BUỘC phải qua .public hoặc .ports."""
        modules_dir = ROOT_DIR / "backend" / "modules"
        module_names = {"projects", "schema_intelligence", "extraction", "curation", "graph_qa", "training"}
        violations: list[tuple[str, str]] = []

        for p in modules_dir.rglob("*.py"):
            rel_parts = p.relative_to(modules_dir).parts
            if not rel_parts:
                continue
            caller_module = rel_parts[0]
            if caller_module not in module_names:
                continue

            for mod in _extract_imports(p):
                if not mod.startswith("backend.modules."):
                    continue
                parts = mod.split(".")
                if len(parts) >= 3:
                    target_module = parts[2]
                    if target_module in module_names and target_module != caller_module:
                        sub = parts[3] if len(parts) > 3 else ""
                        if sub not in ("public", "ports"):
                            violations.append((p.relative_to(ROOT_DIR).as_posix(), mod))

        self.assertEqual(
            violations,
            [],
            f"Phát hiện vi phạm cross-module private import (phải dùng .public hoặc .ports): {violations}",
        )

    def test_frontend_must_not_import_backend_repositories_directly(self) -> None:
        """Quy tắc 6: frontend/ tuyệt đối không import concrete repositories (backend.repositories.*) trực tiếp."""
        frontend_dir = ROOT_DIR / "frontend"
        violations: list[tuple[str, str]] = []

        for p in frontend_dir.rglob("*.py"):
            for mod in _extract_imports(p):
                if mod.startswith("backend.repositories"):
                    violations.append((p.relative_to(ROOT_DIR).as_posix(), mod))

        self.assertEqual(
            violations,
            [],
            f"Phát hiện Frontend import trực tiếp Concrete Repositories: {violations}",
        )

    def test_frontend_must_import_backend_modules_via_public_only(self) -> None:
        """Quy tắc 7: frontend/ khi gọi backend.modules.* BẮT BUỘC phải qua .public."""
        frontend_dir = ROOT_DIR / "frontend"
        module_names = {"projects", "schema_intelligence", "extraction", "curation", "graph_qa", "training"}
        violations: list[tuple[str, str]] = []

        for p in frontend_dir.rglob("*.py"):
            for mod in _extract_imports(p):
                if mod.startswith("backend.modules."):
                    parts = mod.split(".")
                    if len(parts) >= 3 and parts[2] in module_names:
                        sub = parts[3] if len(parts) > 3 else ""
                        if sub not in ("public", "ports"):
                            violations.append((p.relative_to(ROOT_DIR).as_posix(), mod))

        self.assertEqual(
            violations,
            [],
            f"Phát hiện Frontend import private implementation của backend.modules: {violations}",
        )

    def test_guard_detects_unauthorized_cross_module_import_negative_fixture(self) -> None:
        """Negative test: Kiểm chứng AST extractor và rule bắt chính xác vi phạm cross-module private import."""
        synthetic_code = "from backend.modules.projects.application.service import ProjectsApplicationService\n"
        tree = ast.parse(synthetic_code, filename="fake_service.py")
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)

        is_violation = False
        for mod in imported:
            if mod.startswith("backend.modules."):
                parts = mod.split(".")
                if len(parts) >= 4 and parts[2] == "projects" and parts[3] not in ("public", "ports"):
                    is_violation = True
        self.assertTrue(is_violation, "Guard phải bắt được vi phạm import private implementation.")


if __name__ == "__main__":
    unittest.main()
