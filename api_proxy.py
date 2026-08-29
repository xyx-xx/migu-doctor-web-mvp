# -*- coding: utf-8 -*-
"""咪咕医生本地静态服务器与受限的大模型 API 代理。

服务只绑定在 127.0.0.1，适合本地作品演示。API Key、模型选择和系统提示词
只存在于服务端。它不是可直接部署到公网的生产后端。
"""

import json
import logging
import os
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv
from openai import OpenAI

from prompts import get_system_prompt
from request_validation import (
    contains_unsafe_advice,
    parse_model_json,
    validate_assist_request,
    validate_questions_result,
    validate_text_result,
    validate_triage_result,
)


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

LOGGER = logging.getLogger("migu-doctor")
MAX_BODY_BYTES = 64 * 1024
DEFAULT_MODEL = "deepseek-v4-flash"
ALLOWED_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})

# 静态服务采用逐项白名单。目录本身、源码、测试、文档和点文件都不会被发布。
STATIC_PATHS = frozenset(
    {
        "/index.html",
        "/consult.html",
        "/chat.html",
        "/wiki.html",
        "/emergency.html",
        "/toxin.html",
        "/favicon.svg",
        "/assets/app.js",
        "/assets/pets-warm-v1.jpg",
        "/assets/styles.css",
    }
)

SAFE_QUESTIONS_RESULT = {
    "questions": [
        "现在是否有呼吸困难、持续抽搐、意识异常、无法站立或大量出血？",
        "症状从何时开始，目前在加重、减轻还是基本稳定？",
        "精神状态、进食饮水和排泄与平时相比有什么变化？",
    ]
}
SAFE_TRIAGE_RESULT = {
    "risk": "CONTACT_VET_NOW",
    "riskLabel": "现在联系执业兽医",
    "rationale": "本次模型回复未通过格式或安全校验，线上信息不足以安全排除风险。",
    "actions": [
        "请现在联系执业兽医，说明宠物基本信息、症状、持续时间和变化趋势。",
        "记录精神状态、呼吸、进食饮水、排泄和症状变化，保留可能误食物的包装。",
        "不要自行用药或进行家庭处置；若状态恶化，直接前往宠物医院。",
    ],
    "emergencySigns": [
        "出现呼吸困难、持续抽搐、意识异常、无法站立、大量出血、虚脱或快速恶化时立即就医。"
    ],
}
SAFE_TEXT_RESULT = {
    "text": "为了安全，本次模型回复未采用。请现在联系执业兽医说明情况；若出现呼吸困难、持续抽搐、意识异常、无法站立、大量出血、虚脱或快速恶化，请立即前往宠物医院。"
}


def get_model_name():
    """模型只能由服务端环境变量选择。"""
    return os.getenv("DEEPSEEK_MODEL", "").strip() or DEFAULT_MODEL


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


def _fallback_result(task):
    if task == "triage_questions":
        return {"questions": list(SAFE_QUESTIONS_RESULT["questions"])}
    if task == "triage_result":
        return {
            **SAFE_TRIAGE_RESULT,
            "actions": list(SAFE_TRIAGE_RESULT["actions"]),
            "emergencySigns": list(SAFE_TRIAGE_RESULT["emergencySigns"]),
        }
    return dict(SAFE_TEXT_RESULT)


def _validated_model_result(task, content):
    """把不可信模型输出转换成固定协议；任何格式/安全失败都保守兜底。"""
    try:
        if contains_unsafe_advice(content):
            raise ValueError("模型输出包含被禁止的处置建议")
        if task == "triage_questions":
            result = validate_questions_result(parse_model_json(content))
            if contains_unsafe_advice(result):
                raise ValueError("结构化追问包含被禁止的处置建议")
            return result
        if task == "triage_result":
            result = validate_triage_result(parse_model_json(content))
            if contains_unsafe_advice(result):
                raise ValueError("结构化结果包含被禁止的处置建议")
            return result
        return validate_text_result(content)
    except (TypeError, ValueError):
        LOGGER.warning("模型输出未通过 %s 任务的格式或安全校验，已使用安全兜底", task)
        return _fallback_result(task)


