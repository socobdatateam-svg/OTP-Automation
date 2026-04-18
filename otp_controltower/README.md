# OTP Controltower

This app is intentionally separated from `otp_hourly`.

Current state:

- independent folder
- independent Docker files
- independent `.env.example`
- placeholder HTTP service

Endpoints:

- `GET /` or `GET /healthz`
- `POST /trigger`

Use this folder for the next control tower alert flow without mixing logic into `otp_hourly`.
