# -*- coding: utf-8 -*-
"""咪咕医生本地静态服务器与大模型 API 代理。

这个服务只绑定在 127.0.0.1，适合本地作品演示。API Key 只在服务端读取，
不会暴露给浏览器。它不是可直接部署到公网的生产后端。
"""

import json
import logging
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
from openai import OpenAI
from request_validation import validate_messages

load_dotenv()

LOGGER = logging.getLogger("migu-doctor")
MAX_BODY_BYTES = 64 * 1024


def create_client():
    """在请求发生时创建客户端，缺少密钥时仍允许预览静态页面。"""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        return None
    return OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=20.0,
        max_retries=1,
    )


class ApiProxyHandler(SimpleHTTPRequestHandler):
    server_version = "MiguDoctorLocal/1.0"

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; frame-ancestors 'none'",
        )
        super().end_headers()

    def do_GET(self):
        if self.path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "modelConfigured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
                }
            )
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/chat/completions":
            self._send_json(
                {"error": "接口不存在。", "code": "NOT_FOUND"}, status=404
            )
            return

        if "application/json" not in self.headers.get("Content-Type", ""):
            self._send_json(
                {"error": "请求必须使用 JSON 格式。", "code": "INVALID_CONTENT_TYPE"},
                status=415,
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self._send_json(
                {"error": "请求内容为空或过大。", "code": "INVALID_BODY_SIZE"},
                status=413,
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
            messages = validate_messages(payload.get("messages"))
        except (json.JSONDecodeError, ValueError, AttributeError) as exc:
            self._send_json(
                {"error": str(exc), "code": "INVALID_REQUEST"}, status=400
            )
            return

        client = create_client()
        if client is None:
            self._send_json(
                {
                    "error": "本地服务尚未配置模型密钥，请先填写 .env。",
                    "code": "MODEL_NOT_CONFIGURED",
                },
                status=503,
            )
            return

        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.3,
            )
            content = response.choices[0].message.content
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("模型返回了空内容")
            self._send_json(
                {"choices": [{"message": {"content": content.strip()}}]}
            )
        except Exception:
            LOGGER.exception("调用模型服务失败")
            self._send_json(
                {
                    "error": "模型服务暂时不可用，请稍后重试。",
                    "code": "UPSTREAM_ERROR",
                },
                status=502,
            )

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), ApiProxyHandler)
    print(f"咪咕医生本地演示已启动：http://127.0.0.1:{port}")
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print("提示：未配置 DEEPSEEK_API_KEY，静态页面可预览，AI 功能暂不可用。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n本地演示已停止。")
    finally:
        server.server_close()