def _parse_local_authority(value, expected_port):
    """严格解析 Host，只接受本机名称和当前监听端口。"""
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        parsed = urlsplit(f"//{value}")
        port = parsed.port
    except ValueError:
        return None
    hostname = parsed.hostname.lower() if parsed.hostname else None
    if (
        hostname not in ALLOWED_LOCAL_HOSTS
        or port != expected_port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        return None
    return hostname, port


def _origin_matches_authority(value, authority):
    """Origin 必须是当前 HTTP 本地服务的同一 scheme、host 与端口。"""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname.lower() if parsed.hostname else None
    return (
        parsed.scheme.lower() == "http"
        and hostname == authority[0]
        and port == authority[1]
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )


class ApiProxyHandler(SimpleHTTPRequestHandler):
    server_version = "MiguDoctorLocal/2.0"

    def __init__(self, *args, **kwargs):
        # 不采用进程 cwd，也不允许调用方覆盖发布目录。
        kwargs["directory"] = str(BASE_DIR)
        super().__init__(*args, **kwargs)

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

    def _request_path(self):
        return unquote(urlsplit(self.path).path)

    def _is_allowed_static_path(self, path):
        return path == "/" or path in STATIC_PATHS

    def _serve_static_or_404(self, head_only=False):
        path = self._request_path()
        if not self._is_allowed_static_path(path):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        if head_only:
            super().do_HEAD()
        else:
            super().do_GET()

    def list_directory(self, _path):
        """即使白名单中的入口文件意外缺失，也绝不生成目录列表。"""
        self.send_error(HTTPStatus.NOT_FOUND, "File not found")
        return None

    def _health_payload(self):
        return {
            "status": "ok",
            "configured": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
            "model": get_model_name(),
        }

    def _require_local_host(self):
        host_values = self.headers.get_all("Host") or []
        expected_port = int(self.server.server_address[1])
        authority = None
        if len(host_values) == 1:
            authority = _parse_local_authority(host_values[0], expected_port)
        if authority is None:
            self._send_json(
                {
                    "error": "请求 Host 不是当前本地服务地址。",
                    "code": "INVALID_HOST",
                },
                status=403,
                include_body=self.command != "HEAD",
            )
        return authority

    def _require_same_origin_for_post(self, authority):
        origin_values = self.headers.get_all("Origin") or []
        # 本地 curl、脚本和自动化通常不发送 Origin；只要 Host 已严格通过，
        # 明确允许这类无 Origin 的非浏览器客户端。浏览器一旦发送 Origin，
        # 则必须与请求 Host 的 scheme、hostname 和实际监听端口完全同源。
        if not origin_values:
            return True
        if len(origin_values) == 1 and _origin_matches_authority(
            origin_values[0], authority
        ):
            return True
        self._send_json(
            {
                "error": "POST 请求的 Origin 与当前本地服务不同源。",
                "code": "INVALID_ORIGIN",
            },
            status=403,
        )
        return False

    def do_GET(self):
        if self._require_local_host() is None:
            return
        if self._request_path() == "/api/health":
            self._send_json(self._health_payload())
            return
        self._serve_static_or_404()

    def do_HEAD(self):
        if self._require_local_host() is None:
            return
        if self._request_path() == "/api/health":
            self._send_json(self._health_payload(), include_body=False)
            return
        self._serve_static_or_404(head_only=True)

    def do_POST(self):
        authority = self._require_local_host()
        if authority is None:
            return
        if not self._require_same_origin_for_post(authority):
            return
        if self._request_path() != "/api/assist":
            self._send_json(
                {"error": "接口不存在。", "code": "NOT_FOUND"}, status=404
            )
            return

        if self.headers.get_content_type() != "application/json":
            self._send_json(
                {"error": "请求必须使用 JSON 格式。", "code": "INVALID_CONTENT_TYPE"},
                status=415,
            )
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            content_length = 0

        if content_length <= 0 or content_length > MAX_BODY_BYTES:
            self._send_json(
                {"error": "请求内容为空或过大。", "code": "INVALID_BODY_SIZE"},
                status=413,
            )
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(
                {"error": "请求正文不是有效的 JSON。", "code": "INVALID_REQUEST"},
                status=400,
            )
            return

        try:
            task, messages = validate_assist_request(payload)
        except ValueError as exc:
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

        model = get_model_name()
        request_options = {
            "model": model,
            "messages": [
                {"role": "system", "content": get_system_prompt(task)},
                *messages,
            ],
            "max_tokens": 1_000 if task == "triage_result" else 500,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if task in {"triage_questions", "triage_result"}:
            request_options["response_format"] = {"type": "json_object"}

        try:
            response = client.chat.completions.create(**request_options)
        except Exception:
            LOGGER.exception("调用模型服务失败")
            self._send_json(
                {
                    "error": "模型服务暂时不可用，请稍后重试。",
                    "code": "UPSTREAM_ERROR",
                },
                status=502,
            )
            return

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, KeyError, TypeError):
            content = None
        result = _validated_model_result(task, content)
        self._send_json({"task": task, "result": result, "model": model})

    def _send_json(self, payload, status=200, include_body=True):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
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
