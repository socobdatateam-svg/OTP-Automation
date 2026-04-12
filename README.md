# SeaTalk Bot Server

Lightweight bot server for SeaTalk with this capture flow:

1. export Google Sheets range `B2:M30` to PDF
2. convert PDF to PNG with Poppler
3. trim and optimize PNG with ImageMagick
4. send a single interactive message card to the SeaTalk group
5. repeat every 10 minutes

## Message format

Each run sends one interactive message card:

```text
[Interactive Message]
Title: 🚚 On-Queue & Unloading Update
Description: as of **h:mm AM/PM Mmm-dd**
Image: rendered report snapshot
Button: View Report Link
```

## Config

The app reads the existing local `.env` file format directly:

```text
sheet_id: <google-sheet-id>
tab_name: bot_server
seatalk_webhook_url: <seatalk-webhook-url>
capture_range: B2:M30
report_link: <google-sheet-report-link>
```

Optional settings:

```text
BOT_HOST=0.0.0.0
BOT_PORT=8080
BOT_INTERVAL_MINUTES=10
BOT_TIMEZONE=Asia/Manila
BOT_REQUEST_TIMEOUT_SECONDS=30
BOT_RUN_ON_STARTUP=false
BOT_PDF_DPI=220
BOT_IMAGE_BORDER_PX=20
BOT_IMAGE_RESIZE_WIDTH=2200
BOT_USE_ENV_PROXY=false
GOOGLE_SERVICE_ACCOUNT_FILE=google-service-account.json
```

Use `.env.example` as the committed template and keep real values only in your local `.env`.

## Docker

Build the image:

```powershell
docker build -t seatalk-bot .
```

Run the container:

```powershell
docker run -d --name seatalk-bot `
  -p 8080:8080 `
  -v ${PWD}/.env:/app/.env:ro `
  -v ${PWD}/google-service-account.json:/app/google-service-account.json:ro `
  seatalk-bot
```

Stop and remove the container:

```powershell
docker rm -f seatalk-bot
```

`docker-compose.yml` is included if you want a compose-based start command on a machine that has Compose installed.

## Endpoints

- `GET /` or `GET /healthz`: current service status
- `POST /trigger`: manual run outside the 10-minute schedule

## Notes

- The container image installs both `poppler-utils` and `imagemagick`.
- The Google service account must have access to the target spreadsheet.
- Render deployment steps are documented in [docs/render_web_service_deployment.md](docs/render_web_service_deployment.md).
