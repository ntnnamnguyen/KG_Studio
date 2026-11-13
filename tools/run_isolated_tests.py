"""Run the current working-tree tests in a disposable, offline workspace.

Usage: python tools/run_isolated_tests.py [tests.test_module ...]
No module names means full unittest discovery, including untracked new tests.
Legacy tests using default repositories see synthetic fixtures, never real projects.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest


def _inside(path: object, root: Path) -> bool:
    if isinstance(path, int) or path is None:
        return True
    return Path(os.fsdecode(path)).resolve().is_relative_to(root)


def _run_child(modules: list[str]) -> int:
    root = Path(os.environ["KG_STUDIO_ISOLATED_ROOT"]).resolve()
    if Path.cwd().resolve() != root or not Path(__file__).resolve().is_relative_to(root):
        raise RuntimeError("The isolated child must execute inside its temporary workspace")
    sys.path.insert(0, str(root))
    temp_root = root / "tmp"
    temp_root.mkdir(exist_ok=True)
    tempfile.tempdir = str(temp_root)

    def audit(event: str, args: tuple) -> None:
        if event == "open":
            path, mode, flags = args
            writing = bool(set(mode or "") & set("wax+")) or bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            if writing and not _inside(path, root):
                raise PermissionError("Test attempted a write outside its temporary workspace")
        elif event == "sqlite3.connect" and args[0] != ":memory:":
            if not _inside(args[0], root):
                raise PermissionError("Test attempted an external SQLite connection")
        elif event in {"os.remove", "os.rmdir", "os.mkdir"}:
            if not _inside(args[0], root):
                raise PermissionError("Test attempted a filesystem mutation outside its workspace")
        elif event in {"os.rename", "os.replace"}:
            if not all(_inside(path, root) for path in args[:2]):
                raise PermissionError("Test attempted an external rename")

    sys.addaudithook(audit)
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    lookup = socket.getaddrinfo
    local = {"127.0.0.1", "::1", "localhost"}

    def check_address(address: object) -> None:
        if isinstance(address, tuple) and address[0] not in local:
            raise OSError("External network disabled in offline tests")

    def local_connect(sock, address):
        check_address(address)
        return connect(sock, address)

    def local_connect_ex(sock, address):
        check_address(address)
        return connect_ex(sock, address)

    def local_lookup(host, *args, **kwargs):
        if host is not None and host not in local:
            raise OSError("External DNS disabled in offline tests")
        return lookup(host, *args, **kwargs)

    socket.socket.connect = local_connect
    socket.socket.connect_ex = local_connect_ex
    socket.getaddrinfo = local_lookup

    from backend.repositories.json_repo import JsonProjectRepository, empty_project
    from shared.catalog_utils import apply_relations
    from shared.constants import STATUS_APPROVED

    project = empty_project("HanoiQA")
    text = "Công trình thử nghiệm tọa lạc tại địa điểm thử nghiệm."
    project["documents"] = [{"id": "fixture-doc", "name": "fixture.txt", "text": text, "chars": len(text)}]
    project["entity_types"] = [{"name": "Địa danh", "description": "Fixture", "definition": "Synthetic test place"}]
    apply_relations(project, [{"name": "tọa lạc", "description": "Fixture", "definition": "Synthetic location relation"}])
    project["nodes"] = [
        {"id": "fixture-a", "name": "Công trình thử nghiệm", "kind": "Địa danh", "attributes": {}},
        {"id": "fixture-b", "name": "Địa điểm thử nghiệm", "kind": "Địa danh", "attributes": {}},
    ]
    project["edges"] = [{
        "id": "fixture-edge", "source": "fixture-a", "target": "fixture-b", "relation": "tọa lạc",
        "evidence": text, "doc_id": "fixture-doc", "status": STATUS_APPROVED,
    }]
    JsonProjectRepository().save_project(project)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(modules) if modules else loader.discover("tests", pattern="test_*.py", top_level_dir=".")
    for logger_name in list(logging.Logger.manager.loggerDict):
        if logger_name.startswith("streamlit"):
            logging.getLogger(logger_name).setLevel(logging.ERROR)
    print(f"Isolated Python {sys.version.split()[0]} | discovered cases: {suite.countTestCases()}", flush=True)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and not loader.errors else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:2] == ["--child"]:
        return _run_child(sys.argv[2:])
    modules = sys.argv[1:]
    if any(not module.startswith("tests.") for module in modules):
        raise SystemExit("Arguments must be unittest module/case names starting with tests.")
    source = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="kg-studio-tests-") as folder:
        shadow = Path(folder)
        ignored = shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", ".secrets*", ".venv*", ".pytest_cache")
        for name in ("backend", "frontend", "shared", "ml_lab", "tests", "tools", "config"):
            shutil.copytree(source / name, shadow / name, ignore=ignored)
        if (source / ".streamlit").is_dir():
            shutil.copytree(source / ".streamlit", shadow / ".streamlit", ignore=ignored)
        for name in ("AGENTS.md", "README.md", "pyproject.toml", ".gitignore", "app.py", "run_app.py", "run_windows.cmd"):
            if (source / name).is_file():
                shutil.copy2(source / name, shadow / name)
        # Khai báo fixture/template công khai chính xác theo AGENTS.md, không copy toàn bộ data/
        (shadow / "data").mkdir(exist_ok=True)
        sample_gazetteer = source / "data" / "hanoi_historical_gazetteer.json"
        if sample_gazetteer.is_file():
            shutil.copy2(sample_gazetteer, shadow / "data" / "hanoi_historical_gazetteer.json")
        config = shadow / "config" / "default.toml"
        text = config.read_text(encoding="utf-8-sig")
        storage = {
            "data_dir": str(shadow / "data"), "projects_dir": str(shadow / "data" / "projects"),
            "sqlite_db": str(shadow / "data" / "kg_studio.db"),
            "vector_indices_dir": str(shadow / "data" / "vector_indices"),
            "model_registry_dir": str(shadow / "data" / "model_registry"),
            "training_exports_dir": str(shadow / "data" / "training_exports"),
            "project_file": "project.json", "snapshots_dir": "snapshots",
        }
        section = "[storage]\n" + "\n".join(f"{key} = {json.dumps(value)}" for key, value in storage.items()) + "\n\n"
        text = re.sub(r"(?ms)^\[storage\][^\n]*\n.*?(?=^\[|\Z)", lambda _: section, text)
        text = re.sub(r'(?m)^(\s*(?:api_key|password)\s*=).*$', r'\1 ""', text)
        config.write_text(text, encoding="utf-8")
        env = dict(os.environ)
        for key in list(env):
            if key.endswith("_API_KEY") or key in {"LLM_API_KEY", "NEO4J_PASSWORD"}:
                env[key] = ""
        env.update({
            "KG_STUDIO_ISOLATED_ROOT": str(shadow), "KG_STUDIO_CONFIG": str(config),
            "KG_STUDIO_PROJECTS_DIR": storage["projects_dir"],
            "KG_STUDIO_SECRETS_FILE": str(shadow / "config" / ".secrets.toml"),
            "PYTHONPATH": str(shadow), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false", "STREAMLIT_SERVER_HEADLESS": "true",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "MPLCONFIGDIR": str(shadow / "tmp" / "mpl"),
            "TEMP": str(shadow / "tmp"), "TMP": str(shadow / "tmp"),
        })
        (shadow / "tmp").mkdir()
        completed = subprocess.run(
            [sys.executable, str(shadow / "tools" / "run_isolated_tests.py"), "--child", *modules],
            cwd=shadow, env=env, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8",
        )
        bare_warnings = 0
        for line in completed.stdout.splitlines():
            if "missing ScriptRunContext! This warning can be ignored when running in bare mode." in line:
                bare_warnings += 1
            else:
                print(line)
        if bare_warnings:
            print(f"Suppressed {bare_warnings} repetitive Streamlit bare-mode context warnings.")
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
