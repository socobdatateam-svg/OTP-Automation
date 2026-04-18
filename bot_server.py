import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from zoneinfo import ZoneInfo

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build


LOGGER = logging.getLogger("seatalk-bot")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
MAX_SEATALK_IMAGE_BYTES = 5 * 1024 * 1024
ENV_LINE_PATTERN = re.compile(r"^\s*([A-Za-z0-9_]+)\s*[:=]\s*(.*?)\s*$")
REQUIRED_CONFIG_FIELDS = (
    "sheet_id",
    "tab_name",
    "capture_range",
    "seatalk_webhook_url",
    "report_link",
)
TRIGGER_METADATA_KEYS = (
    "source",
    "trigger_cell",
    "previous_value",
    "current_value",
    "spreadsheet_id",
    "tab_name",
    "fired_at",
    "note",
)


@dataclass(frozen=True)
class Config:
    sheet_id: str
    tab_name: str
    capture_range: str
    seatalk_webhook_url: str
    report_link: str
    timezone_name: str
    service_account_file: Path | None
    service_account_json: str
    trigger_shared_secret: str
    host: str
    port: int
    request_timeout_seconds: int
    run_on_startup: bool
    pdf_dpi: int
    image_border_px: int
    image_resize_width: int
    use_env_proxy: bool


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE_PATTERN.match(line)
        if not match:
            continue
        key, value = match.groups()
        values[key.strip()] = value.strip()
    return values


def get_setting(file_values: dict[str, str], file_key: str, env_key: str, default: str | None = None) -> str:
    return (
        os.getenv(env_key)
        or os.getenv(file_key)
        or file_values.get(env_key)
        or file_values.get(file_key)
        or (default or "")
    )


def parse_bool(value: str, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def ensure_binary(binary_name: str) -> None:
    if shutil.which(binary_name):
        return
    raise RuntimeError(f"Required binary not found in PATH: {binary_name}")


def validate_config(config: Config) -> None:
    missing = [field for field in REQUIRED_CONFIG_FIELDS if not getattr(config, field)]
    if missing:
        raise ValueError(f"Missing required config values: {', '.join(missing)}")
    if config.pdf_dpi <= 0:
        raise ValueError("BOT_PDF_DPI must be greater than 0.")
    if config.image_border_px < 0:
        raise ValueError("BOT_IMAGE_BORDER_PX must be zero or greater.")
    if config.image_resize_width <= 0:
        raise ValueError("BOT_IMAGE_RESIZE_WIDTH must be greater than 0.")

    if config.service_account_json:
        return

    if not config.service_account_file or not config.service_account_file.exists():
        raise FileNotFoundError(
            "No Google service account credentials found. "
            f"Checked GOOGLE_SERVICE_ACCOUNT_JSON and file: {config.service_account_file}"
        )


def load_config() -> Config:
    env_file_values = load_env_file(Path(".env"))

    service_account_json = get_setting(
        env_file_values,
        "google_service_account_json",
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "",
    ).strip()
    service_account_file_value = get_setting(
        env_file_values,
        "google_service_account_file",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        "/etc/secrets/google-service-account.json",
    ).strip()
    service_account_file = Path(service_account_file_value) if service_account_file_value else None

    config = Config(
        sheet_id=get_setting(env_file_values, "sheet_id", "SHEET_ID"),
        tab_name=get_setting(env_file_values, "tab_name", "TAB_NAME"),
        capture_range=get_setting(env_file_values, "capture_range", "CAPTURE_RANGE", "B2:M30"),
        seatalk_webhook_url=get_setting(env_file_values, "seatalk_webhook_url", "SEATALK_WEBHOOK_URL"),
        report_link=get_setting(env_file_values, "report_link", "REPORT_LINK"),
        timezone_name=get_setting(env_file_values, "timezone", "BOT_TIMEZONE", "Asia/Manila"),
        service_account_file=service_account_file,
        service_account_json=service_account_json,
        trigger_shared_secret=get_setting(
            env_file_values,
            "trigger_shared_secret",
            "TRIGGER_SHARED_SECRET",
            "",
        ).strip(),
        host=get_setting(env_file_values, "host", "BOT_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT") or get_setting(env_file_values, "port", "BOT_PORT", "8080")),
        request_timeout_seconds=int(
            get_setting(env_file_values, "request_timeout_seconds", "BOT_REQUEST_TIMEOUT_SECONDS", "30")
        ),
        run_on_startup=parse_bool(get_setting(env_file_values, "run_on_startup", "BOT_RUN_ON_STARTUP", ""), False),
        pdf_dpi=int(get_setting(env_file_values, "pdf_dpi", "BOT_PDF_DPI", "220")),
        image_border_px=int(get_setting(env_file_values, "image_border_px", "BOT_IMAGE_BORDER_PX", "20")),
        image_resize_width=int(get_setting(env_file_values, "image_resize_width", "BOT_IMAGE_RESIZE_WIDTH", "2200")),
        use_env_proxy=parse_bool(get_setting(env_file_values, "use_env_proxy", "BOT_USE_ENV_PROXY", ""), False),
    )
    validate_config(config)
    return config


