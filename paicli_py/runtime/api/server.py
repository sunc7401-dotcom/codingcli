"""运行时 HTTP API 服务器。

对应 ``com.paicli.runtime.api.RuntimeApiServer``。

提供 OpenAI 兼容的 threads/turns/events 端点，
支持 SSE 流式事件推送。
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class RuntimeApiServer:
    """嵌入式 HTTP 服务器，暴露 OpenAI 兼容 API。

    端点:
    - POST /v1/threads → 创建对话线程
    - POST /v1/threads/{id}/turns → 提交任务
    - GET /v1/threads/{id}/events?after=N → SSE 事件流
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        self._host = host
        self._port = port
        self._api_key = os.environ.get("PAICLI_RUNTIME_API_KEY", "")
        self._server: HTTPServer | None = None
        self._db_path = Path.home() / ".paicli" / "runtime.db"

    def start(self) -> None:
        """启动服务器（在后台线程中运行）。"""
        import threading

        handler = self._make_handler()
        self._server = HTTPServer((self._host, self._port), handler)
        self._server.timeout = 1

        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        print(f"Runtime API 服务已启动: http://{self._host}:{self._port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        api_key = self._api_key
        db_path = self._db_path
        runner = getattr(self, '_runner', None)

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if not self._check_auth():
                    return
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/")
                parts = path.split("/")

                if path == "/v1/threads":
                    thread_id = f"thread_{secrets.token_hex(12)}"
                    self._init_db()
                    conn = sqlite3.connect(str(db_path))
                    conn.execute("INSERT INTO runtime_threads (id, created_at) VALUES (?, ?)", [thread_id, time.time()])
                    conn.execute("INSERT INTO runtime_events (thread_id, type, data, created_at) VALUES (?, ?, ?, ?)", [thread_id, "thread.created", "{}", time.time()])
                    conn.commit()
                    conn.close()
                    self._json_response(201, {"id": thread_id, "object": "thread"})

                elif len(parts) >= 4 and parts[1] == "v1" and parts[2] == "threads" and parts[3] and parts[-1] == "turns":
                    thread_id = parts[3]
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}
                    turn_input = body.get("input", body.get("content", ""))

                    self._init_db()
                    conn = sqlite3.connect(str(db_path))
                    conn.execute("INSERT INTO runtime_events (thread_id, type, data, created_at) VALUES (?, ?, ?, ?)", [thread_id, "turn.started", json.dumps({"input": turn_input}), time.time()])
                    conn.commit()
                    conn.close()

                    # 后台执行
                    if runner:
                        import threading
                        def _run():
                            try:
                                result = runner.run(turn_input)
                                c = sqlite3.connect(str(db_path))
                                c.execute("INSERT INTO runtime_events (thread_id, type, data, created_at) VALUES (?, ?, ?, ?)", [thread_id, "message.delta", json.dumps({"content": result}), time.time()])
                                c.execute("INSERT INTO runtime_events (thread_id, type, data, created_at) VALUES (?, ?, ?, ?)", [thread_id, "turn.completed", "{}", time.time()])
                                c.commit(); c.close()
                            except Exception as e:
                                c = sqlite3.connect(str(db_path))
                                c.execute("INSERT INTO runtime_events (thread_id, type, data, created_at) VALUES (?, ?, ?, ?)", [thread_id, "turn.failed", json.dumps({"error": str(e)}), time.time()])
                                c.commit(); c.close()
                        threading.Thread(target=_run, daemon=True).start()

                    self._json_response(202, {"status": "accepted"})
                else:
                    self._json_response(404, {"error": "Not found"})

            def do_GET(self):
                if not self._check_auth():
                    return
                parsed = urlparse(self.path)

                if "/events" in parsed.path:
                    thread_id = self._extract_thread_id(parsed.path)
                    after = int(parsed.query.split("=")[1]) if "after=" in (parsed.query or "") else 0

                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()

                    # SSE 流（简化：发送已有事件后保持连接）
                    conn = sqlite3.connect(str(db_path))
                    rows = conn.execute(
                        "SELECT id, type, data FROM runtime_events WHERE thread_id=? AND id>? ORDER BY id",
                        [thread_id, after],
                    ).fetchall()
                    conn.close()

                    for row in rows:
                        event = f"id: {row[0]}\nevent: {row[1]}\ndata: {row[2]}\n\n"
                        self.wfile.write(event.encode())
                        self.wfile.flush()
                else:
                    self._json_response(404, {"error": "Not found"})

            def _check_auth(self):
                if not api_key:
                    return True
                auth = self.headers.get("Authorization", "")
                if auth == f"Bearer {api_key}":
                    return True
                self._json_response(401, {"error": "Unauthorized"})
                return False

            def _json_response(self, status, data):
                body = json.dumps(data, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            @staticmethod
            def _extract_thread_id(path):
                parts = path.strip("/").split("/")
                for i, p in enumerate(parts):
                    if p == "threads" and i + 1 < len(parts):
                        return parts[i + 1]
                return ""

            @staticmethod
            def _init_db():
                conn = sqlite3.connect(str(db_path))
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS runtime_threads (
                        id TEXT PRIMARY KEY,
                        created_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS runtime_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        thread_id TEXT NOT NULL,
                        type TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at REAL NOT NULL
                    );
                """)
                conn.commit()
                conn.close()

        return _Handler
