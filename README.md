# STEP Analyzer

Eenvoudige FastAPI-service om STEP (.step/.stp) bestanden te lezen met OpenCascade (OCP) en basis-informatie terug te geven.

## Endpoints

- `GET /` — tekst “running”
- `GET /healthz` — healthcheck + check of OCP importeerbaar is
- `POST /analyze` — upload een `.step` of `.stp` bestand (form field: `file`)

Voorbeeld (curl):

```bash
curl -fsSL https://<jouw-render-url>/healthz
curl -F "file=@model.step" https://<jouw-render-url>/analyze