def build_credentials(config: Config) -> service_account.Credentials:
    if config.service_account_json:
        try:
            service_account_info = json.loads(config.service_account_json)
        except json.JSONDecodeError as exc:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.") from exc
        return service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=SCOPES,
        )

    return service_account.Credentials.from_service_account_file(
        str(config.service_account_file),
        scopes=SCOPES,
    )


def build_auth_request(use_env_proxy: bool) -> Request:
    session = requests.Session()
    session.trust_env = use_env_proxy
    return Request(session=session)


def build_http_opener(use_env_proxy: bool) -> request.OpenerDirector:
    if use_env_proxy:
        return request.build_opener()
    return request.build_opener(request.ProxyHandler({}))


def format_update_timestamp(now: datetime) -> str:
    return now.strftime("%I:%M %p %b-%d").lstrip("0")


def filter_trigger_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in TRIGGER_METADATA_KEYS:
        if key in payload:
            metadata[key] = payload[key]
    return metadata


def build_interactive_message_payload(timestamp: str, report_link: str, image_bytes: bytes) -> dict[str, Any]:
    return {
        "tag": "interactive_message",
        "interactive_message": {
            "elements": [
                {
                    "element_type": "title",
                    "title": {
                        "text": f"Update as of {timestamp}",
                    },
                },
                {
                    "element_type": "description",
                    "description": {
                        "text": "-",
                    },
                },
                {
                    "element_type": "image",
                    "image": {
                        "content": base64.b64encode(image_bytes).decode("ascii"),
                    },
                },
                {
                    "element_type": "button",
                    "button": {
                        "button_type": "redirect",
                        "text": "View Report Link",
                        "mobile_link": {
                            "type": "web",
                            "path": report_link,
                        },
                        "desktop_link": {
                            "type": "web",
                            "path": report_link,
                        },
                    },
                },
            ]
        },
    }


