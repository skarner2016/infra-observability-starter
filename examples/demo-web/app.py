"""demo-web:极简示例应用,输出 Prometheus 指标与 JSON 日志。"""

import json
import random
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

http_requests_total = 0
http_errors_total = 0
http_duration_sum = 0.0


def render_metrics() -> bytes:
    return (
        "# HELP demo_http_requests_total 收到的 HTTP 请求总数。\n"
        "# TYPE demo_http_requests_total counter\n"
        f"demo_http_requests_total {http_requests_total}\n"
        "# HELP demo_http_errors_total 返回 5xx 的请求总数。\n"
        "# TYPE demo_http_errors_total counter\n"
        f"demo_http_errors_total {http_errors_total}\n"
        "# HELP demo_request_duration_seconds_sum 请求处理耗时合计(秒)。\n"
        "# TYPE demo_request_duration_seconds_sum counter\n"
        f"demo_request_duration_seconds_sum {http_duration_sum:.3f}\n"
        "# HELP demo_request_duration_seconds_count 请求处理次数。\n"
        "# TYPE demo_request_duration_seconds_count counter\n"
        f"demo_request_duration_seconds_count {http_requests_total}\n"
        "# HELP demo_random_value 演示用随机数。\n"
        "# TYPE demo_random_value gauge\n"
        f"demo_random_value {random.random():.3f}\n"
    ).encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "demo-web/1.0"

    def log_message(self, *args):
        pass

    def do_GET(self):
        global http_requests_total, http_errors_total, http_duration_sum
        start = time.monotonic()
        path = self.path.split("?", 1)[0]

        if path == "/metrics":
            status, body, content_type = 200, render_metrics(), "text/plain; version=0.0.4"
        elif path == "/":
            status, body, content_type = 200, b'{"service": "demo-web", "message": "hello"}\n', "application/json"
        elif path == "/slow":
            time.sleep(random.uniform(0.05, 0.3))
            status, body, content_type = 200, b'{"service": "demo-web", "message": "slow request done"}\n', "application/json"
        elif path == "/error":
            http_errors_total += 1
            status, body, content_type = 500, b'{"service": "demo-web", "error": "something went wrong"}\n', "application/json"
        else:
            status, body, content_type = 404, b'{"service": "demo-web", "error": "not found"}\n', "application/json"

        duration = time.monotonic() - start
        http_requests_total += 1
        http_duration_sum += duration

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

        print(
            json.dumps(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "service": "demo-web",
                    "method": self.command,
                    "path": path,
                    "status": status,
                    "duration_ms": round(duration * 1000, 2),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    port = 8080
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"demo-web listening on :{port}", flush=True)
    server.serve_forever()
