# Inbound Bot Automation

This repository is now split into fully separated app folders.

## Apps

- [otp_hourly](otp_hourly/README.md): the existing working SeaTalk bot that renders the OTP hourly sheet snapshot and sends it after an Apps Script-triggered change in `AD1`.
- [otp_controltower](otp_controltower/README.md): a separate placeholder app for the next alert flow.

## Structure

```text
Inbound-bot-automation/
|-- otp_hourly/
`-- otp_controltower/
```

Each app should keep its own:

- `bot_server.py`
- `README.md`
- `.env.example`
- `Dockerfile`
- `docker-compose.yml`
- `requirements.txt`
- `docs/`

Deploy and configure each app from its own folder.
