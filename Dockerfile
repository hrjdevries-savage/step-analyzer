# Snelle en kleine Python-base
FROM python:3.11-slim

# Minimale systeempakketten voor OCP/OpenCascade (GL/X-libs die wheels verwachten)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglu1-mesa libxrender1 libxext6 libsm6 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Werkdirectory
WORKDIR /app

# Eerst requirements kopiëren zodat we layer-caching benutten
COPY requirements.txt ./requirements.txt

# LET OP: pin pip < 25 i.v.m. OCP + packaging marker bug
# Daarna requirements installeren en *vroeg* valideren dat OCP te importeren is
RUN python -m pip install --upgrade "pip<25" \
 && pip --version \
 && pip install --no-cache-dir -r requirements.txt \
 && python - <<'PY'
import sys
print("Python:", sys.version)
try:
    import OCP
    from OCP.STEPControl import STEPControl_Reader
    print("OCP import OK")
except Exception as e:
    print("OCP import FAILED:", repr(e))
    raise
PY

# App-bestanden
COPY . .

# Render zet $PORT; we exposen 8000 als default
ENV PORT=8000
EXPOSE 8000

# Start de app
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
