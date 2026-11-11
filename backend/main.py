"""Điểm khởi chạy Backend Server độc lập (hỗ trợ cả FastAPI + Uvicorn và HTTPServer chuẩn)."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from backend.api.routers import api_v1_router
from backend.api.v1 import handle_api_request


def create_fastapi_app():
    """Khởi tạo ứng dụng FastAPI với đầy đủ Typed Routers, OpenAPI Swagger docs và CORS."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import RedirectResponse

    app = FastAPI(
        title="KG Studio Pro Commercial & ML API",
        description=(
            "Hệ thống Backend REST API chuẩn hóa cho Trích xuất tri thức, "
            "Gióng hàng Schema (EDC+R), Kiểm duyệt Dữ kiện và G-Retriever Graph RAG. "
            "Tích hợp Pydantic v2 & FastAPI."
        ),
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse(url="/docs")

    app.include_router(api_v1_router)

    return app


# Khởi tạo instance app cấp module để uvicorn có thể chạy trực tiếp: `uvicorn backend.main:app`
try:
    app = create_fastapi_app()
except Exception:
    app = None


class _StdlibAPIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status, data = handle_api_request("GET", self.path)
        self._send_json(status, data)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        status, data = handle_api_request("POST", self.path, body)
        self._send_json(status, data)

    def _send_json(self, status: int, data: dict) -> None:
        encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        return


def run_stdlib_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = HTTPServer((host, port), _StdlibAPIHandler)
    print(f"KG Studio Pro Stdlib API đang chạy tại http://{host}:{port}/api/v1/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


def run_uvicorn_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    print(f"KG Studio Pro FastAPI đang chạy tại http://{host}:{port}/docs")
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Khởi chạy KG Studio Pro Backend API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--engine", choices=["uvicorn", "stdlib"], default="uvicorn")
    args = parser.parse_args()

    if args.engine == "uvicorn":
        try:
            run_uvicorn_server(args.host, args.port)
        except ImportError:
            print("Chưa cài đặt uvicorn, tự động chuyển về máy chủ stdlib...")
            run_stdlib_server(args.host, args.port)
    else:
        run_stdlib_server(args.host, args.port)
