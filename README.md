# STEP Analyzer (Render-ready)

FastAPI service die .stp/.step leest en L/B/H (mm), volume (m³) en optioneel gewicht (kg) teruggeeft.

- `GET /healthz` → `{"ok": true}`
- `POST /analyze?url=<PUBLIC_STEP_URL>&density=7850`
  - of upload multipart: `file=@part.step`
