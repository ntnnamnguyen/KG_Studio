"""Điểm khởi chạy Backend Server độc lập (hỗ trợ cả FastAPI nếu có hoặc HTTPServer chuẩn)."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from backend.api.v1 import handle_api_request


def create_fastapi_app():
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="KG Studio Pro Commercial & ML API", version="2.0.0")

    @app.api_route("/api/v1/{full_path:path}", methods=["GET", "POST"])
    async def proxy_v1(request: Request, full_path: str):
        body = None
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                body = {}
        status, data = handle_api_request(request.method, f"/api/v1/{full_path}", body)
        return JSONResponse(status_code=status, content=data)

    return app


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
    print(f"KG Studio Pro REST API đang chạy tại http://{host}:{port}/api/v1/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Khởi chạy KG Studio Pro Backend API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_stdlib_server(args.host, args.port)

