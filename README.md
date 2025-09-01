# STEP Analyzer (OCP + FastAPI)

Kleine service die `.stp/.step` files uitleest en teruggeeft:
- **length_mm**, **width_mm**, **height_mm** (bounding box in mm)
- **volume_m3**
- **weight_kg** (optioneel, als je `density` meegeeft in kg/m³, bv. 7850 voor staal)

## Endpoints
- `GET /healthz` → `{"ok": true}`
- `POST /analyze?url=<PUBLIC_STEP_URL>&density=7850`
  - Óf upload multipart: `file=@part.step`

## Snel testen (na deploy op Render)
```bash
curl https://<jouw-service>.onrender.com/healthz
curl -X POST "https://<jouw-service>.onrender.com/analyze?url=https://voorbeeld.nl/part.step&density=7850"
