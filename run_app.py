"""Khởi chạy độc lập KG Studio Pro (Frontend Streamlit hoặc kiểm tra cấu hình)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from shared.config_loader import APP_ROOT, CONFIG, CONFIG_PATH


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Khởi chạy KG Studio Pro (Độc lập 100%)")
    parser.add_argument("--check-config", action="store_true", help="Chỉ kiểm tra cấu hình rồi thoát")
    args = parser.parse_args()

    if args.check_config:
        print(f"Cấu hình hợp lệ: {CONFIG_PATH}")
        print(f"Số quan hệ mặc định: {len(CONFIG['knowledge']['relations'])}")
        print(f"Số loại thực thể mặc định: {len(CONFIG['knowledge']['entity_types'])}")
        return 0

    server_cfg = CONFIG["server"]
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_ROOT / "frontend" / "app.py"),
        "--server.address",
        str(server_cfg["address"]),
        "--server.port",
        str(server_cfg["port"]),
        "--server.headless",
        str(server_cfg["headless"]).lower(),
        "--browser.gatherUsageStats",
        str(server_cfg["gather_usage_stats"]).lower(),
        "--client.showSidebarNavigation",
        "false",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(APP_ROOT)
    return subprocess.call(cmd, cwd=str(APP_ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
