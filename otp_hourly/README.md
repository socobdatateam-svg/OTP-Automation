# OTP Hourly

Lightweight bot server for SeaTalk. Google Apps Script watches cell `AD1` in your sheet, and when that value changes it calls this service. The service then renders the report range as an image and sends one interactive message card to the SeaTalk group webhook.

## Flow

1. Google Apps Script runs on a time-driven trigger.
2. The script reads `AD1` and compares it with the last stored value.
3. If `AD1` did not change, nothing happens.
4. If `AD1` changed, Apps Script sends `POST /trigger` to this bot.
5. The bot exports the configured Google Sheets range as PDF.
6. The bot converts the PDF to PNG with Poppler.
7. The bot trims and optimizes the PNG with ImageMagick.
8. The bot sends one interactive SeaTalk card with the rendered image and report link.

## Main Parts

- [bot_server.py](bot_server.py): receives trigger requests, renders the report image, and sends the SeaTalk webhook.
- [docs/google_apps_script_polling.gs](docs/google_apps_script_polling.gs): Apps Script that polls `AD1` and calls the bot when the value changes.
- [docs/render_web_service_deployment.md](docs/render_web_service_deployment.md): deployment steps for the bot service.

## Config

The app reads the local `.env` file directly:

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
BOT_TIMEZONE=Asia/Manila
BOT_REQUEST_TIMEOUT_SECONDS=30
BOT_RUN_ON_STARTUP=false
BOT_PDF_DPI=220
BOT_IMAGE_BORDER_PX=20
BOT_IMAGE_RESIZE_WIDTH=2200
BOT_USE_ENV_PROXY=false
TRIGGER_SHARED_SECRET=change-me
GOOGLE_SERVICE_ACCOUNT_FILE=google-service-account.json
```

`TRIGGER_SHARED_SECRET` is recommended if the bot is exposed on the internet. The Apps Script sends the same secret in its trigger request.

## Apps Script Setup

Use the script in [docs/google_apps_script_polling.gs](docs/google_apps_script_polling.gs).

1. Open your spreadsheet.
2. Go to `Extensions > Apps Script`.
3. Paste the script from `docs/google_apps_script_polling.gs`.
4. Fill in:
   - `spreadsheetId`
   - `sheetName`
   - `triggerCellA1` as `AD1`
   - `botTriggerUrl`
   - `sharedSecret`
5. Run `installMinuteTrigger()` once from Apps Script.
6. Authorize the script when prompted.
7. Run `watchSeatalkTriggerCell()` once to store the initial baseline value without sending an alert.

After that, Apps Script will check `AD1` every minute and only call the bot after the value changes.

Apps Script time-driven polling is minute-level, not second-level. If the `AD1` formula depends on time-based recalculation, make sure the spreadsheet recalculation setting supports minute updates.

## Trigger Contract

The bot accepts:

- `GET /` or `GET /healthz`: current service status
- `POST /trigger`: starts one send cycle

Example trigger payload:

```json
{
  "trigger": "apps_script_cell_change",
  "source": "google_apps_script",
  "trigger_cell": "AD1",
  "previous_value": "0",
  "current_value": "9:35AM Apr-18",
  "spreadsheet_id": "your-sheet-id",
  "tab_name": "bot_server",
  "fired_at": "2026-04-18T09:00:00.000Z",
  "shared_secret": "change-me"
}
```

## Message Format

Each trigger sends one interactive message card:

```text
[Interactive Message]
Title: Update as of h:mm AM/PM Mmm-dd
Description: FMS Latest Update: 9:35AM Apr-18
Image: rendered report snapshot
Button: View Report Link
```

## Docker

Build the image from `otp_hourly/`:

```powershell
docker build -t seatalk-otp-hourly .
```

Run the container:

```powershell
docker run -d --name seatalk-otp-hourly `
  -p 8080:8080 `
  -v ${PWD}/.env:/app/.env:ro `
  -v ${PWD}/google-service-account.json:/app/google-service-account.json:ro `
  seatalk-otp-hourly
```

Stop and remove the container:

```powershell
docker rm -f seatalk-otp-hourly
```

## Notes

- The bot no longer polls Google Sheets for cell changes. Apps Script does that job.
- Google Apps Script installable time-driven triggers can run as often as every minute, so this design is not suitable for sub-minute alerting.
- The container image still requires both `poppler-utils` and `imagemagick`.
- The Google service account must have access to the target spreadsheet so the bot can export the report range.
- Render deployment steps are documented in [docs/render_web_service_deployment.md](docs/render_web_service_deployment.md).
- UptimeRobot setup steps are documented in [docs/uptimerobot_setup.md](docs/uptimerobot_setup.md).
