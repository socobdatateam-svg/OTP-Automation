import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


def build_handler() -> type[BaseHTTPRequestHandler]:
    class BotHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/", "/healthz"}:
                self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            self.respond_json(HTTPStatus.OK, {"status": "ok", "service": "otp_controltower"})

        def do_HEAD(self) -> None:  # noqa: N802
            if self.path not in {"/", "/healthz"}:
                self.respond_empty(HTTPStatus.NOT_FOUND)
                return
            self.respond_empty(HTTPStatus.OK)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/trigger":
                self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            self.respond_json(
                HTTPStatus.NOT_IMPLEMENTED,
                {"error": "otp_controltower trigger flow is not implemented yet"},
            )

        def respond_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def respond_empty(self, status: HTTPStatus) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return BotHandler


def main() -> None:
    host = os.getenv("BOT_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("BOT_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), build_handler())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