class SeatalkBotService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.timezone = ZoneInfo(config.timezone_name)
        self.credentials = build_credentials(config)
        self.auth_request = build_auth_request(config.use_env_proxy)
        self.http_opener = build_http_opener(config.use_env_proxy)
        self.sheets_service = build("sheets", "v4", credentials=self.credentials, cache_discovery=False)

        self.sheet_gid: int | None = None
        self.run_lock = threading.Lock()
        self.last_run_started_at: datetime | None = None
        self.last_run_finished_at: datetime | None = None
        self.last_run_succeeded_at: datetime | None = None
        self.last_error: str | None = None
        self.last_trigger_received_at: datetime | None = None
        self.last_trigger_source: str | None = None
        self.last_trigger_metadata: dict[str, Any] | None = None

        ensure_binary("pdftocairo")
        ensure_binary("magick")

    def start(self) -> None:
        if self.config.run_on_startup:
            self.trigger_async(trigger="startup", trigger_metadata={"source": "startup"})

    def stop(self) -> None:
        return

    def trigger_async(self, trigger: str, trigger_metadata: dict[str, Any] | None = None) -> bool:
        if self.run_lock.locked():
            return False

        self.last_trigger_received_at = datetime.now(self.timezone)
        self.last_trigger_source = str((trigger_metadata or {}).get("source") or "external")
        self.last_trigger_metadata = trigger_metadata or None
        threading.Thread(
            target=self.run_once,
            kwargs={"trigger": trigger, "trigger_metadata": trigger_metadata},
            daemon=True,
        ).start()
        return True

    def run_once(self, trigger: str, trigger_metadata: dict[str, Any] | None = None) -> bool:
        if not self.run_lock.acquire(blocking=False):
            LOGGER.info("Skipping %s run because another execution is still in progress.", trigger)
            return False

        started_at = datetime.now(self.timezone)
        self.last_run_started_at = started_at
        LOGGER.info(
            "Starting bot cycle. trigger=%s source=%s time=%s",
            trigger,
            (trigger_metadata or {}).get("source", "external"),
            started_at.isoformat(),
        )

        try:
            image_bytes = self.render_report_image()
            payload = self.build_message_payload(started_at, image_bytes)
            self.post_to_seatalk(payload)
            self.last_error = None
            self.last_run_succeeded_at = datetime.now(self.timezone)
            LOGGER.info("Bot cycle completed successfully.")
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            LOGGER.exception("Bot cycle failed: %s", exc)
            return False
        finally:
            self.last_run_finished_at = datetime.now(self.timezone)
            self.run_lock.release()

    def render_report_image(self) -> bytes:
        runtime_root = Path(".runtime")
        runtime_root.mkdir(exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="seatalk-bot-", dir=runtime_root) as temp_dir:
            workdir = Path(temp_dir)
            pdf_path = workdir / "sheet-range.pdf"
            png_prefix = workdir / "sheet-range"
            raw_png_path = workdir / "sheet-range.png"
            final_png_path = workdir / "sheet-range-final.png"

            pdf_path.write_bytes(self.export_range_to_pdf())
            self.convert_pdf_to_png(pdf_path, png_prefix)
            self.optimize_png(raw_png_path, final_png_path)

            image_bytes = final_png_path.read_bytes()
            self.validate_image_size(image_bytes)
            return image_bytes

    def validate_image_size(self, image_bytes: bytes) -> None:
        if len(image_bytes) > MAX_SEATALK_IMAGE_BYTES:
            raise ValueError("Rendered PNG exceeds SeaTalk's 5MB image size limit.")

    def export_range_to_pdf(self) -> bytes:
        gid = self.fetch_sheet_gid()
        self.credentials.refresh(self.auth_request)

        query = parse.urlencode(
            {
                "exportFormat": "pdf",
                "format": "pdf",
                "gid": str(gid),
                "range": self.config.capture_range,
                "portrait": "false",
                "fitw": "true",
                "sheetnames": "false",
                "printtitle": "false",
                "pagenumbers": "false",
                "gridlines": "false",
                "fzr": "false",
                "attachment": "false",
                "size": "A4",
                "top_margin": "0.25",
                "bottom_margin": "0.25",
                "left_margin": "0.25",
                "right_margin": "0.25",
            }
        )
        url = f"https://docs.google.com/spreadsheets/d/{self.config.sheet_id}/export?{query}"
        http_request = request.Request(url, headers={"Authorization": f"Bearer {self.credentials.token}"})

        try:
            with self.http_opener.open(http_request, timeout=self.config.request_timeout_seconds) as response:
                pdf_bytes = response.read()
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Sheets export failed with HTTP {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Google Sheets export failed: {exc.reason}") from exc

        if not pdf_bytes.startswith(b"%PDF"):
            snippet = pdf_bytes[:200].decode("utf-8", errors="replace")
            raise RuntimeError(f"Google Sheets export did not return a PDF. Body starts with: {snippet}")
        return pdf_bytes

    def fetch_sheet_gid(self) -> int:
        if self.sheet_gid is not None:
            return self.sheet_gid

        response = (
            self.sheets_service.spreadsheets()
            .get(
                spreadsheetId=self.config.sheet_id,
                fields="sheets(properties(sheetId,title))",
            )
            .execute()
        )
        for sheet in response.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") == self.config.tab_name:
                self.sheet_gid = int(properties["sheetId"])
                return self.sheet_gid
        raise ValueError(f"Tab not found in spreadsheet: {self.config.tab_name}")

    def convert_pdf_to_png(self, pdf_path: Path, png_prefix: Path) -> None:
        command = [
            "pdftocairo",
            "-png",
            "-singlefile",
            "-r",
            str(self.config.pdf_dpi),
            str(pdf_path),
            str(png_prefix),
        ]
        self.run_subprocess(command, "Poppler PDF-to-PNG conversion failed")

    def optimize_png(self, raw_png_path: Path, final_png_path: Path) -> None:
        command = [
            "magick",
            str(raw_png_path),
            "-trim",
            "+repage",
            "-bordercolor",
            "white",
            "-border",
            str(self.config.image_border_px),
            "-resize",
            f"{self.config.image_resize_width}x>",
            "-strip",
            str(final_png_path),
        ]
        self.run_subprocess(command, "ImageMagick PNG optimization failed")

    def run_subprocess(self, command: list[str], error_message: str) -> None:
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            details = stderr or stdout or "no subprocess output"
            raise RuntimeError(f"{error_message}: {details}") from exc

    def build_message_payload(self, now: datetime, image_bytes: bytes) -> dict[str, Any]:
        timestamp = format_update_timestamp(now)
        return build_interactive_message_payload(timestamp, self.config.report_link, image_bytes)

    def post_to_seatalk(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.config.seatalk_webhook_url,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with self.http_opener.open(http_request, timeout=self.config.request_timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"SeaTalk webhook request failed with HTTP {exc.code}: {error_body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"SeaTalk webhook request failed: {exc.reason}") from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"SeaTalk returned invalid JSON: {raw_body}") from exc

        if parsed.get("code") != 0:
            raise RuntimeError(f"SeaTalk returned an error response: {parsed}")
        return parsed

    def status(self) -> dict[str, Any]:
        return {
            "running": self.run_lock.locked(),
            "last_run_started_at": self.last_run_started_at.isoformat() if self.last_run_started_at else None,
            "last_run_finished_at": self.last_run_finished_at.isoformat() if self.last_run_finished_at else None,
            "last_run_succeeded_at": self.last_run_succeeded_at.isoformat() if self.last_run_succeeded_at else None,
            "last_trigger_received_at": self.last_trigger_received_at.isoformat() if self.last_trigger_received_at else None,
            "last_trigger_source": self.last_trigger_source,
            "last_trigger_metadata": self.last_trigger_metadata,
            "last_error": self.last_error,
            "capture_range": self.config.capture_range,
            "tab_name": self.config.tab_name,
            "trigger_auth_enabled": bool(self.config.trigger_shared_secret),
        }


def build_handler(service: SeatalkBotService) -> type[BaseHTTPRequestHandler]:
    class BotHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path not in {"/", "/healthz"}:
                self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            self.respond_json(HTTPStatus.OK, service.status())

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/trigger":
                self.respond_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return

            try:
                payload = self.read_json_payload()
            except ValueError as exc:
                self.respond_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            if not self.authorize_trigger(payload):
                self.respond_json(HTTPStatus.FORBIDDEN, {"error": "Invalid trigger secret"})
                return

            trigger_name = str(payload.get("trigger") or "manual")
            trigger_metadata = filter_trigger_metadata(payload)
            if "source" not in trigger_metadata:
                trigger_metadata["source"] = self.headers.get("X-Trigger-Source", "external")

            started = service.trigger_async(trigger=trigger_name, trigger_metadata=trigger_metadata)
            if not started:
                self.respond_json(HTTPStatus.CONFLICT, {"status": "busy"})
                return
            self.respond_json(HTTPStatus.ACCEPTED, {"status": "started"})

        def read_json_payload(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length <= 0:
                return {}

            raw_body = self.rfile.read(content_length)
            if not raw_body:
                return {}

            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError as exc:
                raise ValueError("Request body must be valid JSON.") from exc

            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            return payload

        def authorize_trigger(self, payload: dict[str, Any]) -> bool:
            expected_secret = service.config.trigger_shared_secret
            if not expected_secret:
                return True

            supplied_secret = self.headers.get("X-Trigger-Secret") or str(payload.get("shared_secret") or "")
            return supplied_secret == expected_secret

        def respond_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            LOGGER.info("%s - %s", self.address_string(), format % args)

    return BotHandler


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    config = load_config()
    service = SeatalkBotService(config)
    service.start()

    server = ThreadingHTTPServer((config.host, config.port), build_handler(service))
    LOGGER.info("Seatalk bot server listening on %s:%s", config.host, config.port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Shutting down bot server.")
    finally:
        server.shutdown()
        service.stop()


if __name__ == "__main__":
    main()
