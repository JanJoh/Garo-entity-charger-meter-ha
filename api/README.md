# Local REST API

Swagger documents served by the charger (GARO Entity Compact) at `https://<host>/api/doc/swagger.json`, one file per firmware.
The integration does not read these files; they are kept as a reference for the API.

| File | Firmware | Fetched |
|---|---|---|
| [`swagger-4.10.3.json`](swagger-4.10.3.json) | 4.10.3 (revision 5bf98996f) | 2026-10-30 |
| [`swagger-2025-07-21.json`](swagger-2025-07-21.json) | ≤ 4.2.7 (the charger ran 4.2.7 until 30 Oct 2026; the exact version in July 2025 was not recorded) | 2025-07-21 |

## Changes in 4.10.3

Configuration parameters moved from `/config/config-parameter` to `/config/parameter/{group}/{parameter}`
(and the same under `/factory`). The old paths are no longer documented.

Added:
- `GET /config/parameter`
- `GET /config/parameter/{group}`
- `DELETE /config/parameter/{group}/{parameter}`
- `GET /config/parameter/{group}/{parameter}`
- `PUT /config/parameter/{group}/{parameter}`
- `GET /factory/parameter`
- `GET /factory/parameter/{group}`
- `DELETE /factory/parameter/{group}/{parameter}`
- `GET /factory/parameter/{group}/{parameter}`
- `PUT /factory/parameter/{group}/{parameter}`
- `GET /status/metervalue-sample`

Removed from the documentation:
- `DELETE /config/config-parameter`
- `GET /config/config-parameter`
- `PUT /config/config-parameter`
- `DELETE /factory/config-parameter`
- `GET /factory/config-parameter`
- `PUT /factory/config-parameter`
- `PUT /hal/adc-values`
- `PUT /hal/dcsense-x30`
- `PUT /hal/dcsense-x6`
- `PUT /hal/slac-response`
