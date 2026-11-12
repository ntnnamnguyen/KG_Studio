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


if __name__ == "__main__":
    unittest.main()
