"""Test Runner tổng hợp cho KG Studio.
Chạy toàn bộ offline unit test suites, lọc bỏ cảnh báo bare-mode của Streamlit,
và xuất bảng tổng kết chi tiết: Pass, Fail, Error, Runtime.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import sys
import time
import unittest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Tắt logging ồn ào của Streamlit trong bare test mode
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"

TEST_FILES = [
    "tests/test_architecture_boundaries.py",
    "tests/test_baseline_graph.py",
    "tests/test_baseline_graph_ui.py",
    "tests/test_code_cleanup.py",
    "tests/test_commit_coordinator.py",
    "tests/test_curation_hub.py",
    "tests/test_curation_merge.py",
    "tests/test_edc_bulk_review.py",
    "tests/test_edc_plus_r_live.py",
    "tests/test_free_triples_baseline.py",
    "tests/test_free_triples_gateway.py",
    "tests/test_free_triples_ui.py",
    "tests/test_g_retriever.py",
    "tests/test_layout_pipeline.py",
    "tests/test_llm_package.py",
    "tests/test_parallel_extraction.py",
    "tests/test_performance_optimizations.py",
    "tests/test_projects_module.py",
    "tests/test_prompt_versions.py",
    "tests/test_relation_cleaning.py",
    "tests/test_secrets_manager.py",
    "tests/test_semantic_clustering.py",
    "tests/test_standalone_architecture.py",
    "tests/test_api_v1_and_composition.py",
    "tests/test_pydantic_contracts.py",
]


def run_all() -> int:
    print("=" * 70)
    print("🧪 KG STUDIO PRO - FULL OFFLINE TEST SUITE RUNNER")
    print(f"Python: {sys.version.split()[0]} | Suites: {len(TEST_FILES)}")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for test_file in TEST_FILES:
        module_name = test_file.replace("/", ".").replace("\\", ".")
        if module_name.endswith(".py"):
            module_name = module_name[:-3]
        try:
            mod_suite = loader.loadTestsFromName(module_name)
            suite.addTests(mod_suite)
        except Exception as exc:
            print(f"❌ Lỗi khi nạp suite {test_file}: {exc}")

    total_tests = suite.countTestCases()
    print(f"Đã nạp {total_tests} test cases. Bắt đầu thực thi...\n")

    start_time = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    duration = time.perf_counter() - start_time

    print("\n" + "=" * 70)
    print("📊 KẾT QUẢ NGHIỆM THU KIỂM THỬ:")
    print(f"  - Tổng số tests: {result.testsRun}")
    print(f"  - Thành công    : {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"  - Thất bại      : {len(result.failures)}")
    print(f"  - Lỗi           : {len(result.errors)}")
    print(f"  - Bỏ qua        : {len(result.skipped)}")
    print(f"  - Thời gian chạy: {duration:.2f} giây")
    print("=" * 70)

    if result.wasSuccessful():
        print("✅ TOÀN BỘ OFFLINE TEST SUITE ĐẠT 100% PASS.")
        return 0
    else:
        print("❌ CÓ TEST BỊ THẤT BẠI HOẶC LỖI.")
        return 1


if __name__ == "__main__":
    sys.exit(run_all())
